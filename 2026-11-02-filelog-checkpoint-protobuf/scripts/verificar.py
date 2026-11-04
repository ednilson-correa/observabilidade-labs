#!/usr/bin/env python3
"""Compara as instâncias usando o Prometheus do lab. Só biblioteca padrão.

uso: python3 scripts/verificar.py [--url http://localhost:9090] [--janela 5m] [--tempo <unix>]
Rode com a carga ativa há mais tempo que a janela. Enquanto a janela ainda pega o
início da série, rate() fica abaixo do valor real (linhas/s menor que LINHAS_SEG),
embora a comparação entre as instâncias continue válida.
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request

JSON, PROTO, NOVA = "json-0.163.1", "protobuf-0.163.1", "protobuf-0.164.0"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:9090")
    ap.add_argument("--janela", default="5m")
    ap.add_argument("--tempo")
    a = ap.parse_args()

    def consulta(expr):
        q = {"query": expr}
        if a.tempo:
            q["time"] = a.tempo
        with urllib.request.urlopen(f"{a.url}/api/v1/query?{urllib.parse.urlencode(q)}") as r:
            return {x["metric"].get("instancia"): float(x["value"][1]) for x in json.load(r)["data"]["result"]}

    cpu = consulta(f"rate(otelcol_process_cpu_seconds[{a.janela}])")
    aloc = consulta(f"rate(otelcol_process_runtime_total_alloc_bytes[{a.janela}])")
    rss = consulta("otelcol_process_memory_rss")
    vazao = consulta(f"rate(otelcol_receiver_accepted_log_records[{a.janela}])")
    faltando = [i for i in (JSON, PROTO, NOVA) if i not in cpu]
    if faltando:
        sys.exit(f"FALHA: sem dados de {faltando}. Espere a carga rodar por alguns minutos.")

    print(f"{'instância':<20}{'CPU (núcleos)':>15}{'alocação (MB/s)':>18}{'RSS (MB)':>10}{'linhas/s':>10}")
    for i in (JSON, PROTO, NOVA):
        print(f"{i:<20}{cpu[i]:>15.3f}{aloc[i] / 1e6:>18.1f}{rss[i] / 1e6:>10.0f}{vazao[i]:>10.1f}")
    print(f"\nprotobuf x JSON, mesma versão: CPU {100 * (cpu[PROTO] / cpu[JSON] - 1):+.1f}%, alocação {100 * (aloc[PROTO] / aloc[JSON] - 1):+.1f}%")

    falhas = []
    if max(vazao.values()) - min(vazao.values()) > 0.05 * max(vazao.values()):
        falhas.append("as vazões diferem mais de 5%: a comparação não vale")
    if cpu[PROTO] >= cpu[JSON]:
        falhas.append("protobuf não usou menos CPU que JSON")
    print("\nOK" if not falhas else "\nFALHA: " + "; ".join(falhas))
    sys.exit(1 if falhas else 0)


if __name__ == "__main__":
    main()
