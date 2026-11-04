# Filelog com checkpoint em protobuf: o ganho real e a armadilha do rollback

> Data: 02/11/2026 · Versões: OTel Collector Contrib 0.147.0, 0.148.0, 0.163.1 e 0.164.0 · Prometheus v3.15.1 · Grafana 13.3.0

O blog do OpenTelemetry anunciou em 28/10/2026 que, a partir do Collector Contrib 0.164.0, o receiver `filelog` sempre grava checkpoints em protobuf. Nos benchmarks do projeto, salvar ficou quase 5 vezes mais rápido, carregar mais de 5 vezes e o checkpoint ficou cerca de 35% menor.

Este lab responde a duas perguntas que o benchmark não responde:

1. Quanto disso aparece no processo inteiro do Collector?
2. O que acontece com o checkpoint em upgrade e em rollback?

## Objetivo

Comparar, com a mesma config e os mesmos arquivos, três instâncias:

| Serviço | Versão | Checkpoint |
|---|---|---|
| `col-json` | 0.163.1 com `--feature-gates=-filelog.protobufCheckpointEncoding` | JSON |
| `col-proto` | 0.163.1 | protobuf (padrão desde a 0.156.0) |
| `col-proto-164` | 0.164.0 | protobuf, sem opção de desligar |

A comparação limpa é entre `col-json` e `col-proto`: mesma versão, só o formato muda. A 0.164.0 entra para confirmar o comportamento da versão nova.

## Pré-requisitos

- Docker Engine + Docker Compose v2
- Python 3 no host, para os scripts (sem dependências)
- Portas livres: 3000 e 9090, ajustáveis no `.env`
- Para o `scripts/migracao.py`, porta 18899 livre

## Arquitetura

```text
gerador ──▶ volume logs (1.000 arquivos, 200 linhas/s)
                 │ somente leitura
     ┌───────────┼──────────────┐
  col-json    col-proto    col-proto-164     cada um com seu file_storage
     └───────────┼──────────────┘            e exporter nop
                 ▼ métricas internas (:8888)
            Prometheus ──▶ Grafana
```

O exporter é `nop`: o custo de exportar não entra na conta. O `poll_interval` é o padrão, 200 ms.

## Como subir

```bash
cp .env.example .env
docker compose up -d --build
```

Espere pelo menos 10 minutos. Nos primeiros 5, os painéis sobem em rampa: é o `rate()` de 5 minutos ainda sem a janela completa, não um aumento real de custo.

## Como testar

```bash
# 1. Custo em regime
python3 scripts/verificar.py

# 2. Tamanho e formato de cada checkpoint
docker compose run --rm inspecao

# 3. Upgrade e rollback (sobe um Collector por vez, em volumes temporários)
python3 scripts/migracao.py
```

## Resultado do teste

Medido com binários oficiais em uma VM de 2 vCPU, 12 minutos em regime, 1.000 arquivos e 200 linhas/s. O valor absoluto muda de máquina para máquina.

| Medida | JSON 0.163.1 | Protobuf 0.163.1 | Diferença | Protobuf 0.164.0 |
|---|---|---|---|---|
| CPU (núcleos) | 0,345 | 0,272 | **−21,2%** | 0,278 |
| Memória alocada | 111,3 MB/s | 91,7 MB/s | **−17,6%** | 91,7 MB/s |
| Checkpoint | 1.700.889 bytes | 1.065.000 bytes | **−37,4%** | 1.065.000 bytes |
| Escrita do processo (`wchar`, 60 s) | 8,56 MB/s | 5,39 MB/s | **−37,0%** | 5,39 MB/s |
| RSS | 256 MB | 249 MB | sem diferença relevante | 251 MB |
| Linhas aceitas | 200/s | 200/s | igual | 200/s |

A economia foi de cerca de 73 ms de CPU por segundo. O blog estima 61 ms para o mesmo número de arquivos (de 77 ms para 16 ms). O ganho em um processo inteiro é menor que os 5x porque o Collector faz outras coisas além de serializar checkpoint.

### Upgrade e rollback

Resultado do `scripts/migracao.py`, com 200 arquivos e 3.000 linhas iniciais:

