# Lab: métricas RC do hostmetrics/process — legado x transição x RC

> Semana de 12/10/2026 · OpenTelemetry Collector Contrib **0.163.1** · Prometheus **3.15.0** · Grafana **13.2.4**

## Objetivo

Em 13/10/2026 o blog do OpenTelemetry anunciou as primeiras métricas **Release Candidate (RC)** do receiver `hostmetrics`: o scraper `process` passa a ter, lado a lado, as métricas legadas e as versões alinhadas às convenções semânticas (marcadas `@v1` no `metadata.yaml`). A troca é controlada por dois feature gates:

| Gate | Efeito |
|---|---|
| `scraper.process.EmitV1SystemConventions` | passa a emitir as métricas/atributos RC |
| `scraper.process.DontEmitV0SystemConventions` | para de emitir as métricas/atributos legados |

Os dois estão em **alpha** (desligados por padrão). Quando o scraper virar stable, eles vão para **beta** (ligados por padrão) e o legado some. Este lab mostra **o que acontece com um dashboard antigo** em cada etapa, com o mesmo processo sendo coletado ao mesmo tempo por três coletores.

## Pré-requisitos

- Docker com Docker Compose v2 (testado para WSL2 + Docker Engine)
- Portas livres: `9090` (Prometheus) e `3000` (Grafana) — dá para mudar no `.env`
- Python 3 no host, só para o script de verificação (biblioteca padrão)

## Arquitetura

```
                      ┌──────────────────────┐
                      │ carga (python 3.13)  │  CPU, 6 threads, FDs abertos,
                      │ processo "carga"     │  escrita+fsync, page faults
                      └──────────┬───────────┘
          /proc do host (pid: host)│
     ┌───────────────────────────┼───────────────────────────┐
┌────▼──────────┐       ┌────────▼────────┐        ┌─────────▼───────┐
│ otelcol-legado│       │otelcol-transicao│        │   otelcol-rc    │
│  (sem gates)  │       │   EmitV1        │        │ EmitV1+DontEmitV0│
└────┬──────────┘       └────────┬────────┘        └─────────┬───────┘
     └──────── OTLP/HTTP ────────┼──────── job=hostmetrics-<modo> ┘
                        ┌────────▼────────┐      ┌───────────┐
                        │ Prometheus 3.15 │◄─────│ Grafana   │
                        │ OTLP nativo     │      │ 13.2.4    │
                        └─────────────────┘      └───────────┘
```

Arquivos:

| Arquivo | Para quê |
|---|---|
| `docker-compose.yml` | carga, três coletores, Prometheus e Grafana (versões fixas) |
| `otel-collector.yaml` | config única dos coletores (`host_metrics` → `resource` → `otlp_http`) |
| `prometheus/prometheus.yml` | receptor OTLP e promoção de `modo`, `process.executable.name`, `process.pid` |
| `carga/carga.py` | processo de carga (só biblioteca padrão) |
| `scripts/verificar.py` | roda as consultas de um dashboard legado nos três modos |
| `grafana/` | datasource e dashboard provisionados |

Três detalhes da config (e um do kernel):

- **Só os nomes legados estão em `metrics:`**. Com o gate `EmitV1SystemConventions`, o scraper emite a versão RC das métricas habilitadas sem você mudar a config (ex.: habilitar `process.threads` já traz `process.thread.count`).
- **`host_metrics` e `otlp_http`** são os nomes novos dos componentes. No 0.163.1 os nomes `hostmetrics` e `otlphttp` ainda funcionam, mas o log avisa: *alias is deprecated*.
- **I/O de disco depende do kernel.** `process.disk.io` é lido de `/proc/<pid>/io`, que só existe em kernels com contabilidade de I/O por processo (`CONFIG_TASK_IO_ACCOUNTING`). O kernel do WSL2 (testado: `6.18.54.1-microsoft-standard-WSL2`) **não tem**: `cat /proc/self/io` dá *No such file or directory*. Nesse caso a métrica não é emitida em nenhum modo, sem erro no log (`mute_process_io_error`), e o lab mostra 8 / 10 / 8 métricas em vez de 9 / 11 / 9. Num Linux comum (VM, bare metal, nuvem) ela aparece normalmente.

