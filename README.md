# observabilidade-labs

Laboratórios práticos de observabilidade, SRE e DevOps — cada pasta é um tutorial reproduzível com `docker compose`.

## Como usar

```bash
git clone https://github.com/ednilson-correa/observabilidade-labs.git
cd observabilidade-labs/<pasta-do-lab>
cp .env.example .env   # se o lab tiver variáveis
docker compose up -d
```

Para derrubar: `docker compose down -v`.

## Estrutura

Cada lab fica em `AAAA-MM-DD-<tema>/` com `README.md`, `docker-compose.yml` e as configurações necessárias.

## Labs

| Data | Lab | Tema |
|------|-----|------|
| 2026-09-30 | [prometheus-otlp-nativo](./2026-09-30-prometheus-otlp-nativo/) | OTLP nativo no Prometheus 3.15 + OTel Collector (`delta_to_cumulative`, `info()`, `runtime.log_level`) |
