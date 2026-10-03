# ADR-008: Controle de concorrência por UPDATE condicional e índice único parcial

**Status:** Aceito
**Data:** 2026-10-03

## Contexto

Dois clientes podem tentar comprar o mesmo veículo ao mesmo tempo. Só um pode vencer. Num cenário de várias réplicas da API, uma checagem em memória do tipo "ler status e depois gravar" sofre de condição de corrida.

## Alternativas avaliadas

| Alternativa | Prós | Contras |
|---|---|---|
| **UPDATE condicional** (`... SET status='RESERVADO', versao=versao+1 WHERE id=:id AND status='A_VENDA'`) **+ índice único parcial** em vendas ativas | Atômico no banco; funciona com N réplicas; sem lock longo | Precisa interpretar `rowcount = 0` como conflito |
| `SELECT ... FOR UPDATE` | Explícito | Lock pessimista; mais suscetível a deadlock |
| Lock distribuído (Redis) | Independe do banco | Componente extra sem necessidade |
| Só checagem na aplicação | Simples | Incorreto sob concorrência |

## Decisão

- A reserva é feita por UPDATE condicional. `rowcount = 0` gera `VeiculoIndisponivelError` (HTTP 409).
- Como segunda linha de defesa, o índice único parcial `ON vendas.vendas (veiculo_id) WHERE status IN ('AGUARDANDO_PAGAMENTO','EFETIVADA')`.
- A coluna `versao` em `catalogo.veiculos` registra as transições.

## Consequências

### Positivas
- Correto com qualquer número de réplicas, e a garantia é testável (teste de integração com duas compras simultâneas).

### Negativas
- A regra de transição aparece também no SQL, além do domínio.

## Mitigações
- O domínio continua sendo a fonte da regra (`Veiculo.reservar()`), e o repositório aplica a mesma pré-condição no UPDATE. Os testes cobrem as duas camadas.
