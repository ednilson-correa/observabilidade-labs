#!/usr/bin/env bash
# Compara, nos últimos N segundos, o que o Tempo vê (amostrado), o que ele
# estima com with(extrapolate=true) e a "verdade" do span_metrics no Prometheus.
# Uso: ./scripts/compara.sh [janela_em_segundos]   (padrão: 120)
set -euo pipefail
TEMPO=${TEMPO_URL:-http://localhost:3200}
PROM=${PROM_URL:-http://localhost:9090}
JANELA=${1:-120}
FIM=$(( $(date +%s) - 15 ))      # margem para o flush do span_metrics
INICIO=$(( FIM - JANELA ))

tempo() {
  curl -s -G "$TEMPO/api/metrics/query" --data-urlencode "q=$1" \
    --data-urlencode "start=$INICIO" --data-urlencode "end=$FIM" |
  python3 -c 'import sys,json
d=json.load(sys.stdin)
for s in d.get("series",[]):
    lab=",".join(str(list(l["value"].values())[0]) for l in s["labels"] if l["key"]!="__name__") or "total"
    v=s.get("value",float("nan"))
    print("  %-10s %8.2f" % (lab, v))'
}
prom() {
  curl -s -G "$PROM/api/v1/query" --data-urlencode "query=$1" --data-urlencode "time=$FIM" |
  python3 -c 'import sys,json
for r in json.load(sys.stdin)["data"]["result"]:
    print("  %-10s %8.2f" % (r["metric"].get("service_name","total"), float(r["value"][1])))'
}

echo "Janela: ${JANELA}s"
echo; echo "Spans/s — Tempo cru:            {} | rate()";                      tempo '{} | rate()'
echo;  echo "Spans/s — Tempo extrapolado:    {} | rate() with(extrapolate=true)"; tempo '{} | rate() with(extrapolate=true)'
echo;  echo "Spans/s — verdade (span_metrics, 100%)";                           prom "sum(rate(traces_span_metrics_calls_total[${JANELA}s]))"
echo;  echo "% de erro — Tempo (aritmética TraceQL)"
tempo '100 * ({status=error} | rate() by (resource.service.name)) / ({} | rate() by (resource.service.name))'
echo;  echo "% de erro — verdade (span_metrics, 100%)"
prom "100 * sum by (service_name) (rate(traces_span_metrics_calls_total{status_code=\"STATUS_CODE_ERROR\"}[${JANELA}s])) / sum by (service_name) (rate(traces_span_metrics_calls_total[${JANELA}s]))"
