"""Cria ARQUIVOS arquivos de log e acrescenta LINHAS_SEG linhas por segundo, em
rodízio. Cada arquivo começa com mais de 1 KB para ter a impressão digital
(fingerprint) completa de 1.000 bytes, como em um node Kubernetes de verdade.

A cada minuto grava em /logs/.contagem o total de linhas escritas.
"""
import itertools
import os
import sys
import time

DIR = os.environ.get("LOG_DIR", "/logs")
ARQUIVOS = int(os.environ.get("ARQUIVOS", "1000"))
LINHAS_SEG = int(os.environ.get("LINHAS_SEG", "200"))
LINHA = "2026-11-02T00:00:00Z INFO arquivo={a} seq={s} mensagem de exemplo com tamanho razoavel\n"


def main():
    os.makedirs(DIR, exist_ok=True)
    total = 0
    arquivos = []
    for a in range(ARQUIVOS):
        caminho = os.path.join(DIR, f"pod-{a:05d}.log")
        novo = not os.path.exists(caminho)
        arq = open(caminho, "a", buffering=1)
        if novo:
            # conteúdo único no início: fingerprints diferentes para cada arquivo
            for s in range(15):
                arq.write(LINHA.format(a=a, s=s))
                total += 1
        arquivos.append(arq)
    print(f"{ARQUIVOS} arquivos prontos em {DIR}", flush=True)
    rodizio = itertools.cycle(range(ARQUIVOS))
    prox = time.monotonic()
    ultimo = 0.0
    seq = 1000
    while True:
        for _ in range(max(1, LINHAS_SEG // 10)):
            a = next(rodizio)
            arquivos[a].write(LINHA.format(a=a, s=seq))
            seq += 1
            total += 1
        prox += 0.1
        time.sleep(max(0, prox - time.monotonic()))
        if time.monotonic() - ultimo > 60:
            ultimo = time.monotonic()
            with open(os.path.join(DIR, ".contagem"), "w") as c:
                c.write(str(total))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
