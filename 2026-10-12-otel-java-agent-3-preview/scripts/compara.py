#!/usr/bin/env python3
"""Compara a telemetria de banco das 3 instâncias (legado x dup x preview 3.0).

Só biblioteca padrão. Lê:
  - spans do Jaeger (API v3: /api/v3/traces)
  - métricas do Prometheus (/api/v1/query)

Uso:  python3 scripts/compara.py [minutos]     (padrão: 5)
Variáveis: JAEGER_URL (http://localhost:16686), PROMETHEUS_URL (http://localhost:9090)
"""
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request

JAEGER = os.environ.get("JAEGER_URL", "http://localhost:16686")
PROM = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
SERVICOS = ["pedidos-legado", "pedidos-dup", "pedidos-v3"]
CHAVES = [
    ("db.system", "legado"), ("db.name", "legado"), ("db.operation", "legado"),
    ("db.statement", "legado"), ("db.user", "legado"), ("db.connection_string", "legado"),
    ("db.system.name", "novo"), ("db.namespace", "novo"), ("db.query.summary", "novo"),
    ("db.query.text", "novo"), ("server.address", "ambos"), ("server.port", "ambos"),
]


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.load(r)


def iso(t: dt.datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def spans_de_banco(servico: str, minutos: int) -> list[tuple[str, dict]]:
    agora = dt.datetime.now(dt.timezone.utc)
    q = urllib.parse.urlencode({
        "query.service_name": servico,
        "query.start_time_min": iso(agora - dt.timedelta(minutes=minutos)),
        "query.start_time_max": iso(agora),
        "query.num_traces": 50,
    })
    dados = get_json(f"{JAEGER}/api/v3/traces?{q}")
    saida = []
    for rs in dados.get("result", {}).get("resourceSpans", []):
        for ss in rs.get("scopeSpans", []):
            if ss.get("scope", {}).get("name") != "io.opentelemetry.jdbc":
                continue
            for sp in ss.get("spans", []):
                attrs = {a["key"]: next(iter(a["value"].values()), "") for a in sp.get("attributes", [])}
                saida.append((sp["name"], attrs))
    return saida


def prom(expr: str) -> list[dict]:
    q = urllib.parse.urlencode({"query": expr})
    return get_json(f"{PROM}/api/v1/query?{q}")["data"]["result"]


def main() -> None:
    minutos = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    print(f"Janela: últimos {minutos} min · Jaeger {JAEGER} · Prometheus {PROM}\n")

    por_servico = {s: spans_de_banco(s, minutos) for s in SERVICOS}

    print("1) Nomes dos spans de banco (JDBC)")
    for s, spans in por_servico.items():
        nomes = sorted({n for n, _ in spans if not n.startswith("CREATE")})
        print(f"  {s:15} {', '.join(nomes) or '(sem spans ainda)'}")

    print("\n2) Atributos presentes nos spans de banco (✔ presente · · ausente)")
    print(f"  {'atributo':24} {'convenção':9} " + " ".join(f"{s:>15}" for s in SERVICOS))
    for chave, conv in CHAVES:
        linha = []
        for s in SERVICOS:
            tem = any(chave in a for _, a in por_servico[s])
            linha.append(f"{'✔' if tem else '·':>15}")
        print(f"  {chave:24} {conv:9} " + " ".join(linha))

    print("\n3) Texto do SELECT de listagem (PreparedStatement com 'LIMIT 10' literal)")
    for s, spans in por_servico.items():
        for _, a in spans:
            txt = a.get("db.query.text") or a.get("db.statement")
            if txt and "ORDER BY" in txt:
                origem = "db.query.text" if "db.query.text" in a else "db.statement"
                print(f"  {s:15} {origem:14} {txt}")
                break

    print("\n4) Métrica db.client.operation.duration (segundos) por serviço")
    res = {r["metric"].get("job"): r for r in prom(
        'sum by (job) (rate(db_client_operation_duration_seconds_count[2m]))')}
    p95 = {r["metric"].get("job"): r for r in prom(
        'histogram_quantile(0.95, sum by (le, job) (rate(db_client_operation_duration_seconds_bucket[5m])))')}
    for s in SERVICOS:
        if s in res:
            print(f"  {s:15} {float(res[s]['value'][1]):6.2f} ops/s · p95 {float(p95[s]['value'][1]) * 1000:6.1f} ms")
        else:
            print(f"  {s:15} (não emitida)")


if __name__ == "__main__":
    main()
