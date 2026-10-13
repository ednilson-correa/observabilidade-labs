# Dica: no Java agent 3.0, o SQL de PreparedStatement chega sem sanitização

> Semana de 12/10/2026 · Testado com OpenTelemetry Java agent 2.32.0 (RC do 3.0) + OTel Collector Contrib 0.162.0 + PostgreSQL · Lab relacionado: [`2026-10-12-otel-java-agent-3-preview`](../2026-10-12-otel-java-agent-3-preview/)

## Contexto

O Java agent 2.32.0 é o release candidate do 3.0, que torna padrão as convenções semânticas **estáveis** de banco. Uma mudança que passa despercebida: o atributo `db.statement` (legado) dá lugar a `db.query.text`, e a regra de sanitização muda.

Pela especificação, texto de consulta **parametrizada não deve ser sanitizado** — a premissa é que dado sensível vai nos parâmetros (`?`), não no SQL. Na prática, qualquer literal escrito direto no `PreparedStatement` passa a aparecer no trace.

## O teste

Mesmo código, mesmo agent, dois modos:

```java
c.prepareStatement("SELECT count(*) FROM pedidos WHERE cliente = 'PREP-42' AND valor > ?");
c.createStatement().executeQuery("SELECT count(*) FROM pedidos WHERE cliente = 'STMT-42' AND valor > 10");
```

| Modo | `PreparedStatement` | `Statement` |
|---|---|---|
| 2.x padrão (`db.statement`) | `... cliente = ? AND valor > ?` | `... cliente = ? AND valor > ?` |
| Preview 3.0 (`db.query.text`) | `... cliente = 'PREP-42' AND valor > ?` | `... cliente = ? AND valor > ?` |

O mesmo vale para `LIMIT 10`: no legado vira `LIMIT ?`, no 3.0 fica `LIMIT 10`.

## O que fazer

1. **Na origem (o certo):** passe valores como parâmetro (`?`), inclusive constantes que identificam pessoas, tenants ou status sensíveis.
2. **Rede de proteção no Collector** (testado — `'PREP-42'` virou `?`):

```yaml
processors:
  transform/redige-sql:
    error_mode: ignore
    trace_statements:
      - replace_pattern(span.attributes["db.query.text"], "'[^']*'", "?")
```

Coloque no pipeline de traces antes do `batch`. Arquivo completo no lab: `extras/otel-collector-redige-sql.yaml`.

## Cuidados

- O padrão acima pega só literais de texto entre aspas simples; números (`LIMIT 10`, `id = 7`) continuam visíveis.
- Redação no Collector protege o backend, mas o dado já saiu da aplicação: se a rede até o Collector não é confiável, resolva na origem.
- Ative o preview em homologação primeiro (`OTEL_INSTRUMENTATION_COMMON_V3_PREVIEW=true`) e inspecione alguns spans de banco antes de promover.
- Teste também com `/dup` (`OTEL_SEMCONV_STABILITY_OPT_IN=database/dup`): o `db.query.text` não sanitizado já aparece ao lado do `db.statement` antigo.

## Fontes

- [The OpenTelemetry Java agent 3.0 is almost here — preview it today (06/10/2026)](https://opentelemetry.io/blog/2026/java-agent-3.0-preview/)
- [Convenções semânticas – spans de banco: sanitização de `db.query.text`](https://opentelemetry.io/docs/specs/semconv/db/database-spans/)
- [transform processor (contrib v0.162.0)](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/v0.162.0/processor/transformprocessor)
