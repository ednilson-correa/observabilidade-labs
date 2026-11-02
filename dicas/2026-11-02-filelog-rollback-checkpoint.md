# Dica: faça backup do file_storage antes de subir um Collector antigo

> Semana de 02/11/2026 · Testado com Collector Contrib 0.147.0, 0.148.0, 0.163.1 e 0.164.0 · Lab relacionado: [`2026-11-02-filelog-checkpoint-protobuf`](../2026-11-02-filelog-checkpoint-protobuf/)

## Contexto

O checkpoint do `filelog` é gravado em protobuf por padrão desde a 0.156.0, e sem opção de desligar desde a 0.164.0. O upgrade é transparente: o JSON antigo é lido e regravado. O risco aparece ao voltar para a 0.147.0, que não entende protobuf.

## O teste

Com 200 arquivos e 200 linhas novas de verdade:

| Caminho a partir da 0.164.0 | Linhas lidas |
|---|---|
| Rollback para 0.148.0 | 200 |
| Rollback para 0.147.0 | não sobe, e o checkpoint vira `0\n` |
| Próximo restart, na 0.147.0 ou na 0.164.0 | 3.600 (3.400 duplicadas) |

## O que fazer

Mantenha o alvo de rollback na 0.148.0 ou mais nova. Vindo de versão mais antiga, copie o `file_storage` com o Collector parado antes do upgrade:

```bash
cp -a /var/lib/otelcol/file_storage /var/lib/otelcol/file_storage.bak
```

Procure também a gate, que impede a subida da 0.164.0:

```bash
grep -rn -- "-filelog.protobufCheckpointEncoding" .
```

## Cuidados

- O efeito depende do `start_at`. Com `beginning`, o Collector relê tudo.
- Só a 0.147.0 foi testada entre as versões sem protobuf.
- Em Kubernetes, um restart automático já completa o estrago: a primeira tentativa apaga o checkpoint e a segunda relê.

## Fonte

[Blog do OpenTelemetry, 28/10/2026](https://opentelemetry.io/blog/2026/filelog-protobuf-checkpoints/) e testes do lab.
