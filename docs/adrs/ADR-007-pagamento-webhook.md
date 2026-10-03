# ADR-007: Pagamento simulado por webhook com segredo compartilhado

**Status:** Aceito
**Data:** 2026-10-03

## Contexto

O vídeo exigido mostra "compra e efetivação da compra", ou seja, a compra não termina no clique. Integrar um gateway real (ex.: Mercado Pago) está fora do escopo e do prazo, mas o modelo deve refletir como a efetivação acontece na prática: de forma assíncrona, por notificação do provedor de pagamento.

## Alternativas avaliadas

| Alternativa | Prós | Contras |
|---|---|---|
| **Webhook simulado** (`POST /api/v1/pagamentos/webhook` com `X-Webhook-Secret`) | Modela o fluxo real; fácil de demonstrar via Swagger ou curl; troca por gateway real exige só um adaptador | O "gateway" é acionado manualmente na demonstração |
| Gestor confirma o pagamento manualmente | Simples | Não reflete o fluxo de pagamento online |
| Compra efetivada na hora, sem pagamento | Mais simples | Contradiz o enunciado (compra e efetivação são etapas distintas) |
| Integração com gateway real em sandbox | Realista | Credenciais, prazo e dependência externa |

## Decisão

- A compra cria a venda em `AGUARDANDO_PAGAMENTO`, com um `codigo_pagamento` único.
- O "gateway" chama o webhook com `{codigo_pagamento, status: APROVADO|RECUSADO}`.
- O segredo compartilhado é comparado em tempo constante. A tradução do payload para comandos de domínio fica numa camada anticorrupção.
- Regras de idempotência:
  - `APROVADO` para venda já `EFETIVADA` → 200, sem efeito;
  - `RECUSADO` para venda já `CANCELADA` → 200, sem efeito;
  - `APROVADO` para venda `CANCELADA` → 409;
  - `APROVADO` para venda expirada → a venda é cancelada com `RESERVA_EXPIRADA`, o veículo é liberado e a resposta é 409.

## Consequências

### Positivas
- Ciclo de vida realista e demonstrável, e idempotente diante de reentregas.
- Para adotar um gateway real, basta mudar o adaptador.

### Negativas
- O segredo compartilhado é mais fraco que uma assinatura HMAC do corpo da requisição.
- Pagamento aprovado após a expiração exigiria estorno, que está fora do escopo.

## Mitigações
- Segredo forte, gerado pelo Terraform e trocável. A evolução documentada é a assinatura HMAC com timestamp, contra replay.
- O caso do pagamento aprovado após a expiração fica registrado na resposta 409 e nos logs, para tratamento manual.
