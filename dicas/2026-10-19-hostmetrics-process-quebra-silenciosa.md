# Dica: antes de ligar as métricas RC do hostmetrics/process, procure seus `by (state)`

> Semana de 19/10/2026 · Testado com OpenTelemetry Collector Contrib 0.163.1 + Prometheus 3.15.0 · Lab relacionado: [`2026-10-19-hostmetrics-process-rc`](../2026-10-19-hostmetrics-process-rc/)

## Contexto

O scraper `process` do receiver `hostmetrics` ganhou métricas **Release Candidate** controladas por dois feature gates (alpha, desligados por padrão): `scraper.process.EmitV1SystemConventions` e `scraper.process.DontEmitV0SystemConventions`. Quando o scraper virar stable, os dois vão ligar por padrão e o legado sai.

O risco não está nas métricas renomeadas (`process_threads` → `process_thread_count`): essas viram "No data" e alguém percebe. O risco está nas que **mantêm o nome e trocam o atributo**: `sum by (state)` continua devolvendo número, só que uma série única somando user + system + iowait.

## O teste

Nove consultas de um dashboard legado, o mesmo processo, três coletores:

| Modo | OK | Sem dados | Silencioso |
|---|---|---|---|
| sem gates | 9 | 0 | 0 |
| `EmitV1` (transição) | 9 | 0 | 0 |
| `EmitV1` + `DontEmitV0` (RC) | 1 | 3 | 5 |

## O que fazer

1. Ligue primeiro **só** o `EmitV1SystemConventions`. As métricas que mantêm o nome chegam com os dois labels (`state` **e** `cpu_mode`) e as renomeadas chegam duplicadas — custo medido: +2 séries por processo.

   ```bash
   otelcol-contrib --config=config.yaml \
     --feature-gates=scraper.process.EmitV1SystemConventions
   ```

2. Migre consultas e alertas nessa janela:

   ```promql
   # antes
   sum by (state) (rate(process_cpu_time_seconds_total[5m]))
   # depois (repare: "wait" virou "iowait")
   sum by (cpu_mode) (rate(process_cpu_time_seconds_total[5m]))
   ```

3. Só então ligue `DontEmitV0SystemConventions` (ou seja, deixe a versão do Collector fazer isso por você quando os gates virarem beta).

Busca rápida nos dashboards exportados (JSON):

```bash
grep -rlE 'by \((state|direction|type)\)|process_threads|process_open_file_descriptors' dashboards/
```

## Cuidados

- Unidades entre chaves (`{count}` → `{context_switch}`) mudam no OTLP, mas não aparecem no nome do Prometheus.
- No 0.163, `hostmetrics` e `otlphttp` já são aliases deprecated de `host_metrics` e `otlp_http`.
- `process.disk.io` depende de `/proc/<pid>/io`, que não existe no kernel do WSL2 (`cat /proc/self/io` falha). Lá a métrica simplesmente não aparece, sem erro no log.

## Fonte

- [Versioned metrics: Shipping the first Release Candidate metrics in hostmetrics](https://opentelemetry.io/blog/2026/hostmetrics-process-scraper-rc/) (13/10/2026)
