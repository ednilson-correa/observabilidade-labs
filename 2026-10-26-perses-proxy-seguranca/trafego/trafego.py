"""Gerador de tráfego do lab (só stdlib).

1. A cada INTERVALO segundos, consulta o proxy de datasources de cada Perses
   (`/proxy/globaldatasources/<ds>/api/v1/query?query=up`) e registra o
   código HTTP devolvido e a duração.
2. Registra se a resposta do proxy veio com o header
   `Content-Security-Policy: sandbox ...` (novo no 0.55).
3. Expõe tudo em /metrics (formato texto do Prometheus) na porta 8000.

Variáveis de ambiente:
  ALVOS      lista "nome|versao|url_base" separada por vírgula
  DATASOURCES lista de datasources Prometheus a testar (padrão: prom-local,prom-rede)
  INTERVALO  segundos entre rodadas (padrão: 5)
  ESPERA_INICIAL segundos antes da primeira rodada, para os Perses subirem (padrão: 15)
"""

import os
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ALVOS = [
    tuple(item.split("|"))
    for item in os.environ.get(
        "ALVOS",
        "perses-054|0.54.0|http://prometheus:8054,"
        "perses-055|0.55.0|http://prometheus:8055,"
        "perses-055-liberado|0.55.0|http://prometheus:8056",
    ).split(",")
    if item.strip()
]
DATASOURCES = [d for d in os.environ.get("DATASOURCES", "prom-local,prom-rede").split(",") if d]
INTERVALO = float(os.environ.get("INTERVALO", "5"))
PORTA = int(os.environ.get("PORTA", "8000"))
ESPERA_INICIAL = float(os.environ.get("ESPERA_INICIAL", "15"))

_lock = threading.Lock()
_requisicoes = {}  # (instancia, versao, datasource, code) -> contador
_duracao = {}  # (instancia, versao, datasource) -> [soma, contagem]
_ultimo = {}  # (instancia, versao, datasource) -> último código
_csp = {}  # (instancia, versao) -> 1 se a resposta do proxy trouxe CSP sandbox


def _inc(dic, chave, valor=1):
    dic[chave] = dic.get(chave, 0) + valor


def consultar(url):
    """Devolve (código HTTP, segundos, CSP sandbox presente?). Código 0 = falha de conexão."""
    inicio = time.monotonic()
    csp = False
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            resp.read()
            codigo = resp.status
            csp = "sandbox" in (resp.headers.get("Content-Security-Policy") or "")
    except urllib.error.HTTPError as erro:
        codigo = erro.code
    except Exception:  # conexão recusada, timeout, DNS...
        codigo = 0
    return codigo, time.monotonic() - inicio, csp


def rodada():
    for nome, versao, base in ALVOS:
        for ds in DATASOURCES:
            url = f"{base}/proxy/globaldatasources/{ds}/api/v1/query?query=up"
            codigo, segundos, csp = consultar(url)
            with _lock:
                if codigo == 200:
                    _csp[(nome, versao)] = 1 if csp else 0
                _inc(_requisicoes, (nome, versao, ds, str(codigo)))
                soma = _duracao.setdefault((nome, versao, ds), [0.0, 0])
                soma[0] += segundos
                soma[1] += 1
                _ultimo[(nome, versao, ds)] = codigo


def laco():
    time.sleep(ESPERA_INICIAL)
    while True:
        try:
            rodada()
        except Exception as erro:  # nunca derrubar o gerador
            print("erro na rodada:", erro, flush=True)
        time.sleep(INTERVALO)


def metricas():
    linhas = [
        "# HELP lab_perses_proxy_requests_total Requisições ao proxy de datasources do Perses, por código HTTP.",
        "# TYPE lab_perses_proxy_requests_total counter",
    ]
    with _lock:
        for (inst, ver, ds, code), n in sorted(_requisicoes.items()):
            linhas.append(
                f'lab_perses_proxy_requests_total{{instancia="{inst}",versao="{ver}",datasource="{ds}",code="{code}"}} {n}'
            )
        linhas += [
            "# HELP lab_perses_proxy_request_duration_seconds Duração das requisições ao proxy.",
            "# TYPE lab_perses_proxy_request_duration_seconds summary",
        ]
        for (inst, ver, ds), (soma, cont) in sorted(_duracao.items()):
            rot = f'instancia="{inst}",versao="{ver}",datasource="{ds}"'
            linhas.append(f"lab_perses_proxy_request_duration_seconds_sum{{{rot}}} {soma:.6f}")
            linhas.append(f"lab_perses_proxy_request_duration_seconds_count{{{rot}}} {cont}")
        linhas += [
            "# HELP lab_perses_proxy_last_status Último código HTTP devolvido pelo proxy (0 = falha de conexão).",
            "# TYPE lab_perses_proxy_last_status gauge",
        ]
        for (inst, ver, ds), code in sorted(_ultimo.items()):
            linhas.append(
                f'lab_perses_proxy_last_status{{instancia="{inst}",versao="{ver}",datasource="{ds}"}} {code}'
            )
        linhas += [
            "# HELP lab_perses_proxy_csp_sandbox 1 se a última resposta 200 do proxy trouxe Content-Security-Policy: sandbox.",
            "# TYPE lab_perses_proxy_csp_sandbox gauge",
        ]
        for (inst, ver), v in sorted(_csp.items()):
            linhas.append(f'lab_perses_proxy_csp_sandbox{{instancia="{inst}",versao="{ver}"}} {v}')
    return "\n".join(linhas) + "\n"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/metrics"):
            corpo = metricas().encode()
            tipo = "text/plain; version=0.0.4"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *args):  # silencia o log de acesso
        pass


if __name__ == "__main__":
    threading.Thread(target=laco, daemon=True).start()
    print(f"trafego: {len(ALVOS)} instâncias, datasources={DATASOURCES}, porta={PORTA}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORTA), Handler).serve_forever()
