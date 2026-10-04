# ADR-001: Keycloak como provedor de identidade apartado

**Status:** Aceito
**Data:** 2026-10-03

## Contexto

O enunciado exige que o cadastro e a autorização dos compradores fiquem num serviço **totalmente apartado** do restante da solução, com os dados de clientes separados dos dados transacionais das vendas. Ele cita Auth0, Cognito, Keycloak ou uma implementação própria. O projeto é individual, tem prazo curto (15/10/2026) e não tem acesso a nenhuma conta AWS. Todo o ambiente roda num Kubernetes local (ver [ADR-005](ADR-005-kind-terraform-nodeport.md)).

## Alternativas avaliadas

| Alternativa | Prós | Contras |
|---|---|---|
| **Keycloak** (self-hosted) | OpenID Connect e OAuth 2.0 completos; autorregistro, login, papéis e perfil de usuário prontos; roda em container; custo zero; banco próprio | Consome mais memória (JVM; *limit* de 1536Mi no cluster); a configuração do realm precisa ser versionada |
| Amazon Cognito | Gerenciado; integra com a AWS | Exige conta AWS, que não está disponível; não roda localmente |
| Auth0 | Gerenciado; boa experiência para o desenvolvedor | Dependência de SaaS externo; o plano gratuito limita recursos; os dados pessoais ficariam com um operador externo |
| Implementação própria | Controle total | Reimplementar hashing de senha, emissão e rotação de tokens, recuperação de senha e proteção contra força bruta: alto risco e nenhum ganho para o objetivo do trabalho |

## Decisão

Adotar o **Keycloak 26.7.1** (imagem oficial `quay.io/keycloak/keycloak:26.7.1`, tag fixada) no namespace `identidade`, com **uma instância PostgreSQL exclusiva**. A configuração fica no realm `revenda`, versionado em `keycloak/realm-revenda.json` e importado na inicialização. Ela inclui:

- papéis `cliente` (atribuído por padrão no autorregistro) e `gestor`;
- perfil de usuário com nome, sobrenome, e-mail, CPF e telefone;
- client público `revenda-swagger` (Authorization Code + PKCE);
- client `revenda-e2e` (password grant), só para os testes e2e do ambiente local;
- mapper de audiência `revenda-api`;
- escopos `profile` e `email` apenas opcionais nos clients: o access token carrega só `sub`, papéis e audiência, sem nome nem e-mail.

A API só valida tokens JWT RS256 pela JWKS do realm. Ela nunca recebe nem guarda dados cadastrais.

## Consequências

### Positivas
- A segregação dos dados pessoais é física: outro processo, outro banco, outro namespace.
- O fluxo de cadastro, login e recuperação vem pronto e é testado pela comunidade.
- Usa um padrão aberto (OIDC). Trocar por Cognito ou Auth0 no futuro exige só mudar configuração na API.

### Negativas
- Há mais um componente para operar e mais memória consumida no cluster.
- O Keycloak não garante unicidade de atributos customizados, como o CPF.
- No ambiente local ele roda em modo `start-dev` (HTTP, sem cache distribuído).

## Mitigações
- *Limit* de memória de 1536Mi e *request* de 768Mi; o heap usa o padrão da imagem (percentual da memória do container), sem ajuste manual. A probe de readiness evita tráfego antes do realm estar importado.
- O e-mail é o identificador único. A validação de formato do CPF fica no perfil de usuário. A unicidade do CPF é registrada como limitação conhecida.
- Para produção, o caminho documentado é:
  - modo `start` com TLS, hostname fixo e cluster com cache distribuído;
  - **desativar o client `revenda-e2e`** (password grant), que existe só para os testes automatizados locais;
  - definir `OIDC_AZP_PERMITIDOS` na API apenas com os clients de produção (o padrão aceita `revenda-swagger` e `revenda-e2e`).
