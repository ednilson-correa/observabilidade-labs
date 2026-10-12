# Lab: Java agent 3.0 preview — o que muda na telemetria de banco (legado x `/dup` x 3.0)

> Data: 12/10/2026 · Versões: OpenTelemetry Java agent 2.32.0 (release candidate do 3.0) · OTel Collector Contrib 0.162.0 · Jaeger 2.22.0 · Prometheus v3.15.0 · Grafana 13.2.3 · PostgreSQL 18.6 · driver JDBC pgjdbc 42.7.14 · Eclipse Temurin 21.0.12 · Python 3.13.7 (gerador de carga)

## Objetivo

Em 06/10/2026 o projeto OpenTelemetry anunciou que o **Java agent 2.32.0 é o release candidate do 3.0** (previsto para outubro de 2026). O 3.0 troca padrões de telemetria: convenções de **banco** e **code** viram estáveis por padrão, **messaging** adota convenções mais novas e alguns padrões de captura mudam.

Dashboards, alertas e pipelines que dependem de nomes de span e atributos antigos podem **quebrar em silêncio**. Este lab sobe **a mesma API**, com **o mesmo agent** e **a mesma carga**, em três modos lado a lado:

| Instância | Configuração do agent | O que representa |
|---|---|---|
| `pedidos-legado` | padrão | Como você roda hoje no 2.x |
| `pedidos-dup` | `OTEL_INSTRUMENTATION_COMMON_V3_PREVIEW=false` + `OTEL_SEMCONV_STABILITY_OPT_IN=database/dup,code/dup` | Passo 1 do blog: atributos antigos **e** novos juntos, para migrar dashboards sem apagão |
| `pedidos-v3` | `OTEL_INSTRUMENTATION_COMMON_V3_PREVIEW=true` | Passo 2 do blog: comportamento combinado previsto para o 3.0 |

## Pré-requisitos

- Docker Engine 24+ com o plugin Docker Compose v2 (o build da API baixa o agent e o driver JDBC do GitHub)
- Portas livres: `3000` (Grafana), `9090` (Prometheus), `16686` (Jaeger), `8081–8083` (as 3 instâncias) — ajustáveis no `.env`
- `python3` no host (para `scripts/compara.py`, só biblioteca padrão)

## Arquitetura

```
             ┌────────────────────────── mesma imagem, mesmo agent 2.32.0 ──────────────────────────┐
┌─────────┐  │  pedidos-legado (padrão)   pedidos-dup (database/dup)   pedidos-v3 (v3_preview=true)  │
│ loadgen │─▶│        │ JDBC                    │ JDBC                       │ JDBC                  │──▶ PostgreSQL 18.6
│ 10 rps  │  └────────┼─────────────────────────┼────────────────────────────┼───────────────────────┘
│ /alvo   │           └──────────── OTLP/HTTP ──┴────────────────────────────┘
└─────────┘                                     ▼
                       ┌────────────────────────────────────────────┐
                       │ OTel Collector 0.162                        │
                       │  traces ──▶ Jaeger 2.22 (UI :16686)          │
                       │  traces ──▶ span_metrics (dimensões de banco│
                       │             antigas E novas; ausente = "-") │
                       │  métricas + span_metrics ──▶ Prometheus 3.15│──▶ Grafana 13.2
                       └────────────────────────────────────────────┘
```

| Serviço | Imagem | Função |
|---|---|---|
| `app-legado`, `app-dup`, `app-v3` | build de `app/` (`eclipse-temurin:21.0.12_8-jdk`) | API de pedidos só com JDK + JDBC; nenhuma linha de OpenTelemetry no código |
| `postgres` | `postgres:18.6` | Banco `pedidos` (tabela criada pela API ao subir) |
| `loadgen` | `python:3.13.7-slim` | 10 req/s por instância: 60% `GET /pedidos`, 30% `POST /pedidos`, 10% `GET /pedidos/lento` |
| `otel-collector` | `otel/opentelemetry-collector-contrib:0.162.0` | Encaminha traces ao Jaeger, gera `span_metrics` e manda métricas ao Prometheus |
| `jaeger` | `jaegertracing/jaeger:2.22.0` | Para inspecionar spans e atributos |
| `prometheus` | `prom/prometheus:v3.15.0` | Receptor OTLP nativo (`--web.enable-otlp-receiver`) |
| `grafana` | `grafana/grafana:13.2.3` | Dashboard provisionado (pasta **Labs**) |

