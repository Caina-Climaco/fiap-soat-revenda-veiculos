# Architecture Decision Records

Registro das decisões de arquitetura do projeto. Cada ADR descreve o contexto, as alternativas avaliadas, a decisão e as consequências.

| Nº | Decisão | Status |
|---|---|---|
| [ADR-001](ADR-001-keycloak-identidade.md) | Keycloak como provedor de identidade apartado | Aceito (atualizado por ADR-014) |
| [ADR-002](ADR-002-monolito-modular.md) | Monólito modular para Catálogo e Vendas | Aceito |
| [ADR-003](ADR-003-stack-python-fastapi.md) | Stack Python 3.12, FastAPI, SQLAlchemy 2, Alembic e PyJWT | Aceito |
| [ADR-004](ADR-004-postgresql-schemas.md) | PostgreSQL com schemas por módulo e instância separada para identidade | Aceito (atualizado por ADR-014) |
| [ADR-005](ADR-005-kind-terraform-nodeport.md) | Kubernetes local (kind via CLI) com plataforma provisionada por Terraform, NodePort sem Ingress | Aceito (atualizado por ADR-014) |
| [ADR-006](ADR-006-ci-hospedado-cd-self-hosted.md) | CI no runner hospedado do GitHub e CD em runner self-hosted | Aceito (atualizado por ADR-014) |
| [ADR-007](ADR-007-pagamento-webhook.md) | Pagamento simulado por webhook com segredo compartilhado | Aceito |
| [ADR-008](ADR-008-concorrencia-update-condicional.md) | Concorrência por UPDATE condicional e índice único parcial | Aceito |
| [ADR-009](ADR-009-expiracao-preguicosa.md) | Reserva com expiração preguiçosa | Aceito |
| [ADR-010](ADR-010-kind-load-sem-registry.md) | Imagem carregada no kind sem registry, tag = SHA | Aceito |
| [ADR-011](ADR-011-segredos-terraform.md) | Segredos gerados pelo Terraform, nada sensível versionado | Aceito (atualizado por ADR-014) |
| [ADR-012](ADR-012-observabilidade-prometheus.md) | Métricas Prometheus nativas na API, APM como evolução | Aceito |
| [ADR-013](ADR-013-sem-api-gateway-e-serverless.md) | Sem API Gateway e sem Serverless nesta entrega | Aceito |
| [ADR-014](ADR-014-identidade-em-repositorio-proprio.md) | Serviço de identidade em repositório próprio, com pipeline, Terraform e state separados | Aceito |
