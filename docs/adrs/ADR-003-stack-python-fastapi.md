# ADR-003: Stack Python 3.12, FastAPI, SQLAlchemy 2, Alembic e PyJWT

**Status:** Aceito
**Data:** 2026-10-03

## Contexto

A API precisa ser entregue rápido, com boa testabilidade e documentação OpenAPI para o time de front-end integrar. O autor usou Python e FastAPI nas fases anteriores e no hackathon.

## Alternativas avaliadas

| Alternativa | Prós | Contras |
|---|---|---|
| **Python 3.12 + FastAPI** | OpenAPI e Swagger automáticos, com OAuth2 no próprio Swagger; validação com Pydantic v2; experiência prévia | Desempenho bruto inferior ao de stacks compiladas, o que é irrelevante para o volume esperado |
| Java + Spring Boot | Ecossistema robusto; Spring Security com OIDC | Mais cerimônia; menos familiaridade; prazo curto |
| Node.js + NestJS | Bom ecossistema | Sem vantagem que compense trocar de stack |

## Decisão

- Python 3.12 e FastAPI.
- SQLAlchemy 2 em modo síncrono, com driver `psycopg` 3.
- Alembic para migrações.
- Pydantic v2 e pydantic-settings para configuração.
- PyJWT com `PyJWKClient` para validar os tokens do Keycloak.
- Qualidade: ruff para lint e formatação, mypy para tipagem, pytest e pytest-cov para testes.

## Consequências

### Positivas
- Reaproveita o conhecimento e os padrões das fases anteriores (Clean Architecture, fixtures de teste).
- O contrato OpenAPI é gerado do código e nunca fica desatualizado.

### Negativas
- O modo síncrono limita a concorrência por réplica.

## Mitigações
- Escala horizontal com HPA (2 a 5 réplicas) e pool de conexões dimensionado. Migrar para async é possível sem mudar o domínio.