| Passo | Versão | Linhas novas no disco | Linhas lidas | Checkpoint depois |
|---|---|---|---|---|
| 1. Primeira leitura com JSON | 0.163.1 | 3.000 | 3.000 | JSON |
| 2. Upgrade | 0.164.0 | 200 | 200 | protobuf |
| 3. Gate desligada | 0.164.0 | 0 | não sobe | sem mudança |
| 4. Rollback | 0.148.0 | 200 | 200 | JSON |
| 5. Volta | 0.164.0 | 0 | 0 | protobuf |
| 6. Rollback | 0.147.0 | 200 | não sobe | vazio (`0\n`) |
| 7a. Restart a partir do passo 6 | 0.147.0 | 0 | **3.600** | JSON |
| 7b. Volta para a nova a partir do passo 6 | 0.164.0 | 0 | **3.600** | protobuf |

O upgrade é transparente, como o anúncio diz. O problema está no passo 6:

- A 0.147.0 não entende protobuf e falha com `read known files from database: decoding file count: invalid character`.
- Ao encerrar, ela regrava o checkpoint como `0\n`, ou seja, zero arquivos conhecidos.
- No restart seguinte, em qualquer versão, os offsets não existem mais. Com `start_at: beginning`, o Collector relê tudo: 3.600 linhas em vez de 200, ou 3.400 duplicadas.

O passo 3 mostra outra mudança da 0.164.0: quem mantém `-filelog.protobufCheckpointEncoding` na linha de comando não sobe mais. A mensagem é `feature gate "filelog.protobufCheckpointEncoding" is stable, can not be disabled`.

### Reprodução no WSL2

Rodado com `docker compose`, em 02/11/2026:

| Medida | JSON 0.163.1 | Protobuf 0.163.1 | Diferença | Protobuf 0.164.0 |
|---|---|---|---|---|
| CPU (núcleos) | 0,288 | 0,229 | **−20,7%** | 0,224 |
| Memória alocada | 100,6 MB/s | 83,0 MB/s | **−17,5%** | 82,7 MB/s |
| Checkpoint | 1.700.899 bytes | 1.064.000 bytes | **−37,4%** | 1.064.000 bytes |

Essa rodada usou janela de 10 minutos com a série ainda incompleta (183,9 linhas/s em vez de 200), então os valores absolutos ficaram abaixo do regime. As porcentagens não são afetadas. O dashboard, com a janela já completa, mostrou 0,322, 0,256 e 0,250 núcleo. O `migracao.py` reproduziu toda a tabela de upgrade e rollback, incluindo as 3.600 linhas lidas.

## O que fazer

- Na 0.156.0 ou mais nova, sem opt-out, você já usa protobuf. A 0.164.0 não traz esse ganho de novo.
- Antes do upgrade, procure a gate nos seus manifestos.
- Mantenha o alvo de rollback na 0.148.0 ou mais nova. Nos testes, ela lê protobuf.
- Faça backup do diretório do `file_storage` antes de um upgrade vindo de 0.147 ou anterior. Se precisar voltar para uma versão antiga, restaure esse backup com o Collector parado.

## O que foi e o que não foi validado

**Validado com binários oficiais:** configs com `promtool check config` e `otelcol-contrib validate`, carga real, as três instâncias, todas as queries do dashboard no Prometheus, os scripts `verificar.py`, `checkpoint.py` e `migracao.py --nativo`.

**Validado no WSL2 com `docker compose`:** a subida do lab, o dashboard no Grafana 13.3.0, `verificar.py`, o serviço `inspecao` e o `migracao.py` em modo Docker, nessa rodada executado com `sudo`.

**Limites:** só testei a 0.147.0 entre as versões sem protobuf, sempre com `start_at: beginning`. Versões mais antigas devem ser conferidas no seu cenário.

## Print do dashboard no Grafana

1. Com a carga rodando há pelo menos 15 minutos, abra <http://localhost:3000/d/lab-filelog-checkpoint?kiosk&theme=dark&from=now-10m&to=now>. A janela de 10 minutos deixa de fora a rampa inicial.
2. Ajuste a janela do navegador para cerca de 1600×900.
3. Confira se os stat panels do topo têm valor. Eles usam `rate()` de 5 minutos.
4. Salve o print fora do repositório.

## Como derrubar

```bash
docker compose down -v
```

## Fontes

- [Faster, smaller checkpoints: the File Log receiver now uses protobuf](https://opentelemetry.io/blog/2026/filelog-protobuf-checkpoints/)
- [Issue #43266](https://github.com/open-telemetry/opentelemetry-collector-contrib/issues/43266)
- [PR #52037](https://github.com/open-telemetry/opentelemetry-collector-contrib/pull/52037)
- [README do filelog receiver](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/v0.164.0/receiver/filelogreceiver)
- [CHANGELOG do contrib](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.164.0/CHANGELOG.md)