Arquivos:

```
.
├── docker-compose.yml
├── app/App.java                      # API (JDK HttpServer + JDBC)
├── app/Dockerfile                    # baixa o agent 2.32.0 e o pgjdbc 42.7.14
├── loadgen/loadgen.py                # mesma carga para as 3 instâncias
├── otel-collector.yaml               # span_metrics com dimensões antigas e novas
├── prometheus/prometheus.yml
├── grafana/provisioning/...          # datasource Prometheus + provider
├── grafana/dashboards/lab-otel-java-agent-3-preview.json
├── scripts/compara.py                # tabela legado x dup x 3.0 (Jaeger + Prometheus)
├── extras/otel-collector-redige-sql.yaml  # dica: redigir literais de db.query.text (OTTL)
└── .env.example
```

## Como subir

```bash
cd 2026-10-12-otel-java-agent-3-preview
cp .env.example .env        # ajuste portas/senhas se precisar
docker compose up -d --build
docker compose ps
```

Aguarde **2–3 minutos** para acumular dados (o `span_metrics` publica a cada 15 s e o agent exporta métricas a cada 15 s).

## Como testar

**1. A API responde nas três instâncias?**

```bash
for p in 8081 8082 8083; do curl -s -X POST localhost:$p/pedidos; curl -s localhost:$p/pedidos | head -2; done
```

**2. Compare a telemetria dos três modos:**

```bash
python3 scripts/compara.py 5     # janela de 5 minutos
```

Resultado do teste feito na criação do lab:

```
1) Nomes dos spans de banco (JDBC)
  pedidos-legado  INSERT pedidos.pedidos, SELECT pedidos, SELECT pedidos.pedidos
  pedidos-dup     INSERT pedidos, SELECT, SELECT pedidos
  pedidos-v3      INSERT pedidos, SELECT, SELECT pedidos

2) Atributos presentes nos spans de banco (✔ presente · · ausente)
  atributo                 convenção  pedidos-legado     pedidos-dup      pedidos-v3
  db.system                legado                  ✔               ✔               ·
  db.name                  legado                  ✔               ✔               ·
  db.operation             legado                  ✔               ✔               ·
  db.statement             legado                  ✔               ✔               ·
  db.user                  legado                  ✔               ✔               ·
  db.connection_string     legado                  ✔               ✔               ·
  db.system.name           novo                    ·               ✔               ✔
  db.namespace             novo                    ·               ✔               ✔
  db.query.summary         novo                    ·               ✔               ✔
  db.query.text            novo                    ·               ✔               ✔
  server.address           ambos                   ✔               ✔               ✔
  server.port              ambos                   ✔               ·               ·

3) Texto do SELECT de listagem (PreparedStatement com 'LIMIT 10' literal)
  pedidos-legado  db.statement   SELECT id, cliente, valor FROM pedidos ORDER BY id DESC LIMIT ?
  pedidos-dup     db.query.text  SELECT id, cliente, valor FROM pedidos ORDER BY id DESC LIMIT 10
  pedidos-v3      db.query.text  SELECT id, cliente, valor FROM pedidos ORDER BY id DESC LIMIT 10

4) Métrica db.client.operation.duration (segundos) por serviço
  pedidos-legado  (não emitida)
  pedidos-dup      10.00 ops/s · p95   72.7 ms
  pedidos-v3        9.99 ops/s · p95   74.0 ms
```

**3. Veja no Jaeger:** http://localhost:16686 → serviço `pedidos-legado` e depois `pedidos-v3` → abra um trace de `GET /pedidos` e compare as tags do span JDBC.

**4. Dashboard:** http://localhost:3000 → pasta **Labs** → **Lab – Java agent 3.0 preview: convenções de banco (legado x dup x 3.0)**.

