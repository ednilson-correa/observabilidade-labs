"""Gerador de carga (só biblioteca padrão) para as 3 instâncias da API.

Cada alvo recebe a MESMA mistura de requisições, para que a diferença entre
os painéis venha só da configuração do Java agent:
  60% GET /pedidos · 30% POST /pedidos · 10% GET /pedidos/lento
"""
import os
import random
import threading
import time
import urllib.error
import urllib.request

ALVOS = [a.strip() for a in os.environ.get(
    "ALVOS", "http://app-legado:8080,http://app-dup:8080,http://app-v3:8080").split(",") if a.strip()]
RPS = float(os.environ.get("REQUISICOES_POR_SEGUNDO", "10"))  # por alvo

ROTAS = [("GET", "/pedidos", 60), ("POST", "/pedidos", 30), ("GET", "/pedidos/lento", 10)]
PESOS = [r[2] for r in ROTAS]


def chamar(base: str) -> None:
    metodo, caminho, _ = random.choices(ROTAS, weights=PESOS)[0]
    req = urllib.request.Request(base + caminho, method=metodo, data=b"" if metodo == "POST" else None)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            r.read()
    except (urllib.error.URLError, OSError):
        pass  # app ainda subindo: segue o jogo


def laco(base: str, rps: float) -> None:
    intervalo = 1.0 / rps
    while True:
        inicio = time.monotonic()
        chamar(base)
        time.sleep(max(0.0, intervalo - (time.monotonic() - inicio)))


if __name__ == "__main__":
    print(f"loadgen: {RPS} req/s para cada alvo: {ALVOS}", flush=True)
    for alvo in ALVOS:
        for _ in range(2):  # 2 threads por alvo, metade da taxa cada
            threading.Thread(target=laco, args=(alvo, RPS / 2), daemon=True).start()
    while True:
        time.sleep(3600)
