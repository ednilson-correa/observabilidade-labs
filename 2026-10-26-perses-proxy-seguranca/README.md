# Perses 0.55: o proxy de datasources fechou a porta do localhost (e do metadata de nuvem)

Lab da semana de 26/10/2026. O [Perses v0.55.0](https://github.com/perses/perses/releases/tag/v0.55.0) (projeto sandbox da CNCF para dashboards) saiu em 21/10/2026 com uma lista longa de correções de segurança. A que mais afeta quem opera é a do **proxy de datasources**: para impedir SSRF, ele passa a recusar por padrão loopback, link-local (incluindo o metadata de nuvem `169.254.169.254`), endereços reservados, IPs em notação não canônica e URLs com credenciais.

Na prática: **se o seu Prometheus roda no mesmo host do Perses (`http://localhost:9090`), os dashboards param depois do upgrade**, com HTTP 403, mesmo sem você ter mudado nada.

## Objetivo

Comparar, com o **mesmo banco de dados** e o **mesmo Prometheus**, três instâncias:

| Instância | Versão | Configuração do proxy | Porta |
|---|---|---|---|
| `perses-054` | 0.54.0 | — (antes do hardening) | 8054 |
| `perses-055` | 0.55.0 | padrão | 8055 |
| `perses-055-liberado` | 0.55.0 | `allowed_networks: ["127.0.0.0/8", "::1/128"]` | 8056 |

E provar:

1. O datasource `http://localhost:9090`, salvo **antes** do upgrade, passa a responder **403** no 0.55.
2. Salvar um datasource novo em localhost, em `169.254.169.254`, em `2130706433` (127.0.0.1 em decimal) ou com `user:senha@` na URL devolve **400**.
3. Datasources em rede privada (`http://prometheus:9090`) seguem funcionando.
4. `allowed_networks` com o loopback resolve o caso do localhost **sem** abrir o metadata de nuvem.
5. As respostas do proxy ganham `Content-Security-Policy: sandbox`.
6. Com `security.enable_auth: true` e sem `encryption_key`, o 0.55 **se recusa a subir** (o 0.54 subia com uma chave padrão e pública).

## Pré-requisitos

- Docker Engine + Docker Compose v2 (testado para WSL2 com Rocky Linux 10)
- Python 3 no host (só para o `scripts/verificar.py`, sem dependências)
- Portas livres: 9090, 8054, 8055, 8056

## Arquitetura

```
                 ┌─────────── namespace de rede do serviço "prometheus" ("o host") ───────────┐
                 │                                                                              │
 trafego ──────► │  perses-054 :8054 ─┐                                                         │
 (gera tráfego   │  perses-055 :8055 ─┼──► http://localhost:9090   (prom-local, salvo no banco) │
  e expõe        │  perses-055-lib :8056┘──► http://prometheus:9090 (prom-rede, rede privada)    │
  /metrics)      │                        Prometheus 3.15.1 :9090 ◄── scrape trafego:8000         │
                 └──────────────────────────────────────────────────────────────────────────────┘
```

- Os três Perses usam `network_mode: service:prometheus`, então `localhost:9090` **é** o Prometheus, como numa VM única.
- O serviço `semente` copia o mesmo banco "pré-upgrade" (`perses/seed/prom-local.yaml`) para o volume de cada Perses.
- O datasource `prom-rede` e os dashboards são provisionados por arquivo (`perses/provisioning`).
- O `trafego` consulta o proxy das três instâncias a cada 5 s e expõe `lab_perses_proxy_requests_total{instancia,datasource,code}`, a duração e a presença do header CSP.

Arquivos:

```
docker-compose.yml
.env.example
prometheus/prometheus.yml
perses/perses-054.yaml               # config 0.54
perses/perses-055.yaml               # config 0.55 padrão
perses/perses-055-liberado.yaml      # config 0.55 com loopback liberado
perses/perses-055-auth-sem-chave.yaml# auth ligada, sem encryption_key (profile à parte)
perses/seed/prom-local.yaml          # datasource "salvo antes do upgrade"
perses/provisioning/                 # projeto, datasource prom-rede e 2 dashboards
trafego/trafego.py                   # gerador de tráfego + métricas (stdlib)
scripts/verificar.py                 # matriz de verificação (stdlib)
```

## Como subir

```bash
cp .env.example .env
docker compose up -d
docker compose ps
```

Espere uns 20 segundos (o `trafego` aguarda os Perses subirem).

## Como testar

### 1. A matriz de verificação

```bash
python3 scripts/verificar.py
```

### 2. O mesmo datasource, três respostas

```bash
for p in 8054 8055 8056; do
  curl -s -o /dev/null -w "$p -> %{http_code}\n" \
    "http://localhost:$p/proxy/globaldatasources/prom-local/api/v1/query?query=up"
done
```

### 3. O log que aparece no 0.55

```bash
docker compose logs perses-055 | grep "destination is not allowed" | head -3
```

### 4. Auth sem `encryption_key`

```bash
docker compose --profile auth-sem-chave run --rm perses-055-auth-sem-chave
echo "código de saída: $?"
```

### 5. Os dashboards

- Resultado do lab: <http://localhost:8055/projects/lab/dashboards/resultado-lab>
- Dashboard "legado" que usa o `prom-local`:
  - 0.54 (funciona): <http://localhost:8054/projects/lab/dashboards/saude-prometheus-localhost>
  - 0.55 padrão (quebra com 403): <http://localhost:8055/projects/lab/dashboards/saude-prometheus-localhost>
  - 0.55 liberado (funciona): <http://localhost:8056/projects/lab/dashboards/saude-prometheus-localhost>

## Resultado do teste

Rodado em 26/10/2026 com os binários oficiais (Perses 0.54.0 e 0.55.0, Prometheus 3.15.1) e as mesmas configs do lab:

```
Teste                                                                 0.54   0.55 padrão  0.55 liberado
Proxy → prom-local (http://localhost:9090), salvo antes do upgrade     200       403          200
Proxy → prom-rede (http://prometheus:9090, rede privada)               200       200          200
Salvar datasource novo em http://localhost:9090                        200       400          200
Salvar datasource em http://169.254.169.254 (metadata de nuvem)        200       400          400
Salvar datasource em http://2130706433:9090 (127.0.0.1 em decimal)     200       400          400
Salvar datasource com credencial na URL (user:senha@)                  200       400          400
Header CSP sandbox na resposta do proxy                            ausente  presente     presente

OK: todas as verificações bateram.
```

Outros achados:

- **Provisionamento por arquivo:** um datasource em `localhost` dentro da pasta de provisioning do 0.55 **não é criado**. O Perses sobe normalmente e só registra `level=error msg="unable to create the \"GlobalDatasource\" ..."`. Quem faz GitOps de datasources precisa olhar o log depois do upgrade.
- **DNS não dribla a regra:** um nome que resolve para `127.0.0.1` (testado com uma entrada no `/etc/hosts`) é aceito ao **salvar** (200), mas a requisição pelo proxy é recusada com **403**, porque o IP é verificado na hora da conexão.
- **Auth sem chave:** o 0.55 encerra com `level=fatal ... error="encryption_key or encryption_key_file must be provided when auth is enabled"`; o 0.54, com a mesma config, sobe e só avisa que vai usar a chave padrão.
- **O 403 é decidido antes de abrir conexão:** no gerador de tráfego, a latência média do proxy para `prom-local` (janela de 10 min) ficou em ~1,3 ms no 0.55 (403) contra ~3,3 ms no 0.54 (consulta real ao Prometheus) e ~1,8 ms no 0.55 liberado. Números de um ambiente de teste, só para ilustrar: não é benchmark.

## O que foi e o que NÃO foi validado

Validado no ambiente de preparo (sem acesso a registries de container):

- `docker compose config` (com e sem o profile `auth-sem-chave`), `promtool check config` (3.15.1) e sintaxe de todos os YAML/JSON;
- `percli lint --online` (0.55.0) dos dois dashboards e do datasource provisionado;
- o fluxo completo com os **binários oficiais** dos releases do GitHub: Perses 0.54.0 e 0.55.0 (três instâncias, mesmas configs, mesmo banco semeado), Prometheus 3.15.1 e o `trafego.py`. `localhost` era o próprio host e `prometheus`/`trafego` apontavam para um IP não-loopback via `/etc/hosts`;
- todas as consultas dos dois dashboards retornando dados no Prometheus;
- `scripts/verificar.py` com todas as verificações batendo;
- o print do dashboard tirado do Perses 0.55.0 rodando com esses dados.

NÃO validado aqui:

- `docker compose up` de verdade (imagens `persesdev/perses:v0.54.0`/`v0.55.0`, `prom/prometheus:v3.15.1`, `python:3.13.7-slim`), em especial o `network_mode: service:prometheus` e o `chown` do serviço `semente` para o usuário nonroot da imagem distroless. Valide no WSL antes do push.

## Print do dashboard para as postagens

1. Com o lab rodando há pelo menos 10 minutos, abra <http://localhost:8055/projects/lab/dashboards/resultado-lab> (o Perses já abre no tema escuro se o sistema estiver em modo escuro; senão, use o ícone de engrenagem no canto superior direito).
2. No seletor de tempo, escolha **Last 15 minutes**.
3. Deixe a janela com ~1600×900 e tire o print (Win+Shift+S). Salve **fora** do repositório.
4. Opcional: tire também o print do `saude-prometheus-localhost` na porta 8055 (painéis com erro 403) e na 8054 (funcionando), para o antes/depois.

## Como derrubar

```bash
docker compose down -v
```

## Fontes

- [Perses v0.55.0 – release](https://github.com/perses/perses/releases/tag/v0.55.0) (21/10/2026)
- [Perses – upgrade de v0.54.0 para v0.55.0](https://github.com/perses/perses/blob/v0.55.0/docs/upgrade/v0.55.0.md)
- [Perses – Security considerations](https://github.com/perses/perses/blob/v0.55.0/docs/security.md)
- [Perses – DatasourceProxy config](https://github.com/perses/perses/blob/v0.55.0/docs/configuration/configuration.md#datasourceproxy-config)
- [OpenTelemetry – Strengthening OpenTelemetry security while preserving API stability](https://opentelemetry.io/blog/2026/security-versioning-policy/) (22/10/2026)
