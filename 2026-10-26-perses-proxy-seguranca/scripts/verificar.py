#!/usr/bin/env python3
"""Matriz de verificação do lab: Perses 0.54 x 0.55 (padrão) x 0.55 (loopback liberado).

Roda do host (WSL), contra as portas publicadas pelo docker compose. Só stdlib.

    python3 scripts/verificar.py

Cada linha compara o código HTTP obtido com o esperado. Datasources criados
pelo teste são apagados no final. Sai com código 1 se algo divergir.
"""

import json
import os
import sys
import urllib.error
import urllib.request

INSTANCIAS = [
    ("0.54", os.environ.get("PERSES_054", "http://localhost:8054")),
    ("0.55 padrão", os.environ.get("PERSES_055", "http://localhost:8055")),
    ("0.55 liberado", os.environ.get("PERSES_055_LIBERADO", "http://localhost:8056")),
]


def req(metodo, url, corpo=None):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    r = urllib.request.Request(url, data=dados, method=metodo, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, dict(resp.headers), resp.read().decode(errors="replace")
    except urllib.error.HTTPError as erro:
        return erro.code, dict(erro.headers), erro.read().decode(errors="replace")
    except Exception as erro:  # instância fora do ar
        return 0, {}, str(erro)


def datasource(nome, url):
    return {
        "kind": "GlobalDatasource",
        "metadata": {"name": nome},
        "spec": {
            "default": False,
            "plugin": {
                "kind": "PrometheusDatasource",
                "spec": {"proxy": {"kind": "HTTPProxy", "spec": {"url": url}}},
            },
        },
    }


# (descrição, função que devolve (código, detalhe), esperado por instância)
def proxy(ds):
    def f(base):
        codigo, headers, _ = req("GET", f"{base}/proxy/globaldatasources/{ds}/api/v1/query?query=up")
        return codigo, ""
    return f


def criar(nome, url):
    def f(base):
        codigo, _, corpo = req("POST", f"{base}/api/v1/globaldatasources", datasource(nome, url))
        if codigo in (200, 201):
            req("DELETE", f"{base}/api/v1/globaldatasources/{nome}")
            return 200, ""
        detalhe = ""
        try:
            detalhe = json.loads(corpo).get("message", "")
        except Exception:
            pass
        return codigo, detalhe
    return f


def csp(base):
    _, headers, _ = req("GET", f"{base}/proxy/globaldatasources/prom-rede/api/v1/query?query=up")
    valor = {k.lower(): v for k, v in headers.items()}.get("content-security-policy", "")
    return ("presente" if "sandbox" in valor else "ausente"), ""


TESTES = [
    ("Proxy → prom-local (http://localhost:9090), salvo antes do upgrade", proxy("prom-local"), [200, 403, 200]),
    ("Proxy → prom-rede (http://prometheus:9090, rede privada)", proxy("prom-rede"), [200, 200, 200]),
    ("Salvar datasource novo em http://localhost:9090", criar("teste-localhost", "http://localhost:9090"), [200, 400, 200]),
    ("Salvar datasource em http://169.254.169.254 (metadata de nuvem)", criar("teste-metadata", "http://169.254.169.254"), [200, 400, 400]),
    ("Salvar datasource em http://2130706433:9090 (127.0.0.1 em decimal)", criar("teste-decimal", "http://2130706433:9090"), [200, 400, 400]),
    ("Salvar datasource com credencial na URL (user:senha@)", criar("teste-credencial", "http://lab:senha@prometheus:9090"), [200, 400, 400]),
    ("Header CSP sandbox na resposta do proxy", csp, ["ausente", "presente", "presente"]),
]


def main():
    largura = max(len(t[0]) for t in TESTES)
    cab = f"{'Teste':<{largura}}  " + "  ".join(f"{n:>14}" for n, _ in INSTANCIAS)
    print(cab)
    print("-" * len(cab))
    falhas = 0
    detalhes = []
    for descricao, funcao, esperados in TESTES:
        celulas = []
        for (nome, base), esperado in zip(INSTANCIAS, esperados):
            obtido, detalhe = funcao(base)
            ok = obtido == esperado
            falhas += 0 if ok else 1
            celulas.append(f"{str(obtido) + (' ✔' if ok else ' ✘(' + str(esperado) + ')'):>14}")
            if detalhe and nome == "0.55 padrão":
                detalhes.append(f"  [{nome}] {descricao}: {detalhe[:160]}")
        print(f"{descricao:<{largura}}  " + "  ".join(celulas))
    if detalhes:
        print("\nMensagens do 0.55 (padrão):")
        print("\n".join(detalhes))
    print(f"\n{'OK: todas as verificações bateram.' if not falhas else f'{falhas} verificação(ões) divergiram.'}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