## Como subir

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
```

Espere uns 3 minutos para acumular dados (o `rate()` usa janela de 1 minuto).

## Como testar

1. Veja o aviso que o próprio Collector imprime nos modos transição e RC:

   ```bash
   docker compose logs otelcol-rc | grep "Legacy metric"
   ```

   Saída esperada (uma linha por métrica que manteve o nome e mudou atributo): `process.context_switches`, `process.cpu.time`, `process.cpu.utilization`, `process.disk.io` e `process.paging.faults`, com o texto `only latest will be emitted with combined attributes`.

2. Confira se o seu kernel expõe I/O por processo:

   ```bash
   cat /proc/self/io
   ```

   Se der *No such file or directory* (caso do WSL2), o painel "I/O de disco" fica vazio nos três modos e o resultado esperado muda (veja "Resultado no WSL2" abaixo).

3. Rode a verificação:

   ```bash
   python3 scripts/verificar.py
   ```

4. Abra o dashboard: <http://localhost:3000/d/lab-hostmetrics-process-rc>

## Resultado do teste

Executado em 19/10/2026 com os binários oficiais `otelcol-contrib 0.163.1` e `prometheus 3.15.0` (mesma config deste diretório):

```
modo        nomes process_*   séries
legado                    9       16
transicao                11       18
rc                        9       16

Consultas do dashboard LEGADO (state / direction / type / process_threads ...)
painel                    legado   transicao          rc
CPU por modo                  OK          OK  SILENCIOSO
Utilização de CPU             OK          OK  SILENCIOSO
Alerta de iowait              OK          OK   SEM DADOS
Threads                       OK          OK   SEM DADOS
File descriptors              OK          OK   SEM DADOS
I/O de disco                  OK          OK  SILENCIOSO
Trocas de contexto            OK          OK  SILENCIOSO
Page faults                   OK          OK  SILENCIOSO
Memória (RSS)                 OK          OK          OK

Resumo das consultas legadas:
  legado     OK=9  SEM DADOS=0  SILENCIOSO=0
  transicao  OK=9  SEM DADOS=0  SILENCIOSO=0
  rc         OK=1  SEM DADOS=3  SILENCIOSO=5
```

### Resultado no WSL2 (sem `/proc/<pid>/io`)

Executado em 20/10/2026 no WSL2 (Rocky 10, kernel `6.18.54.1-microsoft-standard-WSL2`) com `docker compose up`:

```
modo        nomes process_*   séries
legado                    8       14
transicao                10       16
rc                        8       14

Resumo das consultas legadas:
  legado     OK=8  SEM DADOS=1  SILENCIOSO=0
  transicao  OK=8  SEM DADOS=1  SILENCIOSO=0
  rc         OK=1  SEM DADOS=4  SILENCIOSO=4
