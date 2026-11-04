#!/usr/bin/env python3
"""Testa o que acontece com o checkpoint em upgrade e rollback do Collector.

Sobe um Collector por vez sobre o MESMO file_storage e conta quantas linhas cada
versão leu. Uma linha lida de novo é log duplicado no seu backend.

uso:
  python3 scripts/migracao.py                  # com Docker (imagens oficiais)
  python3 scripts/migracao.py --nativo <dir>   # com binários <dir>/col-<versão>
"""
import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import checkpoint  # noqa: E402

RAIZ = pathlib.Path(__file__).resolve().parent.parent
PORTA = 18899
ARQUIVOS = 200
LINHAS_INICIAIS = 15
GATE_OFF = "--feature-gates=-filelog.protobufCheckpointEncoding"
ESPERA = 12


class Coletor:
    def __init__(self, base, nativo):
        self.base, self.nativo = base, nativo
        self.proc = None

    def subir(self, versao, gate=None):
        if self.nativo:
            cmd = [str(pathlib.Path(self.nativo) / f"col-{versao}"), f"--config={RAIZ}/otel-collector.yaml"]
            env = dict(os.environ, STORAGE_DIR=f"{self.base}/storage", LOG_GLOB=f"{self.base}/logs/*.log",
                       METRICS_PORT=str(PORTA), INSTANCIA="migracao")
        else:
            cmd = ["docker", "run", "--rm", "--name", "lab-migracao",
                   # mesmo usuário do script, para ele conseguir ler o checkpoint sem sudo
                   "--user", f"{os.getuid()}:{os.getgid()}",
                   "-p", f"127.0.0.1:{PORTA}:{PORTA}", "-e", f"METRICS_PORT={PORTA}", "-e", "INSTANCIA=migracao",
                   "-v", f"{RAIZ}/otel-collector.yaml:/etc/otelcol-contrib/config.yaml:ro",
                   "-v", f"{self.base}/logs:/logs:ro", "-v", f"{self.base}/storage:/var/lib/otelcol/file_storage",
                   f"otel/opentelemetry-collector-contrib:{versao}", "--config=/etc/otelcol-contrib/config.yaml"]
            env = None
        if gate:
            cmd.append(gate)
        self.saida = open(f"{self.base}/saida.log", "w")
        self.proc = subprocess.Popen(cmd, env=env, stdout=self.saida, stderr=subprocess.STDOUT)

    def linhas(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{PORTA}/metrics", timeout=3) as r:
            for ln in r.read().decode().splitlines():
                if ln.startswith("otelcol_receiver_accepted_log_records"):
                    return int(float(ln.rsplit(" ", 1)[1]))
        return 0

    def medir(self):
        """Espera estabilizar, devolve quantas linhas foram lidas e encerra."""
        time.sleep(ESPERA)
        if self.proc.poll() is not None:
            return None
        total = None
        for _ in range(5):
            try:
                total = self.linhas()
                break
            except OSError:
                time.sleep(2)
        self.parar()
        return total

    def parar(self):
        if self.proc.poll() is None:
            if self.nativo:
                self.proc.terminate()
            else:
                subprocess.run(["docker", "stop", "-t", "5", "lab-migracao"], capture_output=True)
            self.proc.wait(timeout=30)
        self.saida.close()
        time.sleep(1)

    def formato(self):
        for _, tam, fmt in (x for x in checkpoint.listar(f"{self.base}/storage/receiver_filelog_") if "knownFiles" in x[0]):
            return fmt, tam
        return "nenhum", 0

    def erro(self):
        linhas = pathlib.Path(f"{self.base}/saida.log").read_text(errors="replace").splitlines()
        erros = [ln for ln in linhas if ln.startswith("Error") or "\terror\t" in ln or "failed" in ln.lower()]
        return (erros[-1] if erros else "")[:300]


def acrescentar(base, seq):
    for a in range(ARQUIVOS):
        with open(f"{base}/logs/pod-{a:05d}.log", "a") as arq:
            arq.write(f"2026-11-02T00:00:00Z INFO arquivo={a} seq={seq} linha nova\n")


def preparar(base):
    os.makedirs(f"{base}/logs")
    os.makedirs(f"{base}/storage")
    os.chmod(f"{base}/storage", 0o777)
    for a in range(ARQUIVOS):
        with open(f"{base}/logs/pod-{a:05d}.log", "w") as arq:
            for s in range(LINHAS_INICIAIS):
                arq.write(f"2026-11-02T00:00:00Z INFO arquivo={a} seq={s} mensagem de exemplo com tamanho razoavel\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nativo")
    ap.add_argument("--antes", default="0.163.1")
    ap.add_argument("--depois", default="0.164.0")
    ap.add_argument("--antiga", default="0.147.0", help="sem suporte a checkpoint protobuf")
    ap.add_argument("--primeira", default="0.148.0", help="primeira que lê protobuf")
    args = ap.parse_args()

    base = tempfile.mkdtemp(prefix="lab-migracao-")
    os.chmod(base, 0o755)
    preparar(base)
    c = Coletor(base, args.nativo)
    res = []

    def passo(nome, versao, esperado, gate=None, novas=0):
        # esperado = linhas que uma leitura correta traria; além disso é duplicata
        if novas:
            acrescentar(base, 9000 + len(res))
        antes = c.formato() if res else ("nenhum", 0)
        c.subir(versao, gate)
        lidas = c.medir()
        fmt, tam = c.formato()
        item = {"passo": nome, "versao": versao, "linhas_novas": novas, "linhas_lidas": lidas,
                "esperado": esperado, "checkpoint_antes": antes[0], "checkpoint_depois": fmt, "checkpoint_bytes": tam}
        if lidas is None:
            item["erro"] = c.erro()
        res.append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)

    total = ARQUIVOS * LINHAS_INICIAIS
    try:
        passo("1. primeira leitura, JSON", args.antes, total, GATE_OFF)
        passo("2. upgrade JSON para 0.164", args.depois, ARQUIVOS, novas=ARQUIVOS)
        passo("3. 0.164 com a gate desligada", args.depois, None, GATE_OFF)
        passo("4. rollback para a primeira que lê protobuf", args.primeira, ARQUIVOS, novas=ARQUIVOS)
        passo("5. volta para 0.164", args.depois, 0)
        passo("6. rollback para versão sem protobuf", args.antiga, ARQUIVOS, novas=ARQUIVOS)
        # O passo 6 não sobe, mas o que ele deixou no disco importa. Testa os dois
        # caminhos a partir do MESMO estado: reiniciar a versão antiga ou voltar.
        shutil.copytree(f"{base}/storage", f"{base}/storage-copia")
        passo("7a. restart automático da versão sem protobuf", args.antiga, ARQUIVOS)
        shutil.rmtree(f"{base}/storage")
        shutil.copytree(f"{base}/storage-copia", f"{base}/storage")
        passo("7b. desiste do rollback e volta para 0.164", args.depois, ARQUIVOS)
    finally:
        if c.proc and c.proc.poll() is None:
            c.parar()
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    main()
