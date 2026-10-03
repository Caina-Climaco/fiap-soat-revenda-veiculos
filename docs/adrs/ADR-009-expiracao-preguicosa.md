# ADR-009: Reserva com expiração preguiçosa

**Status:** Aceito
**Data:** 2026-10-03

## Contexto

Quando a compra é iniciada, o veículo fica `RESERVADO`. Se o comprador nunca pagar, o veículo não pode ficar travado para sempre.

## Alternativas avaliadas

| Alternativa | Prós | Contras |
|---|---|---|
| **Expiração preguiçosa** (lazy): verificar `expira_em` quando alguém lista os veículos à venda, tenta comprar ou o webhook chega | Sem componente extra; sempre consistente no momento da leitura relevante | O status persistido pode ficar "atrasado" até a próxima interação |
| CronJob do Kubernetes varrendo vendas vencidas | Status sempre atualizado | Mais um componente e manifesto; concorrência com as requisições |
| Fila com mensagem atrasada | Preciso | Exige broker |

## Decisão

- O TTL da reserva é configurável (`RESERVA_TTL_MINUTOS`, padrão 30).
- A expiração é aplicada:
  - no início de `ListarAVenda`, varrendo até 100 vendas vencidas por chamada;
  - em `IniciarCompra`, quando o veículo está reservado por venda vencida;
  - em `ProcessarPagamento`, quando a venda está vencida.
- Ao expirar, a venda vira `CANCELADA` com motivo `RESERVA_EXPIRADA`, e o veículo volta a `A_VENDA`. O relógio é injetado (`Clock`) para permitir testes determinísticos.

## Consequências

### Positivas
- Zero infraestrutura adicional. O comportamento visível ao usuário é sempre correto.

### Negativas
- Relatórios que leem o banco diretamente podem ver reservas vencidas ainda como ativas.

## Mitigações
- A evolução documentada é um CronJob de saneamento. Os relatórios devem usar a API.
