# ADR-013: Sem API Gateway e sem Serverless nesta entrega

**Status:** Aceito parcialmente; a parte de API Gateway foi **substituída pelo [ADR-015](ADR-015-api-gateway-kong.md)**. A parte de Serverless continua valendo (evolução).
**Data:** 2026-10-03

> **Atualização (2026-10-05).** O API Gateway deixou de ser evolução: o Kong DB-less é a única entrada HTTP da API ([ADR-015](ADR-015-api-gateway-kong.md)). O texto abaixo foi mantido como registro da decisão original; os trechos sobre gateway valem só como histórico. Diferenças em relação ao que este ADR previa: o Kong **não** valida o JWT (a validação continua só na API, num ponto único com testes), o *rate limiting* da compra é por IP (não por `sub`, que exigiria o Kong ler o token) e o webhook passou a ser protegido na borda por key-auth + ACL, além da validação na API.

## Contexto

A Fase 3 apresenta API Gateways (Kong, Azure API Management) e computação Serverless (AWS Lambda, SAM, Cognito). A solução desta entrega roda inteira num cluster kind local, sem conta de nuvem ([ADR-005](ADR-005-kind-terraform-nodeport.md)). Há um único backend HTTP (`revenda-api`), e a autenticação já é centralizada no Keycloak ([ADR-001](ADR-001-keycloak-identidade.md)), com a API validando o JWT localmente. O gateway de pagamento é externo e simulado por chamadas ao webhook ([ADR-007](ADR-007-pagamento-webhook.md)).

## Alternativas avaliadas

| Alternativa | Prós | Contras |
|---|---|---|
| **Sem gateway; API exposta por NodePort** (escolhida) | Nada a mais para operar; um salto de rede a menos; a API já valida JWT, papéis e entrada | Sem *rate limiting*, cota ou WAF na borda |
| Kong (DB-less) na frente de `/api/v1` | *Rate limiting*, validação de JWT na borda, roteamento, *plugins*; roda em container | Mais um componente e mais memória no PC; com um único backend, o ganho funcional é pequeno; duplicaria a validação de JWT já feita na API |
| Azure API Management ou AWS API Gateway | Gerenciado | Exige conta de nuvem; não roda localmente |
| Simulador do gateway de pagamento como função Serverless (Lambda/SAM) | Mostra o padrão orientado a eventos | Exige conta AWS (ou emulação local adicional); o simulador hoje é só um `curl`/Swagger, sem lógica própria |
| Cognito no lugar do Keycloak | Gerenciado, integrado à AWS | Exige conta AWS; decisão já registrada no [ADR-001](ADR-001-keycloak-identidade.md) |

## Decisão

Não usar API Gateway nem Serverless nesta entrega (a parte de API Gateway foi substituída pelo [ADR-015](ADR-015-api-gateway-kong.md)), pelos motivos:

1. sem conta de nuvem (custo zero, ambiente local);
2. um único backend, então roteamento e composição de APIs não agregam;
3. o Keycloak já centraliza a autenticação, e a API valida o token sozinha;
4. o NodePort basta para expor a API localmente.

Onde eles entrariam, quando houver ambiente em nuvem ou mais de um backend:

- *(implementado, com diferenças, no [ADR-015](ADR-015-api-gateway-kong.md))* **Kong DB-less** (configuração declarativa versionada) na frente de `/api/v1`, com o *plugin* de *rate limiting* (por IP nas rotas públicas e por `sub` em `POST /api/v1/vendas`) e o *plugin* de JWT validando a assinatura pelo JWKS do Keycloak antes de o tráfego chegar à API. A API manteria a própria validação (defesa em profundidade). Os endpoints `/health/*` e `/metrics` ficariam fora do gateway, acessíveis só dentro do cluster.
- **Simulador do gateway de pagamento como função Serverless**: uma função (AWS Lambda com SAM, por exemplo) que recebe o pedido de cobrança e, de forma assíncrona, chama `POST /api/v1/pagamentos/webhook` com o `X-Webhook-Secret` lido de um cofre (AWS Secrets Manager). É o ponto natural do sistema para Serverless: evento curto, sem estado, de baixo volume.

## Consequências

### Positivas
- Menos componentes, menos memória e menos pontos de falha num ambiente que já roda cluster, Keycloak e runner no mesmo PC.
- A API continua autossuficiente na segurança: JWT, papéis, propriedade da venda e validação de entrada não dependem de nada na borda.

### Negativas (riscos aceitos)
- ~~**Sem *rate limiting* na borda**~~: resolvido pelo [ADR-015](ADR-015-api-gateway-kong.md) (600/min por IP em `/api/v1`, 60/min por IP na compra, key-auth no webhook).
- Sem WAF; cota por consumidor só para o parceiro de pagamento (consumer `gateway-pagamento`). O Kong ([ADR-015](ADR-015-api-gateway-kong.md)) passa a ser o ponto único para políticas transversais.
- O tema Serverless da fase fica só documentado, sem implementação (continua valendo).

## Mitigações
- Limites de paginação: `limite` ≤ 100 e `deslocamento` ≤ 1.000.000 (acima disso, 422), o que impede consultas caras com `OFFSET` gigantesco.
- Validações estritas de entrada: tipos estritos, tamanhos máximos, caracteres de controle recusados, payload do webhook com formato fixo.
- Webhook com segredo comparado em tempo constante e idempotência por estado; reserva com expiração de 30 minutos.
- HPA de 2 a 5 réplicas absorve picos; o alerta `RevendaWebhookRecusado` ([12-observabilidade.md](../12-observabilidade.md)) detecta tentativa de forjar pagamento.
- *Rate limiting* na borda implementado ([ADR-015](ADR-015-api-gateway-kong.md); [07-seguranca-lgpd.md](../07-seguranca-lgpd.md), seção 3.6); risco R-12 de [10-plano-execucao.md](../10-plano-execucao.md) mitigado.
