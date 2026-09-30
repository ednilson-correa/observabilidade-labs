# Lab: OTLP nativo no Prometheus 3.15 com OpenTelemetry Collector

> Data: 30/09/2026 · Versões: Prometheus v3.15.0 · OTel Collector Contrib 0.162.0 · telemetrygen v0.162.0 · Grafana 13.2.3

## Objetivo

Enviar métricas OpenTelemetry **direto para o receptor OTLP do Prometheus** (sem o exporter `prometheus` do Collector e sem remote write), e aprender a lidar com os três pontos que mais geram dúvida nessa integração:

1. **Atributos de recurso** (`service.name`, `deployment.environment.name`, `host.name`…) — quais viram labels e quais ficam no `target_info`.
2. **Temporalidade delta x cumulativa** — o Prometheus armazena contadores/histogramas cumulativos; o Collector converte com o processor `delta_to_cumulative`.
3. **Enriquecimento com `info()`** — trazer metadados do `target_info` para a consulta sem o famoso `* on (job, instance) group_left(...)`.

Bônus (novidade do Prometheus 3.15): trocar o **nível de log do Prometheus sem restart** usando `runtime.log_level` + reload.

## Pré-requisitos

- Docker Engine 24+ com o plugin Docker Compose v2
- Portas livres: `9090` (Prometheus), `3000` (Grafana), `4317`/`4318` (OTLP) — ajustáveis no `.env`
- `curl` (para os testes)

## Arquitetura

```
┌─────────────┐  OTLP/gRPC   ┌──────────────────────┐  OTLP/HTTP                    ┌──────────────┐     ┌─────────┐
│ checkout    │─────────────▶│ OTel Collector       │──────────────────────────────▶│ Prometheus   │◀────│ Grafana │
│ (histograma │              │ memory_limiter       │  /api/v1/otlp/v1/metrics      │ 3.15         │     │ 13.2    │
│  delta)     │              │ delta_to_cumulative  │                               │ --web.enable-│     └─────────┘
├─────────────┤              │ batch                │◀── scrape :8888 (métricas ────│ otlp-receiver│
│ pagamentos  │─────────────▶│                      │     internas do Collector)    └──────────────┘
│ (contador)  │              └──────────────────────┘
└─────────────┘
 telemetrygen (simula apps instrumentadas com OTel SDK)
```

| Serviço | Imagem | Função |
|---|---|---|
| `checkout` | `ghcr.io/open-telemetry/opentelemetry-collector-contrib/telemetrygen:v0.162.0` | Gera o histograma `loja.checkout.latencia` com temporalidade **delta** |
| `pagamentos` | idem | Gera o contador `loja.pagamentos.processados` (cumulativo) |
| `otel-collector` | `otel/opentelemetry-collector-contrib:0.162.0` | Recebe OTLP, converte delta → cumulativo e exporta via `otlp_http` |
| `prometheus` | `prom/prometheus:v3.15.0` | Receptor OTLP habilitado, `info()` habilitado |
| `grafana` | `grafana/grafana:13.2.3` | Datasource e dashboard provisionados |

Arquivos:

```
.
├── docker-compose.yml
├── otel-collector.yaml
├── prometheus/prometheus.yml        # bloco otlp:, runtime.log_level e OOO window
├── grafana/provisioning/...         # datasource + provider de dashboards
├── grafana/dashboards/lab-prometheus-otlp.json
├── scripts/log-level.sh             # dica: troca o log level sem restart
└── .env.example
```

## Como subir

```bash
cd 2026-09-30-prometheus-otlp-nativo
cp .env.example .env        # opcional: ajuste portas/senha
docker compose up -d
docker compose ps
```

Aguarde ~30 segundos para as primeiras amostras chegarem.

## Como testar

**1. O pipeline está entregando?** (métricas internas do Collector)

```bash
curl -s 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query=sum by (exporter) (rate(otelcol_exporter_sent_metric_points[1m]))'
```

Deve aparecer `otlp_http/prometheus` com valor > 0.

**2. Como o nome OTel virou nome Prometheus?**

