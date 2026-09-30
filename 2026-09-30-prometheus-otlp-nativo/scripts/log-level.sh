#!/usr/bin/env sh
# Troca o nível de log do Prometheus 3.15+ SEM reiniciar o processo.
# Uso: ./scripts/log-level.sh debug|info|warn|error
set -eu

NIVEL="${1:-}"
case "$NIVEL" in
  debug|info|warn|error) ;;
  *) echo "uso: $0 debug|info|warn|error" >&2; exit 1 ;;
esac

DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONF="$DIR/prometheus/prometheus.yml"
PROM_URL="${PROM_URL:-http://localhost:${PROMETHEUS_PORT:-9090}}"

# Edita a chave runtime.log_level (sed portátil: GNU e BSD/macOS)
sed "s/^\([[:space:]]*log_level:\).*/\1 $NIVEL/" "$CONF" > "$CONF.tmp" && cat "$CONF.tmp" > "$CONF" && rm -f "$CONF.tmp"

# Reload via API (requer --web.enable-lifecycle)
curl -fsS -X POST "$PROM_URL/-/reload"

echo "runtime.log_level agora é: $NIVEL"
curl -fsS "$PROM_URL/api/v1/status/config" | grep -o 'log_level: [a-z]*' || true
