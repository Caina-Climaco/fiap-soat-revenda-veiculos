# Revenda de Veículos — API

[![CI](https://github.com/Caina-Climaco/fiap-soat-revenda-veiculos/actions/workflows/ci.yml/badge.svg)](https://github.com/Caina-Climaco/fiap-soat-revenda-veiculos/actions/workflows/ci.yml)

Trabalho Substitutivo do Tech Challenge — FIAP PósTech Software Architecture (SOAT), Fase 3.
Autor: Cainã Clímaco — RM366473 (trabalho individual).

> **Esta entrega tem dois repositórios.** Este é o da **API** (Catálogo e Vendas). O serviço de **identidade** (Keycloak, cadastro e autorização de compradores), que o enunciado exige "totalmente apartado do resto da solução", está em **[fiap-soat-revenda-identidade](https://github.com/Caina-Climaco/fiap-soat-revenda-identidade)**, com código, Terraform, state, CI, CD e runner próprios ([ADR-014](docs/adrs/ADR-014-identidade-em-repositorio-proprio.md)). Para subir o ambiente, comece por ele.

Este README segue o que o enunciado pede: [o que é o projeto](#1-o-que-é), [como foi implementado](#2-como-foi-implementado), [como usar localmente](#3-como-usar-localmente) e [como testar](#4-como-testar). Os detalhes de cada decisão estão em [`docs/`](docs/01-visao-geral.md).

## Sumário

1. [O que é](#1-o-que-é)
2. [Como foi implementado](#2-como-foi-implementado)
3. [Como usar localmente](#3-como-usar-localmente)
4. [Como testar](#4-como-testar)
5. [Fluxo de contribuição](#5-fluxo-de-contribuição)
6. [Estrutura de pastas](#6-estrutura-de-pastas)
7. [Limitações conhecidas](#7-limitações-conhecidas)
8. [Migração para dois repositórios](#8-migração-para-dois-repositórios)
9. [Migração para o API Gateway e o monitoramento](#9-migração-para-o-api-gateway-e-o-monitoramento)
10. [Autor](#10-autor)

---

## 1. O que é

### 1.1 Problema

Uma revenda de veículos quer vender pela internet. A interface (front-end) é de outros times; este projeto entrega o **back-end**: uma API REST e a infraestrutura que a executa, com implantação automatizada. Toda mudança, de código ou de infraestrutura, entra por Pull Request e passa por pipeline de CI/CD.

### 1.2 Funcionalidades

Pedidas no enunciado:

| Funcionalidade | Endpoint / onde |
|---|---|
| Cadastrar veículo (marca, modelo, ano, cor, preço) | `POST /api/v1/veiculos` (gestor) |
| Editar veículo | `PATCH /api/v1/veiculos/{id}` (gestor) |
| Cadastro de compradores em serviço de identidade separado | Tela de registro do Keycloak (realm `revenda`), no [repositório de identidade](https://github.com/Caina-Climaco/fiap-soat-revenda-identidade) |
| Compra pela internet, só por pessoas cadastradas | `POST /api/v1/vendas` (cliente) |
| Efetivação da compra | `POST /api/v1/pagamentos/webhook` (gateway de pagamento simulado) |
| Listar veículos à venda, do mais barato ao mais caro | `GET /api/v1/veiculos/a-venda` (público) |
| Listar veículos vendidos, do mais barato ao mais caro | `GET /api/v1/veiculos/vendidos` (público) |

Descobertas na modelagem (o enunciado avisa que "nem todos os campos e funcionalidades estão descritos"; regras completas em [docs/02, seção 2.7](docs/02-modelagem-ddd.md#27-regras-de-negócio-descobertas)):

- **Reserva com expiração**: a compra reserva o veículo por 30 minutos (configurável); sem pagamento, a venda é cancelada (`RESERVA_EXPIRADA`) e o veículo volta à vitrine.
- **Preço congelado**: o preço de venda é copiado no início da compra; editar o veículo depois não afeta a compra.
- **Edição só de veículo à venda**: veículo reservado ou vendido não pode ser editado (409).
- **Uma venda ativa por veículo**: dois compradores simultâneos nunca levam o mesmo carro (um recebe 201, o outro 409).
- **Pagamento recusado** cancela a venda e devolve o veículo à vitrine; notificações repetidas do gateway são idempotentes.
- **Cancelamento** pelo comprador (desistência) ou pela loja enquanto a venda aguarda pagamento.
- **Gestor não compra** (403), mesmo que tenha também o papel `cliente`.
- **Minhas compras**, consulta de venda (cliente vê só as próprias; venda alheia retorna 404) e listagem de vendas para o gestor, com filtro por status.
- Consulta de veículo por id, paginação nas listagens (`limite` ≤ 100, `deslocamento` ≤ 1.000.000), validação estrita de entrada (mensagens em português), erros em `application/problem+json` (RFC 9457), endpoints de saúde (`/health/live`, `/health/ready`) e métricas Prometheus em `/metrics` (lidas só dentro do cluster).
- **API Gateway (Kong)** como única entrada HTTP: *rate limiting* por IP (mais restrito na compra), credencial do parceiro de pagamento no webhook, `X-Request-ID` e limite de payload na borda ([seção 2.10](#210-api-gateway-kong)).
- **Monitoramento** com Prometheus e Grafana no cluster: painel de negócio, golden signals da API e do gateway, e regras de alerta testadas no CI ([seção 2.11](#211-monitoramento-prometheus-e-grafana)).

### 1.3 Identidade separada dos dados transacionais

Cadastro, login e papéis ficam no **Keycloak**, que é outro sistema: **outro repositório**, outro pipeline de CI/CD, outro state do Terraform, outro namespace do Kubernetes (`identidade`) e banco PostgreSQL **próprio**, em outra instância. Nome, sobrenome, e-mail, CPF e telefone existem só ali. Este repositório não contém o realm, nem os segredos, nem a infraestrutura do Keycloak; a API não tem credencial para o banco dele: ela valida o token (JWT) e guarda na venda apenas o `comprador_id`, que é o identificador opaco `sub` do token.

Do ponto de vista da LGPD, isso aplica o princípio da necessidade (art. 6º, III): o banco transacional não contém dados pessoais diretos, e a ligação entre venda e pessoa só pode ser refeita com a informação mantida separadamente no serviço de identidade. A análise completa (base legal, direitos do titular, exclusão de conta) está em [docs/07](docs/07-seguranca-lgpd.md).

---

## 2. Como foi implementado

### 2.1 Visão de containers

Diagrama resumido; a versão C4 completa (contexto, containers, componentes e implantação) está em [docs/04](docs/04-arquitetura.md).

```mermaid
flowchart LR
  usuario(["Gestor / Cliente / Visitante<br/>navegador ou Swagger UI"])
  gw(["Gateway de pagamento<br/>simulado (Swagger ou curl)"])

  subgraph NSG["namespace gateway"]
    kong["API Gateway Kong 3.9.3<br/>DB-less, rate limiting,<br/>key-auth do webhook"]
  end

  subgraph NSO["namespace observabilidade"]
    prom["Prometheus 3.14<br/>coleta e alertas"]
    graf["Grafana 13.2<br/>painel"]
  end

  subgraph NSR["namespace revenda"]
    api["revenda-api (ClusterIP)<br/>Python 3.12, FastAPI<br/>módulos Catálogo e Vendas"]
    mig["Job revenda-migracao<br/>upgrade head tolerante a rollback"]
    dbr[("PostgreSQL revenda<br/>schemas catalogo e vendas<br/>sem dados pessoais")]
  end

  subgraph NSI["namespace identidade (repositório fiap-soat-revenda-identidade)"]
    kc["Keycloak 26.7.1<br/>realm revenda"]
    dbk[("PostgreSQL keycloak<br/>nome, e-mail, CPF, telefone")]
  end

  usuario -->|"HTTP :8080<br/>Bearer JWT"| kong
  usuario -->|"login e cadastro :8180<br/>OIDC + PKCE"| kc
  usuario -->|"painel :3000"| graf
  gw -->|"POST /api/v1/pagamentos/webhook<br/>X-Webhook-Secret"| kong
  kong -->|"HTTP (único caminho<br/>de entrada)"| api
  prom -->|"scrape /metrics"| api
  prom -->|"scrape :8100"| kong
  graf -->|"PromQL"| prom
  api -->|"SQL"| dbr
  mig -->|"DDL"| dbr
  api -->|"JWKS em cache"| kc
  kc -->|"JDBC"| dbk
```

Todos os namespaces rodam no mesmo cluster kind local (`revenda`), que é a plataforma compartilhada; cada repositório implanta só os seus namespaces (este: `revenda`, `gateway` e `observabilidade`; o de identidade: `identidade`), com Terraform e state próprios. A API depende apenas do **contrato público** da identidade: issuer `http://localhost:8180/realms/revenda`, JWKS interno `http://keycloak.identidade.svc.cluster.local:8080/realms/revenda/protocol/openid-connect/certs`, audiência `revenda-api`, papéis `cliente` e `gestor` e client do Swagger `revenda-swagger` (configurados em [`k8s/base/configmap.yaml`](k8s/base/configmap.yaml)).

| Repositório | Conteúdo | Pipelines |
|---|---|---|
| [fiap-soat-revenda-veiculos](https://github.com/Caina-Climaco/fiap-soat-revenda-veiculos) (este) | API, migrações, manifestos `k8s/`, Terraform dos namespaces `revenda` (banco, segredos, NetworkPolicies, metrics-server), `gateway` (Kong) e `observabilidade` (Prometheus, Grafana) | CI `qualidade`, `testes`, `imagem`, `infra`; CD no runner `revenda-runner` com e2e |
| [fiap-soat-revenda-identidade](https://github.com/Caina-Climaco/fiap-soat-revenda-identidade) | Realm `revenda` versionado, Terraform do namespace `identidade` (Keycloak, banco do Keycloak, segredos, NetworkPolicy, Job `keycloak-reconciliar`) | CI `qualidade`, `realm` (Keycloak real e testes de contrato), `infra`; CD no runner `revenda-runner-identidade` |

### 2.2 Stack

| Camada | Tecnologia |
|---|---|
| API | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (síncrono), Alembic, PyJWT (JWKS), psycopg 3, Uvicorn |
| Identidade (outro repositório) | Keycloak 26.7.1, realm versionado em `keycloak/realm-revenda.json` do [repositório de identidade](https://github.com/Caina-Climaco/fiap-soat-revenda-identidade) |
| Bancos | PostgreSQL 16 (`revenda`, deste repositório; o `keycloak` é outra instância, do repositório de identidade) |
| Infraestrutura | Docker Desktop, kind (Kubernetes 1.34), Terraform (providers `kubernetes`, `helm`, `random`), kustomize, metrics-server |
| API Gateway | Kong Gateway OSS 3.9.3, modo DB-less (configuração declarativa versionada) |
| Monitoramento | Prometheus 3.14.0, Grafana 13.2.3 (fonte de dados, painel e alertas versionados) |
| CI/CD | GitHub Actions: CI no runner hospedado, CD em runner self-hosted em container |
| Qualidade | pytest, pytest-cov, ruff, mypy (strict), import-linter, Trivy, kubeconform, hadolint, shellcheck, `kong config parse`, promtool (`check` e `test rules`) |
| Ferramentas de desenvolvimento | uv (com `uv.lock`), docker compose |

### 2.3 Domain-Driven Design

O domínio foi modelado com Domain Storytelling e Event Storming ([docs/02](docs/02-modelagem-ddd.md)). Resultado:

- **Contextos delimitados**: Vendas (subdomínio principal), Catálogo (suporte), Identidade e Acesso (genérico, resolvido com Keycloak) e Gateway de Pagamento (externo, simulado).
- **Agregados**: `Veiculo` (estados `A_VENDA`, `RESERVADO`, `VENDIDO`) e `Venda` (`AGUARDANDO_PAGAMENTO`, `EFETIVADA`, `CANCELADA`), com invariantes e máquinas de estado.
- **Mapa de contextos**: Identidade publica OIDC/JWT (Open Host Service) e os módulos se conformam; Catálogo é fornecedor de Vendas pela porta `CatalogoPort`; o webhook do gateway é uma camada anticorrupção.
- **Linguagem ubíqua** em português no código (`Veiculo`, `Venda`, `reservar`, `efetivar`, `codigo_pagamento`).

Requisitos e rastreabilidade em [docs/03](docs/03-requisitos.md).

### 2.4 Clean Architecture e monólito modular

Uma única API (`revenda-api`) com dois módulos, `catalogo` e `vendas`, cada um com as camadas `domain`, `application`, `infrastructure` e `interfaces`. O domínio usa só a biblioteca padrão; casos de uso não conhecem FastAPI nem SQLAlchemy; Vendas fala com Catálogo apenas pela porta `CatalogoPort`, ligada em `composicao.py`. Essas regras são verificadas no CI pelo **import-linter** (contratos em `pyproject.toml`) e por um teste de arquitetura.

Por que monólito modular e não microsserviços: a separação exigida pelo enunciado é identidade × transacional, e ela é física (Keycloak em outro repositório, namespace e banco). Entre Catálogo e Vendas basta a fronteira lógica, o que permite reservar o veículo e criar a venda na **mesma transação** sem saga nem mensageria ([ADR-002](docs/adrs/ADR-002-monolito-modular.md)). Cada módulo tem seu schema (`catalogo`, `vendas`) e não há chave estrangeira entre eles ([ADR-004](docs/adrs/ADR-004-postgresql-schemas.md)).

### 2.5 Keycloak (serviço de identidade, outro repositório)

O Keycloak e o realm `revenda` são mantidos no [repositório de identidade](https://github.com/Caina-Climaco/fiap-soat-revenda-identidade); a referência completa (configuração do realm, segredos, implantação e o contrato publicado) está no `README.md` e em `docs/contrato-identidade.md` daquele repositório. O que a API consome:

- Realm `revenda` com autocadastro (nome, sobrenome, e-mail e **CPF** obrigatórios, telefone opcional), login por e-mail e idioma `pt-BR`.
- Papéis `cliente` (padrão de todo autocadastro) e `gestor` (usuário seed `gestor.loja`).
- Clients: `revenda-swagger` (público, Authorization Code + PKCE S256, usado pelo botão *Authorize* do Swagger), `revenda-api` (apenas audiência) e, **só no ambiente local**, `revenda-e2e` (password grant, para obter tokens nos testes) e `revenda-e2e-admin` (client credentials com apenas `manage-users`, `view-users` e `query-users` do realm `revenda`, para os testes criarem e apagarem compradores).
- A API valida assinatura RS256 pelo JWKS (em cache), `iss`, `exp`, `aud = revenda-api` e `azp`; os papéis vêm de `realm_access.roles`.

Decisão em [ADR-001](docs/adrs/ADR-001-keycloak-identidade.md) e, sobre a separação em outro repositório, [ADR-014](docs/adrs/ADR-014-identidade-em-repositorio-proprio.md).

### 2.6 Concorrência e expiração da reserva

- A reserva é um `UPDATE` condicional: `UPDATE catalogo.veiculos SET status='RESERVADO' ... WHERE id=:id AND status='A_VENDA'`. Com zero linhas afetadas, o veículo está indisponível e a API responde 409. Um **índice único parcial** (`ux_vendas_veiculo_ativa`) garante no banco no máximo uma venda ativa por veículo ([ADR-008](docs/adrs/ADR-008-concorrencia-update-condicional.md)). Um teste de integração dispara compras simultâneas do mesmo veículo e confirma exatamente um 201.
- A expiração é **preguiçosa**, sem agendador: a venda vencida é cancelada quando alguém a toca (nova compra do veículo, webhook, cancelamento, consulta do veículo ou da venda, listagens de vendas) e a listagem `a-venda` faz uma varredura limitada antes de consultar; nenhuma leitura mostra reserva vencida como ativa ([ADR-009](docs/adrs/ADR-009-expiracao-preguicosa.md)).

### 2.7 Pagamento por webhook

A compra devolve um `codigo_pagamento` (`PAG-` + 12 hexadecimais). O gateway, externo e aqui simulado, notifica o resultado em `POST /api/v1/pagamentos/webhook` com `{"codigo_pagamento": "...", "status": "APROVADO" | "RECUSADO"}` e o header `X-Webhook-Secret`, comparado em tempo constante. `APROVADO` efetiva a venda e marca o veículo como vendido; `RECUSADO` cancela e libera o veículo; repetições são idempotentes; aprovação após a expiração cancela a venda e responde 409 ([ADR-007](docs/adrs/ADR-007-pagamento-webhook.md), [docs/05, seção 4.13](docs/05-api.md#413-post-apiv1pagamentoswebhook--notificação-do-gateway)).

### 2.8 Infraestrutura

Tudo roda no PC do autor (Windows 11, Docker Desktop), sem nuvem:

- **Cluster kind** `revenda` criado pela **CLI `kind`** a partir de [`infra/kind/cluster.yaml`](infra/kind/cluster.yaml) (um nó, imagem fixada por digest, portas do host em `127.0.0.1`: 8080 → API Gateway (Kong), 8180 → Keycloak, 3000 → Grafana, 9090 → Prometheus, 15432 → banco da API para demonstração). O cluster é a **plataforma local compartilhada** pelos dois repositórios: o `cluster.yaml` é idêntico nos dois, e o CD de cada um cria o cluster se ele faltar. O plano original usava o provider Terraform `tehcyx/kind`, mas o binário dele não tem assinatura de código e foi bloqueado pelo **Smart App Control** do Windows 11; a CLI `kind` é assinada ([ADR-005](docs/adrs/ADR-005-kind-terraform-nodeport.md): kind via CLI, plataforma por Terraform, NodePort sem Ingress).
- **Terraform** ([`infra/terraform`](infra/README.md)) cuida do que é da API **dentro** do cluster: namespace `revenda`, senhas aleatórias entregues como Secrets (`revenda-db-credentials`, `revenda-webhook-secret`), o PostgreSQL `revenda-db` (StatefulSet + PVC), as NetworkPolicies do banco e da API, o metrics-server, o API Gateway Kong (namespace `gateway`) e Prometheus e Grafana (namespace `observabilidade`). O state fica fora do repositório, em `%USERPROFILE%\.revenda\revenda-api.tfstate` ([ADR-011](docs/adrs/ADR-011-segredos-terraform.md)). O namespace `identidade` (Keycloak, banco do Keycloak, segredos dele) é do repositório de identidade, com o state `%USERPROFILE%\.revenda\identidade.tfstate` ([ADR-014](docs/adrs/ADR-014-identidade-em-repositorio-proprio.md)).
- **Aplicação** por kustomize ([`k8s/`](k8s/README.md)): Deployment `revenda-api` (não root, sistema de arquivos somente leitura, probes), Service **ClusterIP** (o host chega à API só pelo Kong), HPA 2..5 réplicas e Job de migração Alembic executado antes de cada rollout. A imagem `revenda-api:<sha>` é carregada no nó com `kind load`, sem registry ([ADR-010](docs/adrs/ADR-010-kind-load-sem-registry.md)).

### 2.9 CI/CD

| Etapa | Onde | O que faz |
|---|---|---|
| Pull Request | GitHub | `main` protegida: PR obrigatório, 4 checks obrigatórios, branch atualizada, histórico linear, sem force push, regras valendo também para administradores, só squash merge |
| CI ([`ci.yml`](.github/workflows/ci.yml)) | Runner hospedado (`ubuntu-latest`), em todo PR e push na `main` | `qualidade`: ruff (lint e formato), mypy, import-linter. `testes`: unit + integração contra PostgreSQL de serviço, cobertura mínima de 80%. `imagem`: build da imagem, Trivy (vulnerabilidades CRITICAL/HIGH corrigíveis) e varredura de segredos. `infra`: `terraform fmt`/`validate`, kubeconform nos manifestos, `kong config parse` da configuração do gateway, `promtool check`/`test rules` dos alertas e JSON do painel, validação do `cluster.yaml`, hadolint e shellcheck do runner (o contrato do realm é testado no CI do repositório de identidade). Um quinto job, `titulo-pr`, valida o título no padrão Conventional Commits (não é obrigatório na proteção) |
| CD ([`cd.yml`](.github/workflows/cd.yml)) | Runner **self-hosted** num **container Linux** no Docker Desktop (labels `self-hosted`, `Linux`, `kind-local`), só em push na `main` (PR mergeado) ou disparo manual com `ref` ancestral da `main` (outra `ref` é recusada) | Cria o cluster kind se faltar; **confere que o realm `revenda` responde** (sem ele, falha cedo pedindo para implantar a identidade); `terraform apply` (state `revenda-api.tfstate`: API, Kong, Prometheus, Grafana); build `revenda-api:<sha>`; `kind load`; Job de migração; rollout do Deployment; aguarda a API pelo Kong; **confere o monitoramento** (alvos da API e do Kong `up` no Prometheus, regras carregadas, painel no Grafana); **testes e2e** pelo gateway; resumo no job summary |

O serviço de identidade tem CI e CD próprios, no repositório dele; o CD da API não implanta nem altera o Keycloak, só consome o contrato (o realm publicado e os Secrets de contrato `keycloak-gestor` e `keycloak-e2e`). O runner roda em container porque o runner nativo para Windows também foi bloqueado pelo Smart App Control. O container fica na rede docker `kind` e compartilha o state do Terraform com os scripts do Windows por bind mount ([ADR-006](docs/adrs/ADR-006-ci-hospedado-cd-self-hosted.md), [docs/08](docs/08-ci-cd-infra.md)). Cada deploy termina com os 23 testes e2e verdes (18 do fluxo da API e 5 do gateway; [seção 4.3](#43-testes-ponta-a-ponta-e2e)). Rollback: *Actions > CD > Run workflow* com `ref` = SHA anterior da `main`; o Job de migração da versão anterior reconhece o schema mais novo e não o altera ([docs/08, seção 6](docs/08-ci-cd-infra.md#6-rollback)).

### 2.10 API Gateway (Kong)

O **Kong 3.9.3 em modo DB-less** (namespace `gateway`) é a única entrada HTTP da API: `http://localhost:8080` → NodePort 30080 → Kong → Service `revenda-api` (ClusterIP). A NetworkPolicy `revenda-api-somente-gateway` só deixa o Kong, o Prometheus e o próprio nó (probes) chegarem à API. A configuração é declarativa e versionada ([`infra/kong/kong.yml.tftpl`](infra/kong/kong.yml.tftpl)), renderizada pelo Terraform num Secret e validada no CI com `kong config parse` ([ADR-015](docs/adrs/ADR-015-api-gateway-kong.md)).

| Rota | Caminho | Proteção na borda |
|---|---|---|
| `api` | `/api/v1` | *Rate limiting* 600 req/min por IP |
| `compra` | `POST /api/v1/vendas` | *Rate limiting* 60 req/min por IP |
| `webhook-pagamento` | `POST /api/v1/pagamentos/webhook` | key-auth (`X-Webhook-Secret`) + ACL: só o consumer `gateway-pagamento`; a API valida o mesmo segredo de novo |
| `documentacao` | `GET /docs`, `GET /openapi.json` | — |
| `saude` | `GET /health/*` | — |

Em todas as rotas: `X-Request-ID` (gerado se ausente e devolvido na resposta), payload máximo de 1 MB e métricas do gateway para o Prometheus. `/metrics` da API **não tem rota** (404 do Kong) e a Admin API do Kong não é exposta. O JWT continua validado **só na API**, pelo JWKS do Keycloak: o gateway cuida da borda, a API das regras de acesso.

### 2.11 Monitoramento (Prometheus e Grafana)

Logs JSON em stdout com `X-Request-ID` e sem dados pessoais; probes de vida e prontidão; métricas Prometheus em `GET /metrics` (latência, volume e erros por rota template, contadores de negócio); metrics-server para o HPA ([ADR-012](docs/adrs/ADR-012-observabilidade-prometheus.md)). No namespace `observabilidade` ([ADR-016](docs/adrs/ADR-016-prometheus-grafana.md)):

- **Prometheus 3.14.0** (`http://localhost:9090`) coleta cada réplica da API e o Kong, por descoberta de pods restrita aos namespaces `revenda` e `gateway`, e avalia 8 regras de alerta versionadas em [`infra/observabilidade/alertas.yml`](infra/observabilidade/alertas.yml), com testes de unidade (`promtool test rules`) no CI. Sem Alertmanager: os alertas aparecem em `http://localhost:9090/alerts` e no painel.
- **Grafana 13.2.3** (`http://localhost:3000`, leitura anônima) abre direto no painel provisionado **"Revenda de Veículos — visão geral"**: negócio (vendas iniciadas, efetivadas e canceladas, veículos cadastrados, réplicas, alertas disparando), golden signals da API e métricas do Kong (requisições por rota, barradas 401/403/429, latências).

O APM (New Relic ou Datadog) e os traços distribuídos continuam como evolução documentada ([docs/12](docs/12-observabilidade.md)). Serverless também fica como evolução ([ADR-013](docs/adrs/ADR-013-sem-api-gateway-e-serverless.md)).

### 2.12 Documentação

| Documento | Conteúdo |
|---|---|
| [01 — Visão geral](docs/01-visao-geral.md) | Problema, escopo, atores, premissas, restrições |
| [02 — Modelagem DDD](docs/02-modelagem-ddd.md) | Domain Storytelling, Event Storming, linguagem ubíqua, contextos, agregados, máquinas de estado, regras descobertas |
| [03 — Requisitos](docs/03-requisitos.md) | Requisitos funcionais e não funcionais, rastreabilidade |
| [04 — Arquitetura](docs/04-arquitetura.md) | C4 (contexto, containers, componentes), implantação, sequências, camadas |
| [05 — API](docs/05-api.md) | Contrato dos endpoints, autenticação, erros, paginação |
| [06 — Dados](docs/06-dados.md) | Modelo físico, índices, migrações, separação dos dados pessoais |
| [07 — Segurança e LGPD](docs/07-seguranca-lgpd.md) | Ameaças (STRIDE), controles, OWASP, LGPD |
| [08 — CI/CD e infraestrutura](docs/08-ci-cd-infra.md) | kind, Terraform, manifestos, pipelines, governança Git, runner, rollback |
| [09 — Testes](docs/09-testes.md) | Estratégia, níveis, cenários BDD |
| [10 — Plano de execução](docs/10-plano-execucao.md) | Backlog, DoR/DoD, cronograma, riscos |
| [11 — Roteiro do vídeo](docs/11-roteiro-video.md) | Roteiro da demonstração em vídeo e checklist de preparação |
| [12 — Observabilidade](docs/12-observabilidade.md) | Logs, métricas, Prometheus e Grafana no cluster, painel, golden signals, SLIs/SLOs, alertas ativos e APM |
| [13 — Design Approval Sheet](docs/13-das.md) | Folha de aprovação do desenho: escopo, decisões, qualidade, riscos, custos |
| [infra/README.md](infra/README.md) | Detalhes da plataforma (kind, Terraform, Kong, Prometheus/Grafana, runner) |
| [k8s/README.md](k8s/README.md) | Manifestos da aplicação e contrato com o CD |
| [Repositório de identidade](https://github.com/Caina-Climaco/fiap-soat-revenda-identidade) | Configuração do realm (`README.md`) e contrato publicado para a API (`docs/contrato-identidade.md`) |

| ADR | Decisão |
|---|---|
| [ADR-001](docs/adrs/ADR-001-keycloak-identidade.md) | Keycloak como provedor de identidade apartado |
| [ADR-002](docs/adrs/ADR-002-monolito-modular.md) | Monólito modular para Catálogo e Vendas |
| [ADR-003](docs/adrs/ADR-003-stack-python-fastapi.md) | Stack Python 3.12, FastAPI, SQLAlchemy 2, Alembic e PyJWT |
| [ADR-004](docs/adrs/ADR-004-postgresql-schemas.md) | PostgreSQL com schemas por módulo e instância separada para identidade |
| [ADR-005](docs/adrs/ADR-005-kind-terraform-nodeport.md) | Kubernetes local (kind via CLI) com plataforma provisionada por Terraform, NodePort sem Ingress |
| [ADR-006](docs/adrs/ADR-006-ci-hospedado-cd-self-hosted.md) | CI no runner hospedado e CD em runner self-hosted |
| [ADR-007](docs/adrs/ADR-007-pagamento-webhook.md) | Pagamento simulado por webhook com segredo compartilhado |
| [ADR-008](docs/adrs/ADR-008-concorrencia-update-condicional.md) | Concorrência por UPDATE condicional e índice único parcial |
| [ADR-009](docs/adrs/ADR-009-expiracao-preguicosa.md) | Reserva com expiração preguiçosa |
| [ADR-010](docs/adrs/ADR-010-kind-load-sem-registry.md) | Imagem carregada no kind sem registry, tag = SHA |
| [ADR-011](docs/adrs/ADR-011-segredos-terraform.md) | Segredos gerados pelo Terraform, nada sensível versionado |
| [ADR-012](docs/adrs/ADR-012-observabilidade-prometheus.md) | Métricas Prometheus nativas na API, APM como evolução (complementado por ADR-016) |
| [ADR-013](docs/adrs/ADR-013-sem-api-gateway-e-serverless.md) | Sem API Gateway e sem Serverless nesta entrega (parte de API Gateway substituída por ADR-015; Serverless continua como evolução) |
| [ADR-014](docs/adrs/ADR-014-identidade-em-repositorio-proprio.md) | Serviço de identidade em repositório próprio, com pipeline, Terraform e state separados |
| [ADR-015](docs/adrs/ADR-015-api-gateway-kong.md) | API Gateway Kong (DB-less) como única entrada HTTP da API |
| [ADR-016](docs/adrs/ADR-016-prometheus-grafana.md) | Prometheus e Grafana no cluster, com alertas versionados e testados |

---

## 3. Como usar localmente

O serviço de identidade é **pré-requisito** da API e vem do [repositório de identidade](https://github.com/Caina-Climaco/fiap-soat-revenda-identidade). Clone os dois repositórios lado a lado:

```bash
git clone https://github.com/Caina-Climaco/fiap-soat-revenda-identidade.git
git clone https://github.com/Caina-Climaco/fiap-soat-revenda-veiculos.git
```

Há duas formas de rodar. As duas publicam a API em `http://localhost:8080` e o Keycloak em `http://localhost:8180`, portanto **não rode as duas ao mesmo tempo**. Só a opção B tem o API Gateway (Kong) na frente da API e o Prometheus/Grafana; no compose, a porta 8080 é a própria API.

| | Opção A — docker compose | Opção B — ambiente completo (kind) |
|---|---|---|
| Para quê | Desenvolvimento rápido | Mesmo ambiente do CD |
| Requer | Docker | Windows, Docker Desktop, kind, Terraform, kubectl, gh |
| Ordem | compose da identidade → compose da API | identidade (script 04 ou CD de lá) → script 04 daqui → CD da API |
| Segredos | Você define nos dois `.env` | Gerados pelo Terraform de cada repositório, lidos com `kubectl` |

### 3.1 Opção A — docker compose (desenvolvimento)

Primeiro o serviço de identidade, no repositório dele (detalhes no `README.md` de lá):

```bash
cd fiap-soat-revenda-identidade
cp .env.example .env      # troque os valores; GESTOR_PASSWORD é a senha do gestor.loja
docker compose up -d      # Keycloak em http://localhost:8180, realm revenda importado
```

Depois a API, neste repositório:

```bash
cd fiap-soat-revenda-veiculos
cp .env.example .env      # PowerShell: Copy-Item .env.example .env
# edite o .env e troque todos os valores "troque-..." (o .env é ignorado pelo Git)
docker compose up -d --build
docker compose ps         # aguarde a api como "healthy"
```

O compose da API sobe só o banco da API, o Job de migração (`alembic upgrade head`) e a API; não há Keycloak nele. A API valida o `iss` `http://localhost:8180/realms/revenda` e busca as chaves (JWKS) do Keycloak pelo host, em `http://host.docker.internal:8180` (o compose declara `host.docker.internal` via `host-gateway`, para funcionar também no Linux). Para recomeçar do zero, `docker compose down -v` em cada repositório.

| Serviço | URL |
|---|---|
| API | http://localhost:8080 |
| Swagger UI | http://localhost:8080/docs |
| Métricas Prometheus (só no compose, sem gateway) | http://localhost:8080/metrics |
| PostgreSQL da API | `localhost:5432` (usuário `DB_USER`, senha `DB_PASSWORD` do `.env`) |
| Keycloak e conta do cliente (repositório de identidade) | http://localhost:8180, http://localhost:8180/realms/revenda/account |

Token: pelo Swagger (passo a passo na [seção 3.3](#33-passo-a-passo-de-uso-pelo-swagger)) ou, para scripts, pelo client `revenda-e2e` (password grant, só local). Exemplo com o gestor, em bash:

```bash
GESTOR_PASSWORD='<valor de GESTOR_PASSWORD no .env do repositório de identidade>'
TOKEN=$(curl -s http://localhost:8180/realms/revenda/protocol/openid-connect/token \
  -d grant_type=password -d client_id=revenda-e2e -d username=gestor.loja \
  --data-urlencode "password=$GESTOR_PASSWORD" | jq -r .access_token)
curl -s http://localhost:8080/api/v1/vendas -H "Authorization: Bearer $TOKEN"
```

### 3.2 Opção B — ambiente completo no Windows (igual ao CD)

**Pré-requisitos**: Windows 10/11, Docker Desktop (com o `kubectl` que ele instala), kind, Terraform, gh (autenticado com `gh auth login`) e git. O script 01 instala kind, Terraform e Helm via winget. Portas livres: 8080, 8180, 3000, 9090 e 15432.

**Ordem para subir tudo do zero:**

1. **Identidade** — no repositório de identidade, `scripts\windows\04-subir-ambiente.ps1` (ou o CD de lá): cria o cluster kind `revenda`, se faltar, e implanta o namespace `identidade` (Keycloak, banco, segredos, realm). Veja o `README.md` daquele repositório.
2. **Infraestrutura da API** — neste repositório, `scripts\windows\04-subir-ambiente.ps1`: namespace `revenda`, segredos, `revenda-db`, metrics-server, API Gateway Kong (namespace `gateway`) e Prometheus/Grafana (namespace `observabilidade`). O script **exige** o realm respondendo em `http://localhost:8180` e falha com uma mensagem clara se a identidade não estiver no ar.
3. **API** — pelo CD deste repositório (merge na `main` ou disparo manual).

Rode os scripts na raiz deste repositório, em PowerShell normal (sem administrador), um por vez:

| # | Script | O que faz | Quando |
|---|---|---|---|
| 00 | `scripts\windows\00-verificar-ambiente.ps1` | Relatório de ferramentas, versões, Docker, clusters kind, `gh auth` e portas em uso (`.setup\relatorio-ambiente.txt`) | Sempre, para conferir |
| 01 | `scripts\windows\01-instalar-ferramentas.ps1` | Instala o que falta (kind, Terraform, Helm) e inicia o Docker Desktop | Primeira vez |
| 02 | `scripts\windows\02-criar-repositorio.ps1` | Cria o repositório no GitHub, faz o push, aplica a proteção da `main` (4 checks, PR obrigatório, squash, histórico linear), aprovação para workflows de forks e o environment `local` | Uma vez, pelo dono do repositório (num fork: `-Dono <seu-usuario>`) |
| 03 | `scripts\windows\03-instalar-runner.ps1` | Constrói a imagem do runner (`infra/runner`) e sobe o container `revenda-runner` na rede `kind`, registrado **neste** repositório com a label `kind-local`; `-Remover` desfaz. A identidade tem o próprio runner (`revenda-runner-identidade`), instalado pelo script 03 de lá | Uma vez, depois do 04 (precisa do cluster e da rede `kind`) |
| 04 | `scripts\windows\04-subir-ambiente.ps1` | Cria o cluster kind (se faltar), exige o realm `revenda` em `localhost:8180` e roda `terraform init` + `apply` com o mesmo state do CD (`%USERPROFILE%\.revenda\revenda-api.tfstate`); mostra pods, URLs e como ler os segredos. `-SemBancoExposto` não publica o banco em 15432. Avisa se ainda existir o state antigo `terraform.tfstate` ([seção 8](#8-migração-para-dois-repositórios)) | Para subir a infraestrutura da API |
| 05 | `scripts\windows\05-destruir-ambiente.ps1` | `terraform destroy` só do que é da API (namespace `revenda`) e remoção do state dela; a identidade não é tocada. `-ApagarCluster` também apaga o cluster kind inteiro (derruba a identidade junto). Pede confirmação; `-Forcar` não pede | Para apagar a API |

Exemplo: `powershell -ExecutionPolicy Bypass -File .\scripts\windows\04-subir-ambiente.ps1`.

Ordem na primeira vez, neste repositório: **00 → 01 → 02 → (identidade no ar) → 04 → 03**, e então implantar a aplicação. O script 04 sobe a infraestrutura da API; a **API vem do CD**: faça merge de um PR na `main` ou dispare o workflow manualmente:

```powershell
gh workflow run cd.yml -R Caina-Climaco/fiap-soat-revenda-veiculos
gh run watch -R Caina-Climaco/fiap-soat-revenda-veiculos
```

<details>
<summary>Sem runner (por exemplo, num clone sem acesso de administrador ao repositório): os mesmos passos do CD, à mão</summary>

Depois do script 04, na raiz do repositório (PowerShell):

```powershell
$sha = git rev-parse HEAD
docker build -t "revenda-api:$sha" .
kind load docker-image "revenda-api:$sha" --name revenda

kubectl -n revenda delete job revenda-migracao --ignore-not-found --wait=true
(kubectl kustomize k8s/migracao) -replace 'revenda-api:dev', "revenda-api:$sha" | kubectl apply -n revenda -f -
kubectl -n revenda wait --for=condition=complete --timeout=300s job/revenda-migracao

(kubectl kustomize k8s/base) -replace 'revenda-api:dev', "revenda-api:$sha" | kubectl apply -f -
kubectl -n revenda rollout status deployment/revenda-api --timeout=180s
```

</details>

**Segredos.** Todos são gerados pelo Terraform (`random_password`) e ficam apenas no state local e em Secrets do cluster; nenhum está no repositório. Os do namespace `revenda` são deste repositório; os do namespace `identidade` são do repositório de identidade, e a API usa deles só os **Secrets de contrato** abaixo (o admin do realm `master` nunca sai daquele repositório).

| Secret (namespace/nome) | Chaves | Para quê | Repositório |
|---|---|---|---|
| `revenda/revenda-webhook-secret` | `WEBHOOK_SECRET` | Header `X-Webhook-Secret` do gateway simulado (o mesmo valor é a credencial do consumer `gateway-pagamento` no Kong, Secret `gateway/kong-config`) | este |
| `observabilidade/grafana-admin` | `GF_SECURITY_ADMIN_USER`, `GF_SECURITY_ADMIN_PASSWORD` | Admin do Grafana (a leitura do painel é anônima) | este |
| `revenda/revenda-db-credentials` | `DB_USER`, `DB_PASSWORD`, `DB_NAME` | Banco da API (`revenda`/`revenda`) | este |
| `identidade/keycloak-gestor` | `GESTOR_PASSWORD` | Senha do usuário `gestor.loja` (login e e2e) | identidade |
| `identidade/keycloak-e2e` | `E2E_ADMIN_CLIENT_ID`, `E2E_ADMIN_CLIENT_SECRET` | Client técnico `revenda-e2e-admin` dos testes e2e (só gerencia usuários do realm `revenda`) | identidade |

PowerShell:

```powershell
function Segredo([string]$ns, [string]$nome, [string]$chave) {
  $b64 = kubectl -n $ns get secret $nome -o "jsonpath={.data.$chave}"
  [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($b64))
}
Segredo identidade keycloak-gestor GESTOR_PASSWORD
Segredo identidade keycloak-e2e E2E_ADMIN_CLIENT_SECRET
Segredo revenda revenda-webhook-secret WEBHOOK_SECRET
Segredo revenda revenda-db-credentials DB_PASSWORD
Segredo observabilidade grafana-admin GF_SECURITY_ADMIN_PASSWORD
# copiar sem mostrar na tela: Segredo revenda revenda-webhook-secret WEBHOOK_SECRET | Set-Clipboard
```

bash (Git Bash ou Linux):

```bash
segredo() { kubectl -n "$1" get secret "$2" -o jsonpath="{.data.$3}" | base64 -d; }
segredo identidade keycloak-gestor GESTOR_PASSWORD
segredo identidade keycloak-e2e E2E_ADMIN_CLIENT_SECRET
segredo revenda revenda-webhook-secret WEBHOOK_SECRET
segredo revenda revenda-db-credentials DB_PASSWORD
segredo observabilidade grafana-admin GF_SECURITY_ADMIN_PASSWORD
```

**URLs** (todas só em `127.0.0.1`):

| Serviço | Endereço |
|---|---|
| API, pelo API Gateway (Kong) | http://localhost:8080 |
| Swagger UI | http://localhost:8080/docs (OpenAPI em `/openapi.json`) |
| Grafana (painel "Revenda de Veículos — visão geral") | http://localhost:3000 (leitura anônima; admin `admin` com a senha do Secret `observabilidade/grafana-admin`) |
| Prometheus (consultas e alertas) | http://localhost:9090 (alertas em http://localhost:9090/alerts) |
| Keycloak (repositório de identidade) | http://localhost:8180 |
| Conta do cliente (dados do titular) | http://localhost:8180/realms/revenda/account |
| Banco da API (demonstração) | `localhost:15432`, usuário `revenda`, banco `revenda`, senha `DB_PASSWORD`; por exemplo `psql -h localhost -p 15432 -U revenda -d revenda`, ou sem psql instalado: `kubectl -n revenda exec -it statefulset/revenda-db -- psql -U revenda -d revenda` |

`http://localhost:8080/metrics` responde 404 (do Kong): as métricas da API só são lidas dentro do cluster. Para ver o texto bruto de uma réplica: `kubectl -n revenda port-forward deploy/revenda-api 8000:8000` e `curl -s http://localhost:8000/metrics`.

Outros comandos úteis: `kubectl get pods -A`, `kubectl -n revenda get hpa revenda-api`, `kubectl -n gateway logs deployment/kong`. O console admin do Keycloak e os logs dele estão documentados no repositório de identidade.

### 3.3 Passo a passo de uso pelo Swagger

Vale para as duas opções. Use `http://localhost:8080/docs`.

Dica: o Keycloak mantém a sessão no navegador. Para alternar entre gestor e cliente, use janelas separadas (uma normal, outra anônima, ou outro navegador) ou, na mesma janela, clique em *Logout* no diálogo *Authorize* e saia da sessão do Keycloak em http://localhost:8180/realms/revenda/account.

1. **Login do gestor.** Clique em **Authorize**. Na seção `keycloak (OAuth2, authorizationCode with PKCE)`, o `client_id` já vem como `revenda-swagger` e o `client_secret` fica vazio; marque o escopo `openid` e clique em **Authorize**. Na tela do Keycloak entre com `gestor.loja` (ou `gestor@revenda.local`) e a senha `GESTOR_PASSWORD`. De volta ao Swagger, feche o diálogo.
2. **Cadastrar veículos.** `POST /api/v1/veiculos` > *Try it out*, corpo:
   ```json
   { "marca": "Fiat", "modelo": "Argo Drive 1.3", "ano": 2023, "cor": "Vermelho", "preco": "79900.00" }
   ```
   Resposta 201 com `id`, `status: "A_VENDA"` e `versao: 1`. Cadastre mais alguns (por exemplo, `"Volkswagen"`/`"Gol 1.0 MPI"`/`2021`/`"Branco"`/`"54900.00"` e `"Toyota"`/`"Corolla XEi 2.0"`/`2022`/`"Prata"`/`"124900.00"`). O preço é texto decimal com duas casas.
3. **Editar.** `PATCH /api/v1/veiculos/{veiculo_id}` com `{ "preco": "52900.00" }`: resposta 200 com `versao: 2`.
4. **Cliente se cadastra.** Em outra janela (anônima), abra o Swagger, clique em **Authorize** e, na tela de login do Keycloak, use o link de cadastro (*Register*). Preencha usuário, e-mail, nome, sobrenome, **CPF** (11 dígitos, sem pontos), telefone (opcional, 10 ou 11 dígitos) e senha. Ao concluir, o Keycloak devolve para o Swagger já autenticado; o novo usuário recebe o papel `cliente`.
5. **Listar à venda.** `GET /api/v1/veiculos/a-venda` (público): itens do mais barato ao mais caro, com `total`, `limite` e `deslocamento`.
6. **Comprar.** Como cliente, `POST /api/v1/vendas` com `{ "veiculo_id": "<id do veículo>" }`: resposta 201 com `status: "AGUARDANDO_PAGAMENTO"`, `codigo_pagamento` (`PAG-...`), `preco_venda` e `expira_em`. O veículo sai da lista à venda. Uma segunda compra do mesmo veículo, por outro cliente, recebe 409 `veiculo-indisponivel`; o gestor tentando comprar recebe 403.
7. **Simular o gateway.** Clique em **Authorize**, na seção `webhook (apiKey)` informe o valor de `WEBHOOK_SECRET` e confirme (o Swagger passa a enviar o header `X-Webhook-Secret`). Em `POST /api/v1/pagamentos/webhook`:
   ```json
   { "codigo_pagamento": "PAG-xxxxxxxxxxxx", "status": "APROVADO" }
   ```
   Resposta 200 com `status: "EFETIVADA"` e `efetivada_em`. Com `"RECUSADO"` a venda seria cancelada e o veículo voltaria à vitrine. Sem o segredo correto: 401 (na opção B, quem recusa é o próprio Kong, antes de chegar à API).
8. **Listar vendidos.** `GET /api/v1/veiculos/vendidos`: o veículo aparece com `status: "VENDIDO"`, em ordem de preço.
9. **Minhas compras.** Como cliente, `GET /api/v1/vendas/minhas`: a venda aparece `EFETIVADA`. O gestor vê todas as vendas, com `comprador_id`, em `GET /api/v1/vendas` (filtro opcional `?status=`).

<details>
<summary>O mesmo fluxo com curl (bash, requer curl e jq)</summary>

Funciona com as duas opções. Na opção A, use os valores do `.env` dos dois repositórios em vez de `kubectl` (`E2E_ADMIN_CLIENT_SECRET` está no `.env` do repositório de identidade). O cliente é criado pela Admin API do Keycloak com o client técnico `revenda-e2e-admin`, como fazem os testes e2e (equivale ao autocadastro: recebe o papel `cliente`).

```bash
API=http://localhost:8080
KC=http://localhost:8180
segredo() { kubectl -n "$1" get secret "$2" -o jsonpath="{.data.$3}" | base64 -d; }
GESTOR_PASSWORD=$(segredo identidade keycloak-gestor GESTOR_PASSWORD)
WEBHOOK_SECRET=$(segredo revenda revenda-webhook-secret WEBHOOK_SECRET)
KC_CLIENT_ID=$(segredo identidade keycloak-e2e E2E_ADMIN_CLIENT_ID)          # revenda-e2e-admin
KC_CLIENT_SECRET=$(segredo identidade keycloak-e2e E2E_ADMIN_CLIENT_SECRET)

token() {  # token(usuario, senha) pelo client revenda-e2e (somente ambiente local)
  curl -s "$KC/realms/revenda/protocol/openid-connect/token" \
    -d grant_type=password -d client_id=revenda-e2e \
    -d "username=$1" --data-urlencode "password=$2" | jq -r .access_token
}

# 1. Gestor cadastra e edita um veículo
TG=$(token gestor.loja "$GESTOR_PASSWORD")
VEICULO=$(curl -s -X POST "$API/api/v1/veiculos" -H "Authorization: Bearer $TG" \
  -H "Content-Type: application/json" \
  -d '{"marca":"Fiat","modelo":"Argo Drive 1.3","ano":2023,"cor":"Vermelho","preco":"79900.00"}' | jq -r .id)
curl -s -X PATCH "$API/api/v1/veiculos/$VEICULO" -H "Authorization: Bearer $TG" \
  -H "Content-Type: application/json" -d '{"preco":"77900.00"}' | jq

# 2. Cliente: cadastro pela Admin API do Keycloak (ou pela tela de registro), com o token
#    do client técnico revenda-e2e-admin (client credentials no realm revenda; só gerencia usuários)
#    Dados fictícios: o CPF 12345678901 tem só o formato válido (11 dígitos), não os dígitos verificadores
TA=$(curl -s "$KC/realms/revenda/protocol/openid-connect/token" \
  -d grant_type=client_credentials -d "client_id=$KC_CLIENT_ID" \
  --data-urlencode "client_secret=$KC_CLIENT_SECRET" | jq -r .access_token)
curl -s -o /dev/null -w "cadastro: %{http_code}\n" -X POST "$KC/admin/realms/revenda/users" \
  -H "Authorization: Bearer $TA" -H "Content-Type: application/json" \
  -d '{"username":"maria.silva","email":"maria@example.com","emailVerified":true,"enabled":true,
       "firstName":"Maria","lastName":"Silva","attributes":{"cpf":["12345678901"]},
       "credentials":[{"type":"password","value":"Senha-Forte-123","temporary":false}]}'
TC=$(token maria.silva 'Senha-Forte-123')

# 3. Vitrine (pública), compra e efetivação
curl -s "$API/api/v1/veiculos/a-venda" | jq '.itens[] | {marca, modelo, preco}'
CODIGO=$(curl -s -X POST "$API/api/v1/vendas" -H "Authorization: Bearer $TC" \
  -H "Content-Type: application/json" -d "{\"veiculo_id\":\"$VEICULO\"}" | tee /dev/stderr | jq -r .codigo_pagamento)
curl -s -X POST "$API/api/v1/pagamentos/webhook" -H "X-Webhook-Secret: $WEBHOOK_SECRET" \
  -H "Content-Type: application/json" -d "{\"codigo_pagamento\":\"$CODIGO\",\"status\":\"APROVADO\"}" | jq

# 4. Vendidos (público) e minhas compras
curl -s "$API/api/v1/veiculos/vendidos" | jq '.itens[] | {marca, modelo, preco, status}'
curl -s "$API/api/v1/vendas/minhas" -H "Authorization: Bearer $TC" | jq '.itens[] | {status, codigo_pagamento, preco_venda}'
```

O access token do realm vale 5 minutos (`accessTokenLifespan` = 300 s); se um comando responder 401, gere o token de novo.

</details>

---

## 4. Como testar

Pré-requisitos: [uv](https://docs.astral.sh/uv/) (instala o Python 3.12 do `.python-version`) e Docker.

```bash
uv sync --frozen        # dependências da aplicação e de desenvolvimento, pelo uv.lock
```

### 4.1 Unidade e integração

Os testes de unidade não usam banco nem rede. Os de integração precisam de um PostgreSQL real, indicado por `TEST_DATABASE_URL`; sem a variável, eles são pulados com aviso. O docker compose cria o banco `revenda_test` na primeira subida do serviço `postgres` (requer o `.env` da [opção A](#31-opção-a--docker-compose-desenvolvimento)):

```bash
docker compose up -d postgres
export TEST_DATABASE_URL="postgresql+psycopg://revenda:<DB_PASSWORD do .env>@localhost:5432/revenda_test"
# PowerShell: $env:TEST_DATABASE_URL = "postgresql+psycopg://revenda:<DB_PASSWORD do .env>@localhost:5432/revenda_test"

uv run pytest -m unit           # só unidade
uv run pytest -m integration    # só integração
uv run pytest                   # unidade + integração (o e2e fica fora por padrão)
```

Cobertura com o mesmo critério do CI:

```bash
uv run pytest -m "unit or integration" --cov=revenda --cov-branch \
  --cov-report=term-missing --cov-report=xml --cov-fail-under=80
```

### 4.2 Lint, tipos e regras de arquitetura

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run lint-imports      # camadas por módulo, independência Catálogo x Vendas, domínio sem frameworks
```

### 4.3 Ponta a ponta (e2e) contra o ambiente implantado

Os testes em `tests/e2e` exercitam o fluxo completo contra a API e o Keycloak reais (este implantado pelo repositório de identidade): criam clientes pela Admin API do realm `revenda` com o client técnico `revenda-e2e-admin` (client credentials; nunca o admin do realm `master`), obtêm tokens pelo client `revenda-e2e`, compram, efetivam, testam 401/403/404/409, conferem o API Gateway (cabeçalhos de *rate limiting*, `X-Request-ID`, limite próprio da compra, `/metrics` fechado na borda, webhook barrado ou encaminhado pelo Kong) e removem os usuários de teste ao final. São **23 testes** coletados. Os veículos que criam (modelos com "E2E") ficam no catálogo. Variáveis:

| Variável | Obrigatória | Valor |
|---|---|---|
| `E2E_API_URL` | não | Padrão `http://localhost:8080` |
| `E2E_KEYCLOAK_URL` | não | Padrão `http://localhost:8180` |
| `E2E_GESTOR_PASSWORD` | sim | `identidade/keycloak-gestor` → `GESTOR_PASSWORD` |
| `E2E_WEBHOOK_SECRET` | sim | `revenda/revenda-webhook-secret` → `WEBHOOK_SECRET` |
| `E2E_KC_CLIENT_SECRET` | sim | `identidade/keycloak-e2e` → `E2E_ADMIN_CLIENT_SECRET` |
| `E2E_KC_CLIENT_ID` | não | Padrão `revenda-e2e-admin` (`identidade/keycloak-e2e` → `E2E_ADMIN_CLIENT_ID`) |
| `E2E_EXIGIR` | não | `1` transforma variável ausente em erro (usado no CD); sem ela, os testes são pulados |
| `E2E_GATEWAY` | não | `1` exige que a API esteja atrás do Kong (usado no CD); sem ela, o gateway é detectado pelo cabeçalho `Via` e, no compose (sem Kong), os 5 testes de `test_e2e_gateway.py` são pulados |

bash:

```bash
segredo() { kubectl -n "$1" get secret "$2" -o jsonpath="{.data.$3}" | base64 -d; }
export E2E_GESTOR_PASSWORD="$(segredo identidade keycloak-gestor GESTOR_PASSWORD)"
export E2E_WEBHOOK_SECRET="$(segredo revenda revenda-webhook-secret WEBHOOK_SECRET)"
export E2E_KC_CLIENT_SECRET="$(segredo identidade keycloak-e2e E2E_ADMIN_CLIENT_SECRET)"
uv run pytest tests/e2e -m e2e -p no:cacheprovider -o addopts="" -v
```

PowerShell (com a função `Segredo` da [seção 3.2](#32-opção-b--ambiente-completo-no-windows-igual-ao-cd)):

```powershell
$env:E2E_GESTOR_PASSWORD   = Segredo identidade keycloak-gestor GESTOR_PASSWORD
$env:E2E_WEBHOOK_SECRET    = Segredo revenda revenda-webhook-secret WEBHOOK_SECRET
$env:E2E_KC_CLIENT_SECRET  = Segredo identidade keycloak-e2e E2E_ADMIN_CLIENT_SECRET
uv run pytest tests/e2e -m e2e -p no:cacheprovider -o addopts="" -v
```

O `tests/e2e/pytest.ini` isola o e2e da configuração do `pyproject.toml`; o e2e depende apenas de `pytest` e `httpx` (`tests/e2e/requirements.txt`) e não importa o pacote `revenda`. Na opção A, o mesmo comando funciona com os valores do `.env` do repositório de identidade (`E2E_GESTOR_PASSWORD` = `GESTOR_PASSWORD`, `E2E_KC_CLIENT_SECRET` = `E2E_ADMIN_CLIENT_SECRET`) e do `.env` deste (`E2E_WEBHOOK_SECRET` = `WEBHOOK_SECRET`).

### 4.4 Carga (k6) e métricas

O teste de carga `tests/carga/listagens.js` usa o [k6](https://grafana.com/docs/k6/latest/): 20 usuários virtuais por 1 minuto nas listagens públicas, com os *thresholds* p95 < 300 ms e erro < 1% (RNF-10). Com a API de pé (opção A ou B):

```bash
k6 run tests/carga/listagens.js
kubectl -n revenda get hpa revenda-api -w      # em outro terminal (opção B), para ver o HPA
```

Durante a carga, acompanhe o painel do Grafana em http://localhost:3000 (tráfego, p95 por rota, réplicas) e os alertas em http://localhost:9090/alerts (opção B). **Atenção**: com 20 usuários virtuais, o k6 faz milhares de requisições por minuto de um único IP, bem acima do limite de 600 req/min da rota `/api/v1` no Kong; pelo gateway, a maior parte vira 429 e o *threshold* de erro < 1% falha. Para medir a API, rode o teste com o limite elevado (no PowerShell, `$env:TF_VAR_kong_limite_geral_minuto = "100000"` e rode de novo o script 04; o próximo CD, ou o 04 sem a variável, volta ao padrão); ou rode contra o compose (opção A), que não tem gateway. No compose (opção A), as métricas brutas estão em `curl -s http://localhost:8080/metrics | grep '^revenda_'`.

`GET /metrics` expõe, no formato Prometheus, a latência e o volume por rota e status e os contadores de negócio (vendas iniciadas, efetivadas e canceladas por motivo; veículos cadastrados). Golden signals, SLOs, painel e alertas estão em [docs/12](docs/12-observabilidade.md).

### 4.5 O que o CI e o CD rodam

| Pipeline | Testes e verificações |
|---|---|
| CI, job `qualidade` | `ruff check`, `ruff format --check`, `mypy src`, `lint-imports` |
| CI, job `testes` | `pytest -m "unit or integration"` com cobertura de ramos e `--cov-fail-under=80`, contra o *service container* `postgres:16.15-alpine`; publica o `coverage.xml` como artefato |
| CI, job `imagem` | Build da imagem; Trivy na imagem (CRITICAL/HIGH corrigíveis) e varredura de segredos no repositório |
| CI, job `infra` | `terraform fmt -check`, `terraform validate`, kubeconform em `k8s/base` e `k8s/migracao`, `kong config parse` da configuração do Kong (renderizada com valores de teste), `promtool check config`/`check rules`/`test rules` e validação do JSON do painel com `jq`, validação do `infra/kind/cluster.yaml` (incluindo as portas 3000 e 9090), hadolint e shellcheck do runner (o realm é validado no CI do repositório de identidade, job `realm`) |
| CD, job `deploy` | Antes de tudo, confere o discovery do realm `revenda` (pré-requisito); após o rollout, espera `/health/ready` pelo Kong; etapa **Monitoramento**: alvos `up` dos jobs `revenda-api` e `kong` no Prometheus, 3 grupos de regras carregados e painel `revenda-visao-geral` no Grafana; roda `pytest tests/e2e -m e2e` com `E2E_EXIGIR=1` e `E2E_GATEWAY=1`; o resultado e a contagem de testes vão para o job summary |

### 4.6 Cobertura

O CI exige no mínimo **80%** de cobertura (linhas e ramos) em `src/revenda`. Com os testes de integração habilitados, a suíte local atinge cerca de **99%**. A estratégia completa, com os cenários BDD, está em [docs/09](docs/09-testes.md).

---

## 5. Fluxo de contribuição

1. Crie a mudança numa branch de vida curta: `feat/*`, `fix/*`, `docs/*` ou `infra/*`.
2. Abra o PR com o script, que cria a branch a partir da `origin/main` levando as mudanças não commitadas, faz commit, push e `gh pr create` com o template:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\windows\abrir-pr.ps1 `
     -Branch docs/ajuste-readme -Titulo "docs: ajustar README" -Acompanhar
   ```
   `-Acompanhar` segue os checks ao vivo; `-AutoMerge` faz squash merge automático quando os checks passarem.
3. O título do PR segue **Conventional Commits** (`tipo(escopo): descrição`; o script e o job `titulo-pr` validam). Ele vira a mensagem do commit na `main`.
4. A `main` só aceita **squash merge** de PR com os checks `qualidade`, `testes`, `imagem` e `infra` verdes e a branch atualizada; force push e exclusão são bloqueados, inclusive para administradores. Aprovações exigidas: zero, por ser trabalho individual (o GitHub não deixa o autor aprovar o próprio PR).
5. O merge dispara o CD, que implanta no kind e roda o e2e. Para investigar falhas de pipeline: `scripts\windows\diagnostico-ci.ps1`.

## 6. Estrutura de pastas

```text
.
├── src/revenda/
│   ├── shared/            # config, banco, autenticação (JWT/JWKS), erros problem+json, logs, saúde
│   ├── catalogo/          # domain, application, infrastructure, interfaces
│   ├── vendas/            # domain, application, infrastructure, interfaces (inclui o webhook)
│   ├── composicao.py      # ligação dos módulos (CatalogoPort)
│   └── main.py            # app FastAPI
├── migrations/            # Alembic
├── tests/
│   ├── unit/  integration/  e2e/  apoio/
│   └── carga/             # teste de carga k6 (listagens.js)
├── infra/
│   ├── kind/cluster.yaml  # cluster kind (CLI kind)
│   ├── terraform/         # namespaces revenda, gateway e observabilidade
│   ├── kong/              # configuração declarativa do Kong (template do Terraform)
│   ├── observabilidade/   # prometheus.yml, alertas.yml (+ testes) e Grafana (fonte, painel)
│   └── runner/            # imagem do runner self-hosted
├── k8s/
│   ├── base/              # Deployment, Service, HPA, ConfigMap
│   └── migracao/          # Job de migração
├── scripts/windows/       # 00 a 05, abrir-pr.ps1, diagnostico-ci.ps1
├── docs/                  # 01 a 13 e adrs/
├── .github/               # workflows ci.yml e cd.yml, template de PR, dependabot
├── docker-compose.yml, Dockerfile, .env.example
└── pyproject.toml, uv.lock, alembic.ini
```

## 7. Limitações conhecidas

- **Pagamento simulado**: não há integração com provedor real; o gateway é representado por chamadas ao webhook com segredo compartilhado (sem assinatura HMAC do corpo, sem estorno).
- **Dois repositórios, um cluster local**: identidade e API têm pipelines, Terraform e states separados, mas rodam no mesmo cluster kind e no mesmo PC; apagar o cluster (`-ApagarCluster`) derruba os dois. A API depende de a identidade estar no ar antes (o script 04 e o CD conferem).
- **Ambiente local sem TLS**: API e Keycloak respondem em HTTP, só em `127.0.0.1`.
- **Keycloak em `start-dev`**: adequado ao ambiente de demonstração, não a produção; os clients `revenda-e2e` (password grant) e `revenda-e2e-admin` (gestão de usuários para os testes) existem só localmente.
- **CPF sem unicidade garantida**: o Keycloak valida o formato, mas não impede o mesmo CPF em duas contas; o identificador único do cadastro é o e-mail.
- **State local do Terraform**: fica em `%USERPROFILE%\.revenda\revenda-api.tfstate` (o da identidade, em `identidade.tfstate`), sem backend remoto nem *locking*; contém os segredos em texto claro e por isso nunca vai para o repositório.
- **Uma réplica do Kong, *rate limiting* local**: o gateway é ponto único de entrada e os contadores de limite são por pod (`policy: local`); com mais réplicas, o limite efetivo se multiplica ([ADR-015](docs/adrs/ADR-015-api-gateway-kong.md)).
- **Monitoramento sem notificação nem histórico**: não há Alertmanager (os alertas só aparecem no Prometheus e no painel), as métricas ficam 2 dias em disco temporário e se perdem quando o pod reinicia; APM e traços distribuídos continuam como evolução ([ADR-016](docs/adrs/ADR-016-prometheus-grafana.md), [docs/12](docs/12-observabilidade.md)).
- **Sem Serverless**: o simulador do gateway de pagamento como função continua só documentado ([ADR-013](docs/adrs/ADR-013-sem-api-gateway-e-serverless.md)).
- **CD depende do PC ligado**: o runner self-hosted roda no PC do autor; com ele desligado, o deploy fica na fila até o runner voltar (ou é disparado de novo com *Run workflow*).

## 8. Migração para dois repositórios

Até esta mudança ([ADR-014](docs/adrs/ADR-014-identidade-em-repositorio-proprio.md)), este repositório implantava API e Keycloak com um único Terraform e um único state (`%USERPROFILE%\.revenda\terraform.tfstate`). Agora cada repositório tem o seu state (`revenda-api.tfstate` e `identidade.tfstate`), e o state antigo descreve recursos que passaram a ser de outro dono. Para migrar um ambiente criado antes da separação, recomece do zero (os dados dos bancos locais são perdidos):

1. Apague o cluster: `kind delete cluster --name revenda`.
2. Apague o state antigo e o diretório de dados do Terraform: `%USERPROFILE%\.revenda\terraform.tfstate`, `%USERPROFILE%\.revenda\terraform.tfstate.backup` e `%USERPROFILE%\.revenda\terraform-data`.
   ```powershell
   Remove-Item "$env:USERPROFILE\.revenda\terraform.tfstate*" -Force -ErrorAction SilentlyContinue
   Remove-Item "$env:USERPROFILE\.revenda\terraform-data" -Recurse -Force -ErrorAction SilentlyContinue
   ```
3. Suba a identidade: `scripts\windows\04-subir-ambiente.ps1` no repositório de identidade (ou o CD de lá).
4. Suba a API: `scripts\windows\04-subir-ambiente.ps1` neste repositório e depois o CD.
5. Instale o runner da identidade (`scripts\windows\03-instalar-runner.ps1` no repositório de identidade, container `revenda-runner-identidade`). O runner deste repositório (`revenda-runner`) continua o mesmo.

No modo docker compose, rode `docker compose down -v --remove-orphans` neste repositório (o `--remove-orphans` remove os containers do Keycloak e do banco dele que ficaram do compose anterior) e `docker volume rm revenda_keycloak-db` (volume antigo, que o compose atual não declara mais), apague do `.env` as variáveis `KC_*` e `GESTOR_PASSWORD` (agora no `.env` do repositório de identidade) e siga a [seção 3.1](#31-opção-a--docker-compose-desenvolvimento).

## 9. Migração para o API Gateway e o monitoramento

Com o API Gateway ([ADR-015](docs/adrs/ADR-015-api-gateway-kong.md)) e o monitoramento ([ADR-016](docs/adrs/ADR-016-prometheus-grafana.md)), o `infra/kind/cluster.yaml` ganhou as portas 3000 (Grafana) e 9090 (Prometheus). O arquivo é idêntico nos dois repositórios; o de identidade recebe a mesma mudança num PR próprio. O kind não acrescenta portas a um cluster existente, então quem já tem o cluster precisa recriá-lo (os dados dos bancos locais são perdidos):

1. Confira que as portas 3000 e 9090 do host estão livres.
2. Apague o cluster: `kind delete cluster --name revenda`.
3. Suba a identidade: `scripts\windows\04-subir-ambiente.ps1` no repositório de identidade (ou o CD de lá).
4. Suba a API: `scripts\windows\04-subir-ambiente.ps1` neste repositório e depois o CD (ou só o CD, que também cria o cluster e aplica o Terraform).

Sem recriar o cluster, as portas 3000 e 9090 não chegam ao host e o primeiro `terraform apply` falha ao criar o Service `kong`, porque o NodePort 30080 ainda pertence ao Service antigo da API (NodePort).

A porta 8080 não muda, mas agora é o Kong: `http://localhost:8080/metrics` passa a responder 404, e as métricas são vistas no Grafana (http://localhost:3000) e no Prometheus (http://localhost:9090).

## 10. Autor

**Cainã Clímaco** (RM366473) — FIAP PósTech Software Architecture (SOAT), Trabalho Substitutivo do Tech Challenge, Fase 3.
Repositório: https://github.com/Caina-Climaco/fiap-soat-revenda-veiculos
