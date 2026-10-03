# ADR-004: PostgreSQL com schemas por módulo e instância separada para identidade

**Status:** Aceito
**Data:** 2026-10-03

## Contexto

Os dados pessoais dos compradores precisam ficar apartados dos dados transacionais. Os módulos Catálogo e Vendas precisam de fronteiras claras ([ADR-002](ADR-002-monolito-modular.md)). A compra exige garantias transacionais fortes, como impedir duas vendas ativas para o mesmo veículo.

## Alternativas avaliadas

| Alternativa | Prós | Contras |
|---|---|---|
| **Instância da API com schemas `catalogo` e `vendas`, mais instância separada para o Keycloak** | ACID; índice único parcial; separação física dos dados pessoais; custo baixo | Duas instâncias para operar |
| Um banco por módulo | Isolamento máximo | Perde a transação única da compra |
| Um único PostgreSQL para tudo, inclusive o Keycloak | Uma instância a menos | Mistura dados pessoais e transacionais no mesmo servidor e nas mesmas credenciais de superusuário, o que enfraquece a separação exigida |
| NoSQL (ex.: MongoDB) | Esquema flexível | Sem ganho para um domínio relacional e transacional |

## Decisão

- **PostgreSQL 16** (imagem oficial `postgres:16-alpine`) em duas instâncias:
  - `revenda-db` (namespace `revenda`), com os schemas `catalogo` e `vendas`;
  - `keycloak-db` (namespace `identidade`).
- **Sem FK entre schemas:** `vendas.vendas.veiculo_id` é referência lógica. A integridade é garantida pela aplicação e pelo índice único parcial ([ADR-008](ADR-008-concorrencia-update-condicional.md)).
- Credenciais distintas, geradas pelo Terraform ([ADR-011](ADR-011-segredos-terraform.md)).

## Consequências

### Positivas
- Um vazamento do banco transacional não expõe nome, CPF, e-mail nem telefone, porque lá existe só o `comprador_id` pseudônimo.
- Cada módulo é dono das suas tabelas, e a extração futura de um deles fica facilitada.

### Negativas
- Sem FK, uma venda poderia, em tese, apontar para um veículo inexistente se houver bug na aplicação.
- Mais memória e armazenamento no cluster.

## Mitigações
- A criação da venda sempre passa pela `CatalogoPort`, que valida a existência do veículo e o reserva na mesma transação. Testes de integração cobrem esse caminho.
- Recursos dos StatefulSets dimensionados para o ambiente local.
