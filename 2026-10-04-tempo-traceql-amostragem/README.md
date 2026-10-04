# Lab: Tempo 3.1 — TraceQL metrics com amostragem (aritmética + `with(extrapolate=true)`)

> Data: 04/10/2026 · Versões: Grafana Tempo 3.1.0 · OTel Collector Contrib 0.162.0 · Prometheus v3.15.0 · Grafana 13.2.3 · Python 3.13.7 (gerador de carga)

## Objetivo

Você amostra traces para economizar (ótimo), mas aí qualquer `rate()` calculado a partir deles mostra **só a fração amostrada**. Com 25% de amostragem, o "tráfego" que aparece é 1/4 do real.

O Grafana Tempo 3.1 (lançado em 29/09/2026) trouxe duas novidades em TraceQL metrics que resolvem isso:

1. **`with(extrapolate=true)`** (experimental) — cada span conta como `1 / probabilidade_de_amostragem`, lida do `tracestate` W3C (`ot=th:...`) gravado pelo amostrador OpenTelemetry. O `rate()` volta a refletir o tráfego real.
2. **Aritmética** (`+ - * /`) entre consultas — taxa de erro em **uma** query TraceQL, sem Math expression no Grafana.

Neste lab você compara três números lado a lado:

| O quê | De onde vem |
|---|---|
| Spans/s **reais** (100%) | conector `span_metrics` no Collector → Prometheus |
| Spans/s **armazenados** (25%) | Tempo: `{} \| rate()` |
| Spans/s **estimados** | Tempo 3.1: `{} \| rate() with(extrapolate=true)` |

## Pré-requisitos

- Docker Engine 24+ com o plugin Docker Compose v2
- Portas livres: `3000` (Grafana), `3200` (Tempo), `9090` (Prometheus), `4318` (OTLP/HTTP) — ajustáveis no `.env`
- `curl` e `python3` no host (para `scripts/compara.sh`)

## Arquitetura

```
┌──────────┐ OTLP/HTTP ┌─────────────────────────────────────────────┐
│ loadgen  │──────────▶│ OTel Collector 0.162                         │
│ frontend │           │                                              │
│  └ checkout          │  traces/total ──▶ span_metrics ──▶ metrics ──┼──▶ Prometheus 3.15 (OTLP)
│ 20 tr/s, │           │     (100% dos spans = "verdade")             │       ▲
│ 5% erro  │           │                                              │       │
└──────────┘           │  traces/amostrado ──▶ probabilistic_sampler ─┼──▶ Tempo 3.1 ◀── Grafana 13.2
                       │     (mode: proportional, 25%)                │   (spans com
                       │     grava tracestate ot=th:c                 │    ot=th:c)
                       └─────────────────────────────────────────────┘
```

| Serviço | Imagem | Função |
|---|---|---|
| `loadgen` | `python:3.13.7-slim` | Script só com biblioteca padrão (`loadgen/loadgen.py`): 20 traces/s (40 spans/s), 5% com erro |
| `otel-collector` | `otel/opentelemetry-collector-contrib:0.162.0` | `span_metrics` (100%) + `probabilistic_sampler` proporcional (25%) |
| `tempo` | `grafana/tempo:3.1.0` | Modo monolítico (`-target=all`), storage local, sem Kafka |
| `prometheus` | `prom/prometheus:v3.15.0` | Recebe o `span_metrics` via OTLP; raspa Collector e Tempo |
| `grafana` | `grafana/grafana:13.2.3` | Datasources Tempo + Prometheus e dashboard provisionados |

Arquivos:

```
.
├── docker-compose.yml
├── otel-collector.yaml              # span_metrics + probabilistic_sampler (proportional)
├── tempo.yaml                       # Tempo 3.1 monolítico
├── prometheus/prometheus.yml
├── loadgen/loadgen.py               # gerador OTLP/JSON (stdlib)
├── grafana/provisioning/...         # datasources + provider de dashboards
├── grafana/dashboards/lab-tempo-traceql-amostragem.json
├── scripts/compara.sh               # Tempo cru x extrapolado x verdade
└── .env.example
```

## Como subir

```bash
cd 2026-10-04-tempo-traceql-amostragem
cp .env.example .env        # opcional: ajuste portas, % de amostragem e carga
docker compose up -d
docker compose ps
```

Aguarde **2–3 minutos** para acumular dados (o `span_metrics` publica a cada 15 s).

## Como testar

**1. A amostragem está acontecendo?**

```bash
curl -s 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query=sum by (sampled) (rate(otelcol_processor_probabilistic_sampler_count_traces_sampled[1m]))'
```

`sampled="true"` deve ficar perto de 25% do total.

**2. O span chegou ao Tempo com o limiar de amostragem?**

