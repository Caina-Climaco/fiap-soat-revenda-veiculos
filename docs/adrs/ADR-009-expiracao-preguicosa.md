# ADR-009: Reserva com expiração preguiçosa

**Status:** Aceito, complementado em 2026-10-06 (CronJob de saneamento)
**Data:** 2026-10-03

## Contexto

Quando a compra é iniciada, o veículo fica `RESERVADO`. Se o comprador nunca pagar, o veículo não pode ficar travado para sempre.

## Alternativas avaliadas

| Alternativa | Prós | Contras |
|---|---|---|
| **Expiração preguiçosa** (lazy): verificar `expira_em` quando alguém lista os veículos à venda, tenta comprar ou o webhook chega | Sem componente extra; sempre consistente no momento da leitura relevante | O status persistido pode ficar "atrasado" até a próxima interação |
| CronJob do Kubernetes varrendo vendas vencidas | Status sempre atualizado | Mais um componente e manifesto; concorrência com as requisições; sozinho não garante correção (entre duas execuções a reserva vencida continua "ativa") |
| Fila com mensagem atrasada | Preciso | Exige broker |

## Decisão

- O TTL da reserva é configurável (`RESERVA_TTL_MINUTOS`, padrão 30).
- A expiração é aplicada nas escritas:
  - em `IniciarCompra`, quando o veículo está reservado por venda vencida;
  - em `ProcessarPagamento` e `CancelarVenda`, quando a venda envolvida está vencida;
  - no início de `EditarVeiculo`, para que um veículo cuja reserva venceu volte a ser editável sem depender de uma leitura anterior.
- E também nas leituras, para que nenhuma resposta mostre uma reserva vencida como ativa:
  - no início de `ListarAVenda`, varrendo até 100 vendas vencidas por chamada;
  - em `ObterVeiculo`, quando o veículo está reservado por venda vencida;
  - em `ObterVenda`, quando a venda consultada está vencida;
  - no início das listagens de vendas (`ListarVendas`, para o comprador e para o gestor).
- Ao expirar, a venda vira `CANCELADA` com motivo `RESERVA_EXPIRADA`, e o veículo volta a `A_VENDA`. O relógio é injetado (`Clock`) para permitir testes determinísticos.
- **Complemento (2026-10-06): CronJob de saneamento.** A expiração preguiçosa continua sendo a garantia de correção da API; o CronJob `revenda-saneamento` (`k8s/saneamento/`, a cada 10 min) é só a **segunda linha de defesa**: executa `python -m revenda.expirar` (`src/revenda/expirar.py`), que reutiliza o mesmo caso de uso `ExpirarReservasVencidas` das leituras, em lotes de `SANEAMENTO_LOTE` (padrão 100, cada lote numa transação) até não sobrar reserva vencida ou atingir `SANEAMENTO_TETO` (padrão 1000) por execução. Ele existe para que relatórios que leem o banco diretamente não vejam reservas vencidas como ativas por mais de alguns minutos; nada na API depende dele.

## Consequências

### Positivas
- Zero infraestrutura adicional. O comportamento visível pela API é sempre correto: leituras e escritas aplicam a expiração antes de responder.

### Negativas
- Relatórios que leem o banco diretamente podem ver reservas vencidas ainda como ativas por até um ciclo do CronJob (10 min, mais o que exceder o teto de uma execução).
- Mais um manifesto (`k8s/saneamento/`) e um passo no CD, embora fora do caminho crítico do rollout.
- Leituras passam a poder escrever (cancelar a venda vencida e liberar o veículo), o que exige transação também em rotas `GET`; os UPDATEs condicionais mantêm essas escritas idempotentes sob concorrência.

## Mitigações
- O CronJob de saneamento, antes documentado como evolução, foi acrescentado em 2026-10-06 ([08-ci-cd-infra.md](../08-ci-cd-infra.md), seção 2.5). Ele é seguro em paralelo com as requisições porque usa os mesmos UPDATEs condicionais ([ADR-008](ADR-008-concorrencia-update-condicional.md)): se a API expirar a venda primeiro, o lote do CronJob simplesmente não a encontra mais (ou a liberação do veículo é tolerada como já feita).
- Os relatórios continuam devendo usar a API, que aplica a expiração no momento da leitura; o CronJob reduz, mas não elimina, a janela de atraso no banco.
- Testes: `tests/unit/test_expirar.py` (laço, teto, log) e `tests/integration/test_expirar.py` (PostgreSQL real, inclusive o comando `python -m revenda.expirar`).
