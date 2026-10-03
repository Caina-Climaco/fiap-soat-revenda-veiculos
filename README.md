# Revenda de Veículos — API

> Trabalho Substitutivo do Tech Challenge — FIAP PósTech Software Architecture (SOAT), Fase 3.
> **Em construção.** Este README será completado com instruções de execução e testes.

API para uma revenda de veículos: cadastro e edição de veículos, compra online por clientes cadastrados, efetivação da compra via pagamento e listagens de veículos à venda e vendidos, ordenadas por preço. O cadastro e a autenticação dos compradores ficam num serviço de identidade apartado (Keycloak), com os dados pessoais separados dos dados de vendas.

## Documentação

| Documento | Conteúdo |
|---|---|
| [01 — Visão geral](docs/01-visao-geral.md) | Problema, escopo, atores, premissas |
| [02 — Modelagem DDD](docs/02-modelagem-ddd.md) | Domain Storytelling, Event Storming, linguagem ubíqua, contextos, agregados, regras |
| [03 — Requisitos](docs/03-requisitos.md) | Requisitos funcionais e não funcionais, rastreabilidade |
| [04 — Arquitetura](docs/04-arquitetura.md) | C4 (contexto, containers, componentes), implantação, sequências |
| [05 — API](docs/05-api.md) | Contrato dos endpoints |
| [06 — Dados](docs/06-dados.md) | Modelo de dados e separação dos dados pessoais |
| [07 — Segurança e LGPD](docs/07-seguranca-lgpd.md) | Ameaças, controles, LGPD |
| [08 — CI/CD e infraestrutura](docs/08-ci-cd-infra.md) | Terraform, Kubernetes, pipelines, governança Git |
| [09 — Testes](docs/09-testes.md) | Estratégia e cenários BDD |
| [10 — Plano de execução](docs/10-plano-execucao.md) | Backlog, DoR/DoD, cronograma, riscos |
| [ADRs](docs/adrs/README.md) | Decisões de arquitetura |