```bash
TID=$(curl -s -G http://localhost:3200/api/search --data-urlencode 'q={}' --data-urlencode limit=1 \
      | python3 -c 'import sys,json; print(json.load(sys.stdin)["traces"][0]["traceID"])')
curl -s http://localhost:3200/api/v2/traces/$TID | grep -o '"traceState":"[^"]*"' | head -2
```

Saída esperada: `"traceState":"ot=th:c"` — `th:c` é o limiar de 25% na especificação de amostragem do OpenTelemetry.

**3. Compare os números:**

```bash
./scripts/compara.sh 300     # janela de 5 minutos
```

Resultado do teste feito na criação do lab (25% de amostragem, 40 spans/s reais):

```
Spans/s — Tempo cru:            {} | rate()
  total          9.16
Spans/s — Tempo extrapolado:    {} | rate() with(extrapolate=true)
  total         36.63
Spans/s — verdade (span_metrics, 100%)
  total         36.70
```

(A janela incluía o aquecimento do lab, por isso a "verdade" ficou abaixo de 40.)

**4. Taxa de erro em uma query só (aritmética TraceQL):**

No Grafana → **Explore** → datasource **Tempo** → aba **TraceQL**:

```traceql
100 * ({status=error} | rate() by (resource.service.name))
    / ({} | rate() by (resource.service.name))
```

Regras da sintaxe (documentação do Tempo 3.1):

- cada subconsulta vai **entre parênteses** — `{status=error} | rate() / {} | rate()` dá erro de parse;
- escalares podem ficar dos dois lados (`100 * (...)`, `(...) * 60`), mas **durações** (`10s`) não;
- com o mesmo `by()` dos dois lados, as séries casam pelo label; se só um lado tiver `by()`, o outro é aplicado a todas as séries;
- `topk`, `bottomk` e comparações (`> 5`) podem vir depois da expressão; `compare()` não entra em aritmética.

**5. Dashboard:** http://localhost:3000 → pasta **Labs** → **Lab – Tempo 3.1: TraceQL metrics com amostragem**.

**6. Experimente:** mude `SAMPLING_PERCENTAGE` no `.env` para `10` e rode `docker compose up -d otel-collector`. O `rate()` cru cai para ~1/10 e o extrapolado continua acompanhando a verdade.

## O que observar (e os cuidados)

- **Razões não precisam de extrapolação**, desde que todos os spans tenham sido amostrados com a mesma probabilidade: o fator se cancela no numerador e no denominador. Mas com amostra pequena a razão fica **ruidosa** — no teste, a taxa de erro "real" foi 4,72% e a vista no Tempo, 3,60% (5 minutos, ~2,7 mil spans armazenados). Eventos raros pedem janelas maiores.
- Se a sua política amostra erros com probabilidade diferente do resto (ex.: "guardar mais erros"), a razão crua fica **distorcida**. A extrapolação só corrige se cada span carregar o próprio limiar (`ot=th`), porque ela soma `1/p` span a span.
- `with(extrapolate=true)` é **experimental** no Tempo 3.1 e exige blocos **vParquet4 ou mais novos** (o 3.1 já grava vParquet5 por padrão). Vale para `rate`, `count_over_time`, `sum_over_time`, `avg_over_time`, `histogram_over_time`, `quantile_over_time` e `compare`; `min_over_time`/`max_over_time` não mudam.
- No `probabilistic_sampler`, o **padrão é `mode: hash_seed`**. Use `proportional` para seguir a especificação de amostragem consistente do OpenTelemetry (aleatoriedade do trace ID), o que importa quando há amostragem em mais de um ponto (SDK, vários Collectors).
- Isto **não substitui** métricas de verdade para alertas críticos: o `span_metrics`/métricas da aplicação continuam sendo a fonte mais barata e precisa para SLOs. A extrapolação é ótima para análise ad hoc e para recortes que você não pré-agregou.

## Como derrubar

```bash
docker compose down -v
```

## Fontes

- [Grafana Tempo v3.1.0 – release (29/09/2026)](https://github.com/grafana/tempo/releases/tag/v3.1.0)
- [Tempo 3.1 – release notes](https://grafana.com/docs/tempo/latest/release-notes/v3-1/)
- [TraceQL metrics functions – aritmética e `with(extrapolate=true)`](https://grafana.com/docs/tempo/latest/metrics-from-traces/metrics-queries/functions/)
- [Tempo – deploy local em modo monolítico](https://grafana.com/docs/tempo/latest/set-up-for-tracing/setup-tempo/deploy/locally/linux/)
- [probabilistic_sampler processor (contrib v0.162.0)](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/v0.162.0/processor/probabilisticsamplerprocessor)
- [span_metrics connector (contrib v0.162.0)](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/v0.162.0/connector/spanmetricsconnector)
- [OpenTelemetry – TraceState: Probability Sampling](https://opentelemetry.io/docs/specs/otel/trace/tracestate-probability-sampling/)
