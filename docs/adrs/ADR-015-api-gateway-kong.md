# ADR-015: API Gateway Kong (DB-less) como única entrada HTTP da API

**Status:** Aceito
**Data:** 2026-10-05
**Substitui:** a parte de API Gateway do [ADR-013](ADR-013-sem-api-gateway-e-serverless.md)
**Atualiza:** [ADR-005](ADR-005-kind-terraform-nodeport.md) (a API deixa de ser NodePort), [ADR-012](ADR-012-observabilidade-prometheus.md) (`/metrics` deixa de ser público)

## Contexto

O [ADR-013](ADR-013-sem-api-gateway-e-serverless.md) deixou o API Gateway como evolução e aceitou riscos na borda: sem *rate limiting* nas listagens públicas e no webhook, sem um ponto único para políticas transversais, e `/metrics` publicado no mesmo NodePort da API (risco R-12 e R-13 em [10-plano-execucao.md](../10-plano-execucao.md)). A Fase 3 apresenta API Gateways (Kong, Azure API Management) como parte da arquitetura, e o ambiente continua local, sem conta de nuvem e com custo zero ([ADR-005](ADR-005-kind-terraform-nodeport.md)).

Restrições que pesam na escolha:

- o PC do autor já roda o cluster kind, o Keycloak, os dois runners e agora o monitoramento ([ADR-016](ADR-016-prometheus-grafana.md));
- a porta do host `8080` é o contrato de acesso da API (README, roteiro do vídeo, Swagger, testes e2e) e não deve mudar;
- a validação de JWT já existe na API, com testes, e não deve ficar dividida entre dois lugares;
- o webhook de pagamento é chamado por um parceiro (simulado) que se identifica por um segredo compartilhado ([ADR-007](ADR-007-pagamento-webhook.md)).

## Alternativas avaliadas

| Alternativa | Prós | Contras |
|---|---|---|
| **Kong OSS em modo DB-less, configuração declarativa versionada** (escolhida) | Roda em container no próprio cluster; configuração em arquivo revisada por PR e validada no CI (`kong config parse`); *plugins* prontos de *rate limiting*, key-auth, ACL, correlation-id, limite de payload e métricas Prometheus; sem banco extra | Mais um pod (~200 MB); Admin API somente leitura (mudança só por novo deploy); *rate limiting* com `policy: local` conta por pod |
| Kong com banco (PostgreSQL) | Admin API de escrita, mudanças em tempo de execução, contadores de *rate limiting* compartilhados (`policy: cluster`) | Mais um banco para operar e migrar; configuração deixa de ser só o que está no repositório (deriva entre Git e estado); mais memória |
| Azure API Management (ou AWS API Gateway) | Gerenciado, com portal de desenvolvedor, cotas e análises | Exige conta e assinatura de nuvem; não alcança um cluster kind local sem túnel; custo; não demonstrável no ambiente da entrega |
| Sem gateway (situação anterior do [ADR-013](ADR-013-sem-api-gateway-e-serverless.md)) | Nada a mais para operar; um salto de rede a menos | Sem *rate limiting* na borda; webhook e `/metrics` expostos direto; cada política transversal teria de entrar no código da API |
| Ingress NGINX com anotações | Componente comum em Kubernetes | Limite de taxa e autenticação por anotações, menos expressivos; sem consumer/ACL para o parceiro de pagamento; exige mudar a exposição do kind ([ADR-005](ADR-005-kind-terraform-nodeport.md)) |

## Decisão

- **Kong 3.9.3 OSS em modo DB-less** no namespace `gateway`, implantado pelo Terraform deste repositório (`infra/terraform/gateway.tf`). A configuração declarativa é um template versionado (`infra/kong/kong.yml.tftpl`), renderizado com `templatefile` e entregue ao pod num **Secret** `kong-config` (ele contém a credencial do parceiro de pagamento). Uma mudança no template muda o *hash* anotado no pod e reinicia o Kong.
- **Única entrada HTTP da API**: o Service `kong` é NodePort 30080 → `http://localhost:8080` (a mesma porta de antes). O Service `revenda-api` passa a **ClusterIP**, e a NetworkPolicy `revenda-api-somente-gateway` só aceita tráfego na porta 8000 vindo do Kong, do Prometheus e do próprio nó (probes do kubelet).
- **Rotas** do serviço `revenda-api` (upstream `http://revenda-api.revenda.svc.cluster.local:80`):

| Rota | Caminho | *Plugins* da rota |
|---|---|---|
| `api` | `/api/v1` (todos os métodos) | `rate-limiting` 600/min por IP |
| `compra` | `POST /api/v1/vendas` | `rate-limiting` 60/min por IP |
| `webhook-pagamento` | `POST /api/v1/pagamentos/webhook` | `key-auth` (header `X-Webhook-Secret`) + `acl` só para o consumer `gateway-pagamento` |
| `documentacao` | `GET /docs`, `GET /openapi.json` | — |
| `saude` | `GET /health/*` | — |

