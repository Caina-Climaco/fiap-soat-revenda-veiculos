# ADR-002: Monólito modular para Catálogo e Vendas

**Status:** Aceito
**Data:** 2026-10-03

## Contexto

A modelagem identificou dois contextos de negócio além da identidade: **Catálogo** (anúncio e estoque de veículos) e **Vendas** (reserva, pagamento e efetivação). A compra precisa mudar os dois de forma consistente: a venda é criada e o veículo é reservado. O trabalho é individual, com 12 dias de prazo. A separação exigida pelo enunciado é entre **identidade** e **transacional**, não entre catálogo e vendas.

## Alternativas avaliadas

| Alternativa | Prós | Contras |
|---|---|---|
| **Monólito modular** (uma API, dois módulos com fronteiras explícitas) | Uma transação ACID cobre reserva e venda; um deploy; simples de testar | Escala e implanta os módulos juntos |
| Microsserviços (Catálogo e Vendas separados) | Deploy e escala independentes | Exige saga ou mensageria para manter consistência entre reserva e venda; mais infraestrutura e mais pontos de falha; custo alto para o prazo |

## Decisão

Uma única aplicação `revenda-api` com os módulos `catalogo` e `vendas`. Cada módulo tem as camadas domain, application, infrastructure e interfaces, além de **schema próprio** no PostgreSQL. Vendas conversa com Catálogo apenas pela porta `CatalogoPort` (reservar, liberar, marcar vendido), na mesma Unit of Work. É proibido importar o domínio de um módulo dentro do outro, e um teste de arquitetura verifica isso.

## Consequências

### Positivas
- Consistência forte na compra, sem saga.
- Menos componentes para implantar, observar e demonstrar no vídeo.
- As fronteiras ficam prontas para uma extração futura.

### Negativas
- Os módulos não escalam de forma independente.
- Alterar Venda e Veiculo na mesma transação desvia da regra "um agregado por transação".

## Mitigações
- A porta `CatalogoPort`, a ausência de FK entre schemas ([ADR-004](ADR-004-postgresql-schemas.md)) e o teste de arquitetura preservam a fronteira. Para extrair Vendas, basta trocar o adaptador in-process por um cliente HTTP e introduzir uma saga.