| OTel | Prometheus (`UnderscoreEscapingWithSuffixes`) |
|---|---|
| `loja.pagamentos.processados` (Sum monotônico) | `loja_pagamentos_processados_total` |
| `loja.checkout.latencia` (Histogram) | `loja_checkout_latencia_bucket` / `_sum` / `_count` |
| `service.namespace` + `service.name` | label `job="loja/pagamentos"` |
| `service.instance.id` | label `instance` (vazio neste lab, pois o telemetrygen não envia) |

No Prometheus (http://localhost:9090), rode:

```promql
loja_pagamentos_processados_total
```

Repare que `service_namespace` e `deployment_environment_name` viraram labels (estão em `otlp.promote_resource_attributes`), mas `host_name` e `service_version` **não** — eles ficam só no `target_info`:

```promql
target_info{service_namespace="loja"}
```

**3. Enriquecendo com `info()`** (função experimental, habilitada com `--enable-feature=promql-experimental-functions`):

```promql
sum by (job, host_name, service_version) (
  info(rate(loja_pagamentos_processados_total[1m]), {host_name=~".+", service_version=~".+"})
)
```

Compare com a forma tradicional:

```promql
sum by (job, host_name, service_version) (
    rate(loja_pagamentos_processados_total[1m])
  * on (job, instance) group_left (host_name, service_version)
    target_info
)
```

**4. Histograma delta convertido:**

```promql
histogram_quantile(0.95, sum by (le, job) (rate(loja_checkout_latencia_bucket[1m])))
```

Sem o processor `delta_to_cumulative` no Collector, essas séries não chegariam utilizáveis como cumulativas. (Alternativa: o flag experimental `--enable-feature=otlp-deltatocumulative` do próprio Prometheus.)

**5. Grafana:** http://localhost:3000 → pasta **Labs** → dashboard **Lab – Prometheus 3.15 + OTLP nativo** (acesso anônimo como Viewer; admin conforme `.env`).

**6. Dica bônus – log level sem restart (Prometheus 3.15+):**

```bash
./scripts/log-level.sh debug    # edita runtime.log_level e faz POST /-/reload
docker compose logs -f prometheus | grep 'level=DEBUG'
./scripts/log-level.sh info     # volta ao normal
```

Se você escrever um valor inválido (ex.: `verbose`), o reload falha, a configuração anterior continua valendo e a métrica `prometheus_config_last_reload_successful` vai a `0` — vale ter alerta nela. Valide antes com:

```bash
docker compose exec prometheus promtool check config /etc/prometheus/prometheus.yml
```

## Como derrubar

```bash
docker compose down -v
```

## Observações importantes

- A própria documentação do Prometheus diz que o receptor OTLP **não é a forma mais eficiente de ingestão** e recomenda cautela para casos de baixo volume; ele não substitui o scrape. Para volume alto, avalie remote write ou uma solução de longo prazo (Mimir, Thanos, VictoriaMetrics etc.).
- `out_of_order_time_window: 30m` evita rejeição de amostras que chegam fora de ordem por batching/retries.
- Promova atributos de recurso com parcimônia: cada label nova multiplica a cardinalidade.
- `info()` é **experimental**: a sintaxe pode mudar em versões futuras.

## Fontes

- [Prometheus v3.15.0 – release notes (24/09/2026)](https://github.com/prometheus/prometheus/releases/tag/v3.15.0)
- [Prometheus – configuração (`otlp`, `runtime`, `storage.tsdb`)](https://prometheus.io/docs/prometheus/latest/configuration/configuration/)
- [Prometheus – OTLP Receiver (HTTP API)](https://prometheus.io/docs/prometheus/latest/querying/api/#otlp-receiver)
- [Prometheus – função `info()`](https://prometheus.io/docs/prometheus/latest/querying/functions/#info)
- [Prometheus – Management API (`/-/reload`)](https://prometheus.io/docs/prometheus/latest/management_api/)
- [OpenTelemetry – Prometheus and OpenTelemetry interoperability in 2026: Survey results](https://opentelemetry.io/blog/2026/otel-prometheus-interoperability/)
- [telemetrygen (opentelemetry-collector-contrib)](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/cmd/telemetrygen)
- [deltatocumulative processor](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/deltatocumulativeprocessor)