- **Plugins globais**: `correlation-id` (`X-Request-ID`; gera UUID quando o cliente não manda e devolve na resposta), `request-size-limiting` (1 MB) e `prometheus` (métricas no *status listener* `:8100`, coletadas pelo Prometheus do cluster).
- **`/metrics` da API não tem rota no Kong**: pelo host responde 404 do próprio gateway; só o Prometheus lê, dentro do cluster.
- **Consumer `gateway-pagamento`**, com credencial key-auth igual ao segredo do webhook (o mesmo `random_password` do Terraform que alimenta o Secret `revenda-webhook-secret`). `hide_credentials: false`: o header chega à API, que **continua validando o segredo** em tempo constante (defesa em profundidade, [ADR-007](ADR-007-pagamento-webhook.md)).
- **JWT continua validado só na API**, pelo JWKS do Keycloak. O Kong não duplica a validação: a regra fica num ponto só, que já tem testes de unidade, integração e e2e. O gateway cuida da borda: limite de taxa, credencial do parceiro de pagamento, correlação, tamanho de payload e métricas.
- **Admin API do Kong só em `127.0.0.1:8001`**, dentro do pod (somente leitura em DB-less); não há Service para ela.
- **Validação no CI**: o job `infra` renderiza o template com valores de teste e roda `kong config parse` na mesma imagem do cluster. No CD, os testes e2e rodam com `E2E_GATEWAY=1` e passam obrigatoriamente pelo Kong (`tests/e2e/test_e2e_gateway.py`).

## Consequências

### Positivas
- *Rate limiting* na borda, com limite mais restrito na compra; respostas `429` e cabeçalhos `RateLimit-*`/`X-RateLimit-*` padronizados, sem código na API.
- Webhook barrado no gateway quando a credencial falta ou está errada (401 do Kong, sem chegar à API), e validado de novo na API quando passa.
- `/metrics`, `/health/*` e qualquer caminho não roteado deixam de ser alcançáveis diretamente do host pela API; a superfície exposta passa a ser a lista de rotas do arquivo declarativo.
- Correlação ponta a ponta: o mesmo `X-Request-ID` aparece no log do Kong e no log JSON da API.
- Métricas do gateway (requisições por rota, barradas 401/403/429, latência total, do *upstream* e do próprio Kong) entram no painel e nos alertas ([ADR-016](ADR-016-prometheus-grafana.md)).
- Toda a configuração está no repositório, revisada por PR e validada no CI; não há estado do gateway fora do Git.

### Negativas
- Mais um componente no caminho de toda requisição: um salto de rede a mais e mais um ponto de falha (uma réplica do Kong).
- Contadores de *rate limiting* locais ao pod (`policy: local`): com mais réplicas do Kong, o limite efetivo se multiplica.
- O segredo do webhook passa a existir em dois Secrets (`revenda-webhook-secret` e `kong-config`); a rotação exige reaplicar o Terraform, que atualiza os dois juntos.
- Quem já tinha o cluster precisa recriá-lo para as novas portas do monitoramento (o kind não acrescenta portas a um cluster existente).
- Mudança de rota ou de limite exige novo deploy (Admin API somente leitura).

## Mitigações
- Alerta `KongFora` e verificação do `/health/ready` através do Kong no CD; `kubectl -n gateway logs deployment/kong` no diagnóstico de falha do CD.
- Limites em variáveis do Terraform (`kong_limite_geral_minuto`, `kong_limite_compra_minuto`); com mais réplicas, trocar para `policy: redis` ou `cluster`.
- Alerta `KongRejeicoesNaBorda` para volume anormal de 401/403/429 ([12-observabilidade.md](../12-observabilidade.md)).
- Procedimento de migração (recriar o cluster) no README, seção "Migração para o API Gateway e o monitoramento".

## Referências
- [07-seguranca-lgpd.md](../07-seguranca-lgpd.md), seção 3.6 (proteção de borda)
- [08-ci-cd-infra.md](../08-ci-cd-infra.md) (recursos Terraform e etapas do CI/CD)
- [Kong Gateway — DB-less and declarative configuration](https://docs.konghq.com/gateway/latest/production/deployment-topologies/db-less-and-declarative-config/)
- [Kong — Rate Limiting plugin](https://docs.konghq.com/hub/kong-inc/rate-limiting/), [Key Authentication](https://docs.konghq.com/hub/kong-inc/key-auth/), [ACL](https://docs.konghq.com/hub/kong-inc/acl/), [Correlation ID](https://docs.konghq.com/hub/kong-inc/correlation-id/), [Prometheus](https://docs.konghq.com/hub/kong-inc/prometheus/)
