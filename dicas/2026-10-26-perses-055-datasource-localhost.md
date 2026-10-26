# Dica: antes de subir o Perses 0.55, procure datasources em localhost

> Semana de 26/10/2026 · Testado com Perses 0.54.0 e 0.55.0 + Prometheus 3.15.1 · Lab relacionado: [`2026-10-26-perses-proxy-seguranca`](../2026-10-26-perses-proxy-seguranca/)

## Contexto

O Perses 0.55.0 (21/10/2026) blindou o proxy de datasources contra SSRF. Por padrão ele recusa loopback (`127.0.0.0/8`, `::1`, `localhost`), link-local e metadata de nuvem (`169.254.169.254` e afins), endereços reservados, IPs em notação não canônica (`2130706433`, `127.1`) e URLs com `user:senha@`. Rede privada (`10/8`, `172.16/12`, `192.168/16`) continua liberada.

O datasource que já estava salvo no banco **não some**: ele só passa a responder `403 Forbidden`. Salvar um novo devolve `400 Bad Request`. Por provisionamento de arquivo, ele simplesmente não é criado (só um `level=error` no log).

## O teste

Mesmo banco, mesmo Prometheus, datasource `http://localhost:9090`:

| Instância | Proxy do datasource salvo | Salvar novo em localhost | Salvar em 169.254.169.254 |
|---|---|---|---|
| 0.54 | 200 | 200 | 200 |
| 0.55 padrão | **403** | **400** | **400** |
| 0.55 + `allowed_networks` loopback | 200 | 200 | **400** |

## O que fazer

1. Liste os datasources que apontam para o próprio host (banco em arquivo; para SQL, faça o equivalente na tabela):

   ```bash
   grep -rlE '"?url"?: *"?https?://(localhost|127\.|\[::1\]|0\.0\.0\.0)' /perses/
   ```

2. Prefira apontar para um nome/IP de rede privada. Se o datasource precisa mesmo ficar no mesmo host, libere **só** o loopback:

   ```yaml
   datasource:
     proxy:
       allowed_networks:
         - "127.0.0.0/8"
         - "::1/128"
   ```

   Liberar `127.0.0.0/8` não libera `169.254.169.254`: a regra mais específica vence.

3. Se a autenticação está ligada, defina `security.encryption_key` (32 bytes) **antes** do upgrade: sem ela o 0.55 não sobe. Trocar a chave invalida os secrets cifrados com a chave padrão antiga.

## Cuidados

- Um nome DNS que resolve para `127.0.0.1` é aceito ao salvar, mas barrado (403) na hora da conexão.
- Credenciais em `headers.Authorization` do datasource passam a ser ignoradas: mova para um `Secret`.
- O proxy agora devolve `Content-Security-Policy: sandbox`: a UI do datasource (ex.: a do Prometheus) não abre mais navegando pelo proxy.

## Fonte

- [Perses – upgrade de v0.54.0 para v0.55.0](https://github.com/perses/perses/blob/v0.55.0/docs/upgrade/v0.55.0.md)
- [Perses v0.55.0](https://github.com/perses/perses/releases/tag/v0.55.0) (21/10/2026)