```

A única diferença é o painel de I/O de disco, que fica sem dados em todos os modos. O resto bate com o resultado acima.

Como ler:

- **SEM DADOS**: a métrica mudou de nome (`process_threads` → `process_thread_count`, `process_open_file_descriptors` → `process_unix_file_descriptor_count`) ou o filtro usa um valor que mudou (`state="wait"` → `cpu_mode="iowait"`). O painel mostra "No data" e alguém percebe.
- **SILENCIOSO**: o nome da métrica é o mesmo, mas o atributo mudou (`state` → `cpu.mode`, `direction` → `disk.io.direction`, `type` → `process.context_switch.type` / `system.paging.fault.type`). O `sum by (state)` continua devolvendo número, só que uma série única com a soma de tudo. Ninguém percebe.
- **Transição**: as métricas que mantiveram o nome chegam com **os dois labels** (`state` e `cpu_mode` na mesma série) e as renomeadas chegam **duas vezes**. Custo medido: +2 nomes e +2 séries por processo (16 → 18). É a janela para migrar dashboards e alertas.

Mapa do que muda no Prometheus (tradução padrão `UnderscoreEscapingWithSuffixes`):

| Legado no Prometheus | RC no Prometheus |
|---|---|
| `process_cpu_time_seconds_total{state}` | `process_cpu_time_seconds_total{cpu_mode}` (`wait` → `iowait`) |
| `process_cpu_utilization_ratio{state}` | `process_cpu_utilization_ratio{cpu_mode}` |
| `process_disk_io_bytes_total{direction}` | `process_disk_io_bytes_total{disk_io_direction}` |
| `process_context_switches_total{type}` | `process_context_switches_total{process_context_switch_type}` |
| `process_paging_faults_total{type}` | `process_paging_faults_total{system_paging_fault_type}` |
| `process_threads` | `process_thread_count` |
| `process_open_file_descriptors` | `process_unix_file_descriptor_count` |
| `process_memory_usage_bytes`, `process_memory_virtual_bytes` | sem mudança |

Observação: as mudanças de unidade entre chaves (`{count}` → `{context_switch}`, `{faults}` → `{fault}`) não aparecem no nome do Prometheus, porque unidades entre chaves são descartadas na tradução.

## O que foi e o que NÃO foi validado

Validado no ambiente de preparo (sem Docker registry disponível):

- `docker compose config` e sintaxe de todos os YAML/JSON (Python);
- `otelcol-contrib validate` (0.163.1) para os três modos e `promtool check config` (3.15.0);
- fluxo completo com os **binários oficiais**: carga → 3 coletores → Prometheus OTLP; `scripts/verificar.py` com a saída acima;
- todas as consultas do dashboard rodadas no Prometheus, retornando dados.

Validado depois, no WSL2 (Rocky 10 + Docker Engine), em 19 e 20/10/2026:

- `docker compose up -d --build` com as imagens fixas, `pid: host` e o processo `carga` visível para os três coletores;
- dashboard renderizado no Grafana 13.2.4;
- `scripts/verificar.py` com o resultado da seção "Resultado no WSL2" (sem `process.disk.io`, porque o kernel do WSL2 não tem `/proc/<pid>/io`).

NÃO validado:

- `process.disk.io` via Docker num Linux com `/proc/<pid>/io` (aqui ele foi validado só com os binários rodando direto no host).

## Print do dashboard para as postagens

1. Suba o lab e espere ~15 minutos de carga.
2. Abra `http://localhost:3000/d/lab-hostmetrics-process-rc?orgId=1&from=now-15m&to=now&theme=dark&kiosk`.
3. No Windows, use a janela do navegador com ~1600×900 e tire o print (Win+Shift+S). Salve **fora** do repositório.
4. Os painéis que mais contam a história: a linha de stats do topo e "CPU por state · consulta legada" (a linha tracejada laranja do modo RC é a quebra silenciosa).

## Como derrubar

```bash
docker compose down -v
```

## Fontes

- [Versioned metrics: Shipping the first Release Candidate metrics in hostmetrics](https://opentelemetry.io/blog/2026/hostmetrics-process-scraper-rc/) — blog do OpenTelemetry, 13/10/2026
- [`metadata.yaml` e `documentation.md` do process scraper (v0.163.0)](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/v0.163.0/receiver/hostmetricsreceiver/internal/scraper/processscraper)
- [RFC de feature gates para semantic conventions](https://github.com/open-telemetry/opentelemetry-collector/blob/71f0462d5460ad3055201fd0f17658e56362d63a/docs/rfcs/semconv-feature-gates.md)
- [Releases do OpenTelemetry Collector (v0.163.1)](https://github.com/open-telemetry/opentelemetry-collector-releases/releases)
