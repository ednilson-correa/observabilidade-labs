#!/usr/bin/env python3
"""Gerador de traces do lab (somente biblioteca padrão do Python).

Simula uma loja com dois serviços e envia OTLP/HTTP (JSON) para o Collector:

    frontend  GET /checkout  (SERVER)
      └── checkout  POST /pagar  (SERVER)

- TRACES_POR_SEGUNDO traces por segundo (padrão: 20)  -> 2 spans por trace
- PERCENTUAL_ERRO % dos traces terminam com erro no checkout (padrão: 5)

Como os números de entrada são conhecidos, dá para comparar o que o Tempo
mostra (amostrado) com a "verdade" (span_metrics no Prometheus).
"""
import json
import os
import random
import time
import urllib.error
import urllib.request

ENDPOINT = os.getenv("OTLP_ENDPOINT", "http://otel-collector:4318").rstrip("/") + "/v1/traces"
TPS = float(os.getenv("TRACES_POR_SEGUNDO", "20"))
ERRO_PCT = float(os.getenv("PERCENTUAL_ERRO", "5"))
LOTE_SEGUNDOS = 1.0


def _id(n_bytes: int) -> str:
    # IDs aleatórios: o trace ID é a fonte de aleatoriedade (W3C Trace Context
    # nível 2) usada pelo probabilistic_sampler no modo "proportional".
    return os.urandom(n_bytes).hex()


def _attr(chave, valor):
    return {"key": chave, "value": {"stringValue": valor}}


def _resource(servico):
    return {
        "attributes": [
            _attr("service.name", servico),
            _attr("service.namespace", "loja"),
            _attr("deployment.environment.name", "lab"),
        ]
    }


def gerar_lote(n_traces: int):
    spans_frontend, spans_checkout = [], []
    agora = time.time_ns()
    for _ in range(n_traces):
        trace_id = _id(16)
        raiz, filho = _id(8), _id(8)
        erro = random.random() * 100 < ERRO_PCT
        dur_checkout = int(random.uniform(20, 120) * 1e6)  # 20–120 ms
        if erro:
            dur_checkout += int(300 * 1e6)  # erros também são mais lentos
        dur_frontend = dur_checkout + int(random.uniform(2, 10) * 1e6)
        inicio = agora - dur_frontend
        spans_frontend.append({
            "traceId": trace_id, "spanId": raiz, "name": "GET /checkout",
            "kind": 2, "startTimeUnixNano": str(inicio),
            "endTimeUnixNano": str(inicio + dur_frontend),
            "attributes": [_attr("http.request.method", "GET"), _attr("http.route", "/checkout")],
            "status": {"code": 2 if erro else 0},
        })
        spans_checkout.append({
            "traceId": trace_id, "spanId": filho, "parentSpanId": raiz,
            "name": "POST /pagar", "kind": 2,
            "startTimeUnixNano": str(inicio + 1_000_000),
            "endTimeUnixNano": str(inicio + 1_000_000 + dur_checkout),
            "attributes": [_attr("http.request.method", "POST"), _attr("http.route", "/pagar"),
                           _attr("pagamento.metodo", random.choice(["pix", "cartao", "boleto"]))],
            "status": {"code": 2 if erro else 1},
        })
    escopo = {"name": "observabilidade-labs/loadgen", "version": "1.0.0"}
    return {"resourceSpans": [
        {"resource": _resource("frontend"), "scopeSpans": [{"scope": escopo, "spans": spans_frontend}]},
        {"resource": _resource("checkout"), "scopeSpans": [{"scope": escopo, "spans": spans_checkout}]},
    ]}


def enviar(payload):
    req = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status


def main():
    print(f"loadgen: {TPS} traces/s ({2 * TPS} spans/s), {ERRO_PCT}% de erro -> {ENDPOINT}", flush=True)
    acumulado = 0.0
    while True:
        t0 = time.monotonic()
        acumulado += TPS * LOTE_SEGUNDOS
        n = int(acumulado)
        acumulado -= n
        try:
            if n:
                enviar(gerar_lote(n))
        except (urllib.error.URLError, OSError) as e:
            print(f"loadgen: falha ao enviar ({e}); tentando de novo", flush=True)
        time.sleep(max(0.0, LOTE_SEGUNDOS - (time.monotonic() - t0)))


if __name__ == "__main__":
    main()
