# 13. Design Approval Sheet (DAS)

Folha de aprovação do desenho da solução: resume o que será entregue, as decisões e os riscos, e registra o parecer de quem aprova. O detalhe está nos documentos e ADRs referenciados.

## 13.1 Identificação

| Campo | Valor |
|---|---|
| Projeto | Revenda de Veículos — API (`fiap-soat-revenda-veiculos`) |
| Contexto | Trabalho Substitutivo do Tech Challenge, FIAP PósTech Software Architecture (SOAT), Fase 3 |
| Versão do desenho | 1.0 |
| Autor (proponente) | Cainã Clímaco |
| Data | 03/10/2026 |
| Entrega prevista | 15/10/2026 |

## 13.2 Resumo da solução e escopo

API REST (`revenda-api`, Python 3.12 e FastAPI) para uma revenda vender veículos pela internet: o gestor cadastra e edita veículos; qualquer pessoa lista os veículos à venda e os vendidos por preço; o cliente cadastrado compra, o que reserva o veículo por 30 minutos; um gateway de pagamento (simulado) confirma ou recusa a compra por webhook. Cadastro, login e dados pessoais ficam no **Keycloak**, entregue em outro repositório ([fiap-soat-revenda-identidade](https://github.com/Caina-Climaco/fiap-soat-revenda-identidade)), com pipeline, state do Terraform, namespace e banco PostgreSQL próprios; a API guarda só o `sub` do token. Tudo roda num cluster kind local compartilhado, com plataforma por Terraform e implantação por CI/CD a cada merge na `main` de cada repositório.

Fora do escopo: front-end, pagamento real, nota fiscal, nuvem pública ([01-visao-geral.md](01-visao-geral.md), seção 1.3).

## 13.3 Requisitos atendidos

| Grupo | Itens | Referência |
|---|---|---|
| Funcionais do enunciado | Cadastrar e editar veículo; cadastro de comprador em serviço apartado; compra só por cadastrados; efetivação; listagens à venda e vendidas por preço (RF-01 a RF-09) | [03, seção 3.2](03-requisitos.md#32-requisitos-funcionais) |
| Funcionais descobertos | Expiração da reserva, cancelamento, minhas compras, gestão de vendas, paginação, OpenAPI (RF-10 a RF-18) | [03, seção 3.2](03-requisitos.md#32-requisitos-funcionais) |
| Não funcionais | Segurança, LGPD, concorrência, disponibilidade, desempenho, observabilidade, CI/CD (RNF-01 a RNF-17) | [03, seção 3.3](03-requisitos.md#33-requisitos-não-funcionais) |
| Rastreabilidade | RF → endpoint → caso de uso → teste | [03, seção 3.4](03-requisitos.md#34-matriz-de-rastreabilidade) |

## 13.4 Decisões de arquitetura

| ADR | Decisão |
|---|---|
| [ADR-001](adrs/ADR-001-keycloak-identidade.md) | Keycloak como provedor de identidade apartado, com PostgreSQL próprio |
| [ADR-002](adrs/ADR-002-monolito-modular.md) | Monólito modular (Catálogo e Vendas), Clean Architecture por módulo |
| [ADR-003](adrs/ADR-003-stack-python-fastapi.md) | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PyJWT |
| [ADR-004](adrs/ADR-004-postgresql-schemas.md) | Schemas por módulo; instância separada para identidade |
| [ADR-005](adrs/ADR-005-kind-terraform-nodeport.md) | kind via CLI, plataforma por Terraform, NodePort sem Ingress |
| [ADR-006](adrs/ADR-006-ci-hospedado-cd-self-hosted.md) | CI no runner hospedado, CD no runner self-hosted restrito à `main` |
| [ADR-007](adrs/ADR-007-pagamento-webhook.md) | Pagamento simulado por webhook com segredo compartilhado |
| [ADR-008](adrs/ADR-008-concorrencia-update-condicional.md) | UPDATE condicional e índice único parcial contra venda dupla |
| [ADR-009](adrs/ADR-009-expiracao-preguicosa.md) | Expiração preguiçosa da reserva, em escritas e leituras |
| [ADR-010](adrs/ADR-010-kind-load-sem-registry.md) | Imagem carregada no kind sem registry, tag = SHA |
| [ADR-011](adrs/ADR-011-segredos-terraform.md) | Segredos gerados pelo Terraform, nada sensível versionado |
| [ADR-012](adrs/ADR-012-observabilidade-prometheus.md) | Métricas Prometheus nativas; APM como evolução |
| [ADR-013](adrs/ADR-013-sem-api-gateway-e-serverless.md) | Sem API Gateway e sem Serverless nesta entrega |
| [ADR-014](adrs/ADR-014-identidade-em-repositorio-proprio.md) | Serviço de identidade em repositório próprio, com pipeline, Terraform e state separados |

## 13.5 Atributos de qualidade

| Atributo | Como é atendido | Evidência |
|---|---|---|
| Segurança e privacidade | Identidade em repositório, pipeline, state, namespace e banco separados; token só com `sub` e papéis; e2e sem o admin do realm `master`; JWT RS256 validado; RBAC e controle por dono; segredos gerados; containers não root e somente leitura | [07](07-seguranca-lgpd.md); `test_migracoes_e_schema.py::test_schema_sem_dados_pessoais` |
| Integridade sob concorrência | UPDATE condicional, índice único parcial, transação única | `tests/integration/test_concorrencia.py` |
| Implantabilidade | PR obrigatório, 4 checks, CD automático com migração tolerante a rollback e e2e | [08](08-ci-cd-infra.md) |
| Testabilidade | Domínio sem framework, relógio injetável, cobertura mínima de 80% | [09](09-testes.md) |
| Desempenho | Índice `(status, preco)`, paginação limitada; p95 < 300 ms nas listagens | k6 `tests/carga/listagens.js` |
| Disponibilidade e escalabilidade | 2 a 5 réplicas (HPA), probes, rollout sem indisponibilidade | [04, seção 5](04-arquitetura.md#5-visão-de-implantação) |
| Observabilidade | Logs JSON com `X-Request-ID`, `/metrics` Prometheus, SLOs e alertas propostos | [12](12-observabilidade.md) |

## 13.6 Riscos e mitigações

| Risco | Mitigação | Referência |
|---|---|---|
| Keycloak consome muita memória no PC | *Limit* de 1536Mi, cluster de um nó | R-02 |
| Runner self-hosted em repositório público | CD só na `main` (dispatch validado), fork PRs com aprovação, CI de PR só no runner hospedado | R-09, [ADR-006](adrs/ADR-006-ci-hospedado-cd-self-hosted.md) |
| API implantada sem a identidade no ar (dois repositórios, ordem de implantação) | CD e script 04 da API conferem o realm `revenda` antes do `terraform apply` e falham cedo; contrato documentado no repositório de identidade | R-14, [ADR-014](adrs/ADR-014-identidade-em-repositorio-proprio.md) |
| PC desligado impede o CD | Runner em container com reinício automático; `workflow_dispatch` | R-01 |
| Sem *rate limiting* na borda | Limites de paginação, validações estritas, HPA | R-12, [ADR-013](adrs/ADR-013-sem-api-gateway-e-serverless.md) |
| Degradação sem alerta ativo | `/metrics`, SLOs e regras de alerta prontas para um coletor | R-13, [ADR-012](adrs/ADR-012-observabilidade-prometheus.md) |
| Prazo sem folga | Priorização Must/Should/Could | R-08 |

Lista completa em [10-plano-execucao.md, seção 10.5](10-plano-execucao.md#105-riscos).

## 13.7 Custos

| Item | Ambiente local (esta entrega) | Estimativa qualitativa em nuvem |
|---|---|---|
| Computação | **Zero**: kind no PC do autor | Kubernetes gerenciado com 2 a 3 nós pequenos: custo mensal baixo a moderado, dominado pelos nós |
| Bancos | Zero: PostgreSQL em StatefulSet | Duas instâncias gerenciadas (API e identidade), com backup: item mais caro depois dos nós |
| Identidade | Zero: Keycloak no cluster | Keycloak no cluster (custo de nó) ou IdP gerenciado cobrado por usuário ativo |
| CI/CD | Zero: runner hospedado gratuito para repositório público; runner self-hosted no PC | Minutos de runner e registry de imagens: baixo |
| Observabilidade | Zero: `/metrics` e logs, sem coletor | Prometheus/Grafana gerenciados (baixo) ou APM SaaS cobrado por host e volume de dados (moderado) |

## 13.8 Pendências e evoluções

- *Rate limiting* e gateway na borda (Kong DB-less), limite de reservas ativas por comprador ([ADR-013](adrs/ADR-013-sem-api-gateway-e-serverless.md)).
- Prometheus, Grafana e alertas ativos; APM com traços ([12-observabilidade.md](12-observabilidade.md)).
- Produção: TLS, Keycloak em modo `start`, desativar os clients `revenda-e2e` e `revenda-e2e-admin`, definir `OIDC_AZP_PERMITIDOS` ([ADR-001](adrs/ADR-001-keycloak-identidade.md)).
- Webhook com assinatura HMAC do corpo e proteção contra replay ([07-seguranca-lgpd.md](07-seguranca-lgpd.md), seção 3.5).
- Backend remoto do Terraform e cofre de segredos ([ADR-011](adrs/ADR-011-segredos-terraform.md)); papéis de banco separados para migração e aplicação.
- Unicidade do CPF no cadastro (limitação do Keycloak).

## 13.9 Aprovação

| Papel | Nome | Data | Parecer |
|---|---|---|---|
| Proponente (autor) | Cainã Clímaco | 03/10/2026 | Submetido para aprovação |
| Arquiteto revisor | | | |
| Segurança e privacidade (LGPD) | | | |
| Operações / plataforma | | | |
| Avaliador (FIAP) | | | |