**5. Teste o "alerta que quebra em silêncio":** no Prometheus (http://localhost:9090), rode

```promql
sum by (service_name) (rate(traces_span_metrics_calls_total{span_name="SELECT pedidos.pedidos"}[5m]))
```

Só `pedidos-legado` aparece. Um alerta escrito assim simplesmente **para de ver dados** depois do upgrade — não dispara, não avisa.

## O que observar (e os cuidados)

- **O nome do span muda, mesmo com `/dup`.** `/dup` duplica *atributos* (e métricas, onde há suporte), mas um span só tem um nome: ele já vem no formato novo (`SELECT pedidos` em vez de `SELECT pedidos.pedidos`; o `SELECT pg_sleep(?)` vira só `SELECT`). Alertas e painéis filtrados por nome de span precisam migrar antes.
- **`db.query.text` de `PreparedStatement` não é sanitizado.** No modo legado, `db.statement` trocava literais por `?` (`LIMIT ?`). Nas convenções estáveis, texto de consulta **parametrizada não deve ser sanitizado** (a especificação parte do princípio de que dado sensível vai nos parâmetros) — o `LIMIT 10` aparece literal. Num teste extra com `WHERE cliente = 'cliente-42' AND valor > ?` em `PreparedStatement`, o literal `'cliente-42'` também apareceu no 3.0 preview; o mesmo SQL via `Statement` simples continuou sanitizado. **Revise SQL com literais sensíveis** antes de ligar o 3.0 — e, se precisar de uma rede de proteção, use o `transform` de `extras/otel-collector-redige-sql.yaml` no Collector (testado: `'PREP-42'` virou `?`).
- **Você ganha uma métrica de banco.** No 2.x padrão o JDBC não emitiu métrica de duração; com `database/dup` ou o preview, aparece `db.client.operation.duration` (histograma em **segundos**, com `db.system.name`, `db.namespace`, `db.query.summary`, `server.address`).
- **`db.namespace` combina banco e schema**: `pedidos|public` (o `db.name` antigo era só `pedidos`). Compare **valores**, não só chaves.
- **`server.port` some quando é a porta padrão** (5432), como manda a convenção de PostgreSQL. `db.user` e `db.connection_string` deixam de existir.
- Segundo o blog do projeto, as métricas de **pool de conexões** já trocam de nome e unidade (ms → s) mesmo com `database/dup`; messaging muda nome de span, tipo de span e relação pai/filho; o exporter **Zipkin** é removido no modo preview. Este lab não usa pool nem mensageria — teste os seus.
- O Jaeger 2.21+ removeu os endpoints HTTP v1 da query (jaeger#9260). Por isso o `scripts/compara.py` usa a **API v3** (`/api/v3/traces`) e o Grafana deste lab usa só o Prometheus.

## Como derrubar

```bash
docker compose down -v
```

## Print do dashboard para as postagens

1. Suba o lab e espere ~10 minutos de carga.
2. Abra `http://localhost:3000/d/lab-otel-java-agent-3-preview?orgId=1&from=now-15m&to=now&theme=dark&kiosk`.
3. Para um PNG nítido com Playwright (no host):

```bash
pip install playwright && python -m playwright install chromium
python - <<'EOF'
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=2)
    pg.goto("http://localhost:3000/d/lab-otel-java-agent-3-preview?orgId=1&from=now-15m&to=now&theme=dark&kiosk")
    pg.wait_for_timeout(8000)
    pg.screenshot(path="dashboard-java-agent-3.png", full_page=True)
    b.close()
EOF
```

## Fontes

- [The OpenTelemetry Java agent 3.0 is almost here — preview it today (06/10/2026)](https://opentelemetry.io/blog/2026/java-agent-3.0-preview/)
- [opentelemetry-java-instrumentation v2.32.0 – release](https://github.com/open-telemetry/opentelemetry-java-instrumentation/releases/tag/v2.32.0)
- [Convenções semânticas – spans de banco (sanitização de `db.query.text`)](https://opentelemetry.io/docs/specs/semconv/db/database-spans/)
- [Convenções semânticas – PostgreSQL (`server.port`)](https://opentelemetry.io/docs/specs/semconv/db/postgresql/)
- [Guia de migração das convenções de banco](https://opentelemetry.io/docs/specs/semconv/non-normative/db-migration/)
- [Instrumentação JDBC – opções](https://github.com/open-telemetry/opentelemetry-java-instrumentation/tree/v2.32.0/instrumentation/jdbc)
- [span_metrics connector (contrib v0.162.0)](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/v0.162.0/connector/spanmetricsconnector)
- [Jaeger v2.22.0 – CHANGELOG](https://github.com/jaegertracing/jaeger/blob/v2.22.0/CHANGELOG.md)
