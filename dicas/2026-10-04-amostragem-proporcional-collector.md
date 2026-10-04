# Dica: amostrou no Collector? Deixe o backend saber quanto

> Semana de 05/10/2026 · Testado com OpenTelemetry Collector Contrib 0.162.0 · Lab relacionado: [`2026-10-04-tempo-traceql-amostragem`](../2026-10-04-tempo-traceql-amostragem/)

## Contexto

Amostragem de cabeça no Collector (`probabilistic_sampler`) é o jeito mais simples de cortar custo de traces. O efeito colateral: qualquer métrica derivada dos traces armazenados (`rate()`, contagens) passa a mostrar só a fração amostrada.

O processor grava a probabilidade usada no próprio span, no `tracestate` W3C, na seção `ot` do OpenTelemetry — por exemplo `ot=th:c` para 25%. Backends que leem esse campo conseguem **reconstruir o volume real**. O Grafana Tempo 3.1 (29/09/2026) faz isso com `with(extrapolate=true)` em TraceQL metrics.

## Config

```yaml
processors:
  probabilistic_sampler:
    mode: proportional        # o padrão é hash_seed
    sampling_percentage: 25   # 1 em cada 4 traces

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, probabilistic_sampler, batch]
      exporters: [otlp_grpc/tempo]
```

## Como conferir

1. Exporter `debug` com `verbosity: detailed` → procure `TraceState : ot=th:c` nos spans.
2. Métrica interna `otelcol_processor_probabilistic_sampler_count_traces_sampled{sampled="true|false"}` → a proporção deve ficar perto do configurado.

Resultado do teste (25%, mesma carga nos dois modos):

| `mode` | `tracestate` gravado |
|---|---|
| `proportional` | `ot=th:c` |
| `hash_seed` (padrão) | `ot=rv:<valor derivado do hash>;th:c` |

## Por que `proportional`

- Usa os 56 bits de aleatoriedade do trace ID (W3C Trace Context nível 2), como manda a especificação de amostragem do OpenTelemetry — fica consistente com SDKs e outros Collectors que amostram no mesmo trace.
- `hash_seed` continua útil para **logs** (amostrar por atributo, ex.: `service.instance.id`), mas exige o mesmo `hash_seed` em todos os Collectors de um tier.

## Cuidados

- `th:c` é um **limiar** em hexadecimal, não um percentual: 25% de amostragem = rejeitar 75% (`c/16 = 0,75`).
- A amostragem é por item, sem estado: para decisões por trace inteiro (ex.: guardar todos os erros) use o `tail_sampling`.
- Razões (ex.: % de erro) não precisam de extrapolação quando todos os spans têm a mesma probabilidade, mas ficam ruidosas com pouco volume.
- O trace ID precisa ser aleatório (SDKs OpenTelemetry já geram assim).

## Fontes

- [probabilistic_sampler processor – README (contrib v0.162.0)](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/v0.162.0/processor/probabilisticsamplerprocessor)
- [OpenTelemetry – TraceState: Probability Sampling](https://opentelemetry.io/docs/specs/otel/trace/tracestate-probability-sampling/)
- [Tempo 3.1 – release notes](https://grafana.com/docs/tempo/latest/release-notes/v3-1/)
