# 07 — Segurança e LGPD

Este documento reúne o modelo de ameaças da solução, os controles de segurança adotados (e os que ficam como evolução), o mapeamento desses controles para o OWASP Top 10 e a análise de conformidade com a Lei Geral de Proteção de Dados Pessoais (Lei nº 13.709/2018, LGPD). Ele complementa a visão de arquitetura ([04-arquitetura.md](04-arquitetura.md)), o contrato de autenticação da API ([05-api.md](05-api.md)) e a separação física de dados ([06-dados.md](06-dados.md)).

> Escopo: ambiente acadêmico local (cluster kind no PC do autor). Onde um controle depende de infraestrutura de produção (TLS público, WAF, cofre de segredos), isso é indicado como evolução.

## 1. Ativos e fronteiras de confiança

| Ativo | Onde está | Impacto se comprometido |
|---|---|---|
| Dados pessoais dos clientes (nome, e-mail, CPF, telefone) | Banco `keycloak` | Alto: incidente de segurança com dados pessoais (LGPD, art. 48) |
| Credenciais de usuários (hash de senha) | Banco `keycloak` | Alto |
| Chave privada de assinatura dos tokens | Keycloak (banco `keycloak`) | Crítico: permitiria forjar qualquer token |
| Estado das vendas e do estoque | Banco `revenda` | Alto: venda dupla, venda sem pagamento |
| Segredo do webhook | Secrets `revenda-webhook-secret` (API) e `kong-config` (credencial do consumer `gateway-pagamento` no Kong, mesmo valor) | Alto: efetivação de vendas sem pagamento |
| Configuração do API Gateway | Secret `gateway/kong-config`, gerado pelo Terraform a partir de `infra/kong/kong.yml.tftpl` | Alto: abrir rotas internas (`/metrics`) ou remover limites e a credencial do webhook |
| Métricas e painel | Prometheus e Grafana (namespace `observabilidade`); admin do Grafana no Secret `grafana-admin` | Baixo/médio: contadores de negócio (volume de vendas), sem dados pessoais |
| Segredos do banco da API e do webhook | Secrets do namespace `revenda` e state `revenda-api.tfstate` (este repositório) | Crítico |
| Segredos do banco e do admin do Keycloak | Secrets do namespace `identidade` e state `identidade.tfstate` (repositório de identidade; fora do alcance do pipeline da API, exceto os Secrets de contrato `keycloak-gestor` e `keycloak-e2e`, lidos pelo e2e) | Crítico |
| Pipeline de CD e runner self-hosted | PC do autor | Crítico: execução de código arbitrário com acesso ao cluster |

Fronteiras de confiança: (1) internet/navegador → API Gateway (Kong) → API, e navegador → Keycloak; (2) gateway de pagamento externo → Kong → webhook; (3) namespace `revenda` ↔ namespace `identidade`; (4) GitHub → runners self-hosted; (5) repositório da API ↔ repositório de identidade, que só se comunicam pelo contrato publicado (OIDC/JWT e Secrets de contrato do ambiente local).

## 2. Modelo de ameaças (STRIDE por componente)

| Componente | S — Falsificação | T — Adulteração | R — Repúdio | I — Divulgação | D — Negação de serviço | E — Elevação de privilégio |
|---|---|---|---|---|---|---|
| **API Gateway (Kong)** | Parceiro de pagamento falso → key-auth + ACL no webhook (só o consumer `gateway-pagamento`) | Alteração de rotas ou limites → configuração declarativa versionada, revisada por PR, validada no CI (`kong config parse`); Admin API só em `127.0.0.1` e somente leitura (DB-less) | Requisição sem rastro → `X-Request-ID` gerado no Kong e repetido no log da API; log de acesso do Kong | Rotas internas expostas → só as rotas declaradas são encaminhadas; `/metrics` sem rota (404) | Inundação → *rate limiting* por IP (600/min em `/api/v1`, 60/min na compra), payload ≤ 1 MB; uma réplica é ponto único de falha (alerta `KongFora`) | Contornar o gateway → API ClusterIP + NetworkPolicy `revenda-api-somente-gateway` |
| **revenda-api (endpoints com JWT)** | Token forjado ou de outro emissor → assinatura RS256 via JWKS, `iss`, `aud`, `azp`, `exp` validados; `alg` fixo | Alteração de claims → assinatura; alteração de preço pelo cliente → preço vem do banco, não do corpo | Ações sem trilha → log estruturado com `sub`, `request_id`, eventos de domínio | Acesso a venda alheia (BOLA) → filtro por `comprador_id`; 404 para não dono; erros sem stack trace | Abuso das listagens → paginação com `limite` ≤ 100 e `deslocamento` ≤ 1.000.000; HPA; *rate limiting* no Kong ([ADR-015](adrs/ADR-015-api-gateway-kong.md)) | Cliente chamando rota de gestor → RBAC por `realm_access.roles` em cada rota |
| **Webhook de pagamento** | Chamador se passando pelo gateway → credencial key-auth no Kong e, de novo, `X-Webhook-Secret` comparado em tempo constante na API | Replay de notificação → idempotência por estado da venda; HMAC do corpo com timestamp como evolução | Gateway nega ter enviado → log do payload (sem segredo) e do `request_id` | Segredo exposto em log → header nunca é registrado | Inundação de chamadas → chamadas sem credencial barradas no Kong, sem chegar à API; *rate limiting* da rota `/api/v1`; alertas `RevendaWebhookRecusado` e `KongRejeicoesNaBorda` | Efetivar venda sem pagamento → só com segredo válido (no Kong e na API) |
| **Keycloak** | Senha fraca / força bruta → política de senha do realm e *brute force detection* habilitados | Alteração de papéis → console admin com senha gerada pelo Terraform do repositório de identidade, que nunca chega a este repositório nem ao seu pipeline | Logins não rastreados → eventos de login e de admin habilitados no realm | Vazamento de dados pessoais pelo token → access token só com `sub`, papéis e audiência (`profile` e `email` apenas opcionais nos clients) | Sobrecarga do login → fora do escopo local | Autocadastro obtendo `gestor` → papel padrão é apenas `cliente`; `gestor` só por admin |
| **PostgreSQL revenda** | Conexão de pod não autorizado → NetworkPolicy + credencial por Secret | SQL injection → SQLAlchemy com parâmetros vinculados, sem SQL concatenado | — | Leitura do banco → não contém dados pessoais (só pseudônimo); logs do SQLAlchemy sem valores de parâmetros (`hide_parameters`) | Esgotamento de conexões → pool limitado por réplica | Usuário da aplicação com DDL → evolução: separar papel de migração e de aplicação |
| **PostgreSQL keycloak** | Idem → NetworkPolicy só a partir do Keycloak | — | — | Exposição de dados pessoais → banco não exposto ao host; instância separada | — | API sem credencial para este banco |
| **CI/CD e runner self-hosted** | PR de fork executando no runner → CD só em `push` na `main`; fork PRs exigem aprovação | Alteração do pipeline sem revisão → `main` protegida, PR e CI obrigatórios | Deploy sem autoria → cada deploy vinculado a SHA e PR | Segredos no repositório → gerados pelo Terraform, `.gitignore`, varredura no CI | Deploys simultâneos → `concurrency: deploy-local` | Runner com admin no host → usuário dedicado sem sudo; um runner e um state por repositório, e o CD da API não implanta nem altera o Keycloak |
| **Imagem e dependências** | Imagem base adulterada → imagens oficiais com versão fixa | Dependência vulnerável → Trivy CRITICAL/HIGH no CI; lockfile | — | — | — | Container como root → `runAsNonRoot`, `readOnlyRootFilesystem`, sem capabilities |

## 3. Controles

### 3.1 Autenticação (OIDC) e validação do JWT

- Protocolo **OpenID Connect** com o Keycloak como provedor. Swagger UI e front-end usam **Authorization Code + PKCE (S256)** com client público, sem segredo no navegador. O client `revenda-e2e` (password grant) existe só para os testes automatizados no ambiente local e não deve existir em produção (o password grant é desaconselhado pelas boas práticas atuais de OAuth). Também só local, o client técnico `revenda-e2e-admin` (client credentials) permite aos testes criar e apagar compradores com apenas `manage-users`, `view-users` e `query-users` do realm `revenda`; os testes não usam o admin do realm `master`.
- A API é um *resource server*: não armazena senhas nem sessões. Cada requisição é autenticada pelo access token, validado localmente:
  1. **Assinatura RS256** com a chave pública do **JWKS** do realm, selecionada pelo `kid`. O algoritmo é fixado no código (lista permitida = `RS256`), o que elimina ataques de `alg: none` e de confusão RS256/HS256.
  2. **`iss`** igual ao emissor configurado (`http://localhost:8180/realms/revenda`).
  3. **`exp`** (e `nbf`/`iat`, se presentes) com tolerância de 30 s.
  4. **`aud`** contendo `revenda-api` e **`azp`** na lista de clients autorizados: um token emitido pelo mesmo realm para outra aplicação não é aceito.
- O JWKS é obtido pelo endereço interno do Service do Keycloak e mantido em cache, com recarga ao surgir um `kid` novo (rotação de chaves) limitada a uma por minuto, para que tokens com `kid` aleatório não virem um vetor de negação de serviço contra o Keycloak.
- Tempo de vida do access token: 5 minutos (padrão do Keycloak), o que limita a janela de uso de um token vazado.
- Conteúdo do access token: `sub`, `realm_access.roles`, `aud` (`revenda-api`), `azp` e as claims técnicas (`iss`, `exp`, `iat`). Nome e e-mail não são incluídos, porque os escopos `profile` e `email` são apenas opcionais nos clients `revenda-swagger` e `revenda-e2e`; CPF e telefone nunca são mapeados para o token. Essas regras são parte do contrato do realm, mantido e testado (contra um Keycloak real, no job `realm` do CI) no repositório [fiap-soat-revenda-identidade](https://github.com/Caina-Climaco/fiap-soat-revenda-identidade).

### 3.2 Autorização (RBAC) e controle por objeto

- Papéis de realm `cliente` e `gestor`, lidos de `realm_access.roles`. Cada rota declara o papel exigido (tabela em [05-api.md](05-api.md)); a verificação é feita na camada `interfaces`, antes de chamar o caso de uso.
- **Controle por objeto**: vendas são sempre filtradas pelo `comprador_id` do token quando o chamador é cliente; o não dono recebe 404 (não 403), para não confirmar a existência do recurso.
- O `comprador_id` vem exclusivamente do token, nunca do corpo da requisição.
- O autocadastro recebe apenas o papel padrão `cliente`; o papel `gestor` só é atribuído pelo administrador do realm.

### 3.3 Princípio do menor privilégio

| Onde | Aplicação |
|---|---|
| Tokens | Só as claims necessárias (`sub`, papéis, `aud`, `azp`); sem dados pessoais. Nos clients `revenda-swagger` e `revenda-e2e`, os escopos `profile` e `email` são apenas opcionais |
| Pods | `runAsNonRoot: true`, `runAsUser: 10001`, `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`, `readOnlyRootFilesystem: true` (com `emptyDir` em `/tmp`), `seccompProfile: RuntimeDefault`, `automountServiceAccountToken: false` |
| Rede | API Gateway como única entrada: o Service `revenda-api` é ClusterIP e a NetworkPolicy `revenda-api-somente-gateway` só aceita, na porta 8000, o Kong (ns `gateway`), o Prometheus (ns `observabilidade`) e o tráfego do nó (probes); o namespace `identidade` não alcança a API. NetworkPolicy: banco da API só aceita pods `app=revenda-api` e `app=revenda-migracao`; banco do Keycloak só aceita `app=keycloak` e nunca é exposto (política declarada no repositório de identidade). O banco da API é publicado em `127.0.0.1:15432` (NodePort 30432) apenas para a demonstração do vídeo, com `expor_banco_revenda = true` (padrão); `false` o torna ClusterIP |
| Credenciais | API sem credencial do banco do Keycloak e vice-versa; Secrets montados apenas nos pods que os usam; o state e o pipeline da API não contêm segredos da identidade; o e2e usa o client técnico `revenda-e2e-admin` em vez do admin do realm `master` |
| Monitoramento | Prometheus só com **Roles** de leitura de pods nos namespaces `revenda` e `gateway` (sem ClusterRole, não enxerga `identidade`); Grafana com leitura anônima apenas como Viewer, painel não editável pela interface e admin com senha gerada; Kong, Prometheus e Grafana não root, com raiz somente leitura e `capabilities.drop: [ALL]` |
| Pipelines | `permissions: contents: read` nos workflows; o runner self-hosted roda como usuário sem privilégio de administrador; cada repositório tem o próprio runner, que só aplica o próprio namespace com o próprio state |
| Banco | Evolução: papel `revenda_migracao` (DDL) separado de `revenda_app` (somente DML nos schemas `catalogo` e `vendas`) |

**Camadas da separação entre identidade e dados transacionais.** A separação exigida pelo enunciado ("totalmente apartado") é aplicada em todas as camadas, de modo que comprometer uma delas não dá acesso aos dados pessoais:

| Camada | API (Catálogo e Vendas) | Identidade (Keycloak) |
|---|---|---|
| Repositório e revisão | `fiap-soat-revenda-veiculos` | [fiap-soat-revenda-identidade](https://github.com/Caina-Climaco/fiap-soat-revenda-identidade) |
| Pipeline de CI/CD e runner | CI `qualidade`/`testes`/`imagem`/`infra`; CD no `revenda-runner` | CI `qualidade`/`realm`/`infra`; CD no `revenda-runner-identidade` |
| State do Terraform (com segredos) | `revenda-api.tfstate` | `identidade.tfstate` |
| Namespace Kubernetes | `revenda` (e `gateway`, `observabilidade`) | `identidade` |
| Banco PostgreSQL | `revenda-db` (sem dados pessoais) | `keycloak-db` (nome, e-mail, CPF, telefone, credenciais) |
| Credenciais | `revenda-db-credentials`, `revenda-webhook-secret`, `kong-config`, `grafana-admin` | `keycloak-db-credentials`, `keycloak-admin`, `keycloak-gestor`, `keycloak-e2e` |
| Ligação entre os dois | Só o contrato público: JWT validado pelo JWKS, `sub` como pseudônimo; no ambiente local, o e2e lê os Secrets de contrato `keycloak-gestor` e `keycloak-e2e` | |

Sobre o suporte a NetworkPolicy: o CNI padrão do kind (kindnet) passou a implementar NetworkPolicy a partir da versão 0.24. O projeto exige essa versão ou superior; o bloqueio é conferido manualmente pelo checklist de [infra/README.md](../infra/README.md#checklist-de-verificação-manual-no-pc) (um pod sem o rótulo esperado não alcança o banco nem a API). Se o CNI não aplicar as políticas, elas permanecem como declaração de intenção versionada.

### 3.4 Gestão de segredos

- Todos os segredos são **gerados pelo Terraform** com `random_password` e gravados como `kubernetes_secret` ([ADR-011](adrs/ADR-011-segredos-terraform.md)), cada um pelo repositório dono dele: senha do banco da API, segredo do webhook (entregue à API e, como credencial do consumer `gateway-pagamento`, ao Kong) e senha do admin do Grafana por este repositório; senha do banco do Keycloak, do admin, do `gestor.loja` e do client `revenda-e2e-admin` pelo repositório de identidade ([ADR-014](adrs/ADR-014-identidade-em-repositorio-proprio.md)). Nenhum valor sensível é digitado, versionado ou colocado em ConfigMap.
- `*.tfstate*`, `.terraform/`, kubeconfig e `.env` estão no `.gitignore`; o repositório tem apenas `.env.example` com valores fictícios.
- O state do Terraform contém os segredos em texto claro; por isso ele fica fora do repositório (`%USERPROFILE%\.revenda\revenda-api.tfstate`; o da identidade é outro arquivo, `identidade.tfstate`), em diretório do usuário do runner com permissão restrita (ver [08-ci-cd-infra.md](08-ci-cd-infra.md)).
- **Lição aprendida**: na fase 2, `secret.yaml`, kubeconfig e `tfstate` foram versionados por engano. Nesta fase, além do `.gitignore`, o CI executa uma varredura de segredos (Trivy com o *scanner* `secret` no repositório) e o template de PR contém o item de verificação "nenhum segredo adicionado".
- Rotação: alterar o `keepers` do `random_password` e reaplicar o Terraform gera novo valor; os pods são reiniciados pelo CD. Para produção, a evolução é um cofre de segredos (Vault, Sealed Secrets ou External Secrets).

### 3.5 Webhook do gateway

- Autenticado pelo header `X-Webhook-Secret`, comparado com o valor esperado em **tempo constante** (ex.: `hmac.compare_digest`), o que impede descobrir o segredo pela medição do tempo de resposta.
- O header nunca é registrado em log; respostas 401 não diferenciam "ausente" de "incorreto".
- **Na borda**: o Kong exige a mesma credencial pelo plugin key-auth (header `X-Webhook-Secret`) e o plugin ACL só deixa passar o consumer `gateway-pagamento`. Sem credencial válida, o Kong responde 401 e a API nem é chamada. `hide_credentials: false`: o header continua chegando à API, que valida de novo (defesa em profundidade); a regra de autenticação do webhook não depende só do gateway ([ADR-015](adrs/ADR-015-api-gateway-kong.md)).
- Idempotência por estado: reenvios do gateway não causam efeito duplicado.
- Evoluções para produção: assinatura HMAC-SHA256 do corpo com timestamp (proteção contra replay e adulteração), lista de IPs de origem do gateway, mTLS e rotação do segredo com período de convivência de dois valores.

### 3.6 Proteção de borda (API Gateway e rate limiting)

Implementado com o **Kong DB-less** ([ADR-015](adrs/ADR-015-api-gateway-kong.md)), única entrada HTTP da API no ambiente kind:

| Controle | Configuração |
|---|---|
| Única entrada | `localhost:8080` → NodePort 30080 → Kong; Service `revenda-api` ClusterIP; NetworkPolicy `revenda-api-somente-gateway` (só Kong, Prometheus e nó) |
| Superfície exposta | Só as rotas declaradas: `/api/v1`, `/docs`, `/openapi.json`, `/health/*`. `/metrics` e qualquer outro caminho → 404 do Kong |
| *Rate limiting* | 600 req/min por IP em `/api/v1`; 60 req/min por IP em `POST /api/v1/vendas`; excedente → 429 com `Retry-After`; cabeçalhos `RateLimit-*` em toda resposta dessas rotas. Limites nas variáveis `kong_limite_geral_minuto` e `kong_limite_compra_minuto` do Terraform |
| Webhook | key-auth + ACL (consumer `gateway-pagamento`), além da validação na API (seção 3.5) |
| Tamanho de payload | Até 1 MB (`request-size-limiting`); acima → 413 |
| Correlação | `X-Request-ID` gerado no Kong quando ausente, repetido na resposta e no log da API |
| Admin API | Só em `127.0.0.1:8001` dentro do pod, somente leitura (DB-less); sem Service |
| Monitoramento | Alerta `KongRejeicoesNaBorda` (401/403/429 acima de 0,5/s por 5 min) e painel "Barradas na borda" ([12-observabilidade.md](12-observabilidade.md)) |

O **JWT não é validado no Kong**: a validação fica num ponto só, na API, que já tem testes de unidade, integração e e2e; o gateway não substitui nenhum controle da API.

Limitações e evoluções: os contadores são locais ao pod (`policy: local`); com mais de uma réplica do Kong, usar `policy: redis`. O limite da compra é por IP, não por `sub` (exigiria que o Kong lesse o token). Continua como evolução um **limite de reservas ativas por comprador**, que impediria um único cliente de reservar todo o estoque (risco de "fluxo de negócio sensível" do OWASP API Security Top 10); hoje o risco é contido pelo limite de 60 compras por minuto por IP e pela expiração das reservas em 30 minutos. Mitigações na própria API continuam: paginação com limites máximos (`limite` ≤ 100 e `deslocamento` ≤ 1.000.000), validações estritas de entrada e HPA.

### 3.7 Containers, imagem e cadeia de suprimentos

- Imagem multi-stage baseada em `python:3.12-slim`, usuário não root (UID 10001), sem ferramentas de build na imagem final.
- **Trivy** no CI analisa a imagem e falha o job em vulnerabilidades `CRITICAL` ou `HIGH` com correção disponível (`--ignore-unfixed`).
- Dependências Python travadas em lockfile; Dependabot para dependências e GitHub Actions.
- Tag da imagem = SHA do commit ([ADR-010](adrs/ADR-010-kind-load-sem-registry.md)): o que roda no cluster é rastreável até o PR.

### 3.8 Transporte

No ambiente local, a comunicação é HTTP em `localhost` e o Keycloak roda em `start-dev`. Em produção: TLS em todas as conexões externas (terminação no Kong, num Ingress ou na Gateway API), Keycloak em modo `start` com `KC_HOSTNAME` HTTPS e cookies seguros, e TLS também entre aplicação e banco.

### 3.9 Logs e auditoria

- Log estruturado em JSON com `request_id`, rota, status, latência e `sub` (pseudônimo). Nunca são registrados: tokens, header `Authorization`, `X-Webhook-Secret`, senhas. O engine do SQLAlchemy usa `hide_parameters=True`, para que erros de banco não levem valores de parâmetros ao log. Respostas 5xx são registradas em nível `ERROR`.
- `GET /metrics` (Prometheus) expõe só contagens e latências por rota template, status e motivo de cancelamento, sem identificadores nem dados pessoais. Como os contadores de vendas são informação de negócio, o endpoint é **interno**: o Kong não tem rota para ele (404 pelo host), o Service da API é ClusterIP e a NetworkPolicy só deixa o Prometheus (e o Kong) chegarem à porta 8000. O painel do Grafana, que mostra esses contadores, fica só em `127.0.0.1:3000` ([12-observabilidade.md](12-observabilidade.md)).
- O Kong registra cada requisição no log de acesso (stdout) com o mesmo `X-Request-ID` da API; credenciais não são registradas.
- Eventos de domínio (`CompraIniciada`, `VendaEfetivada`, `VendaCancelada`, `ReservaExpirada` etc.) são registrados como trilha de auditoria de negócio.
- No Keycloak, eventos de login e de administração ficam habilitados no realm.

## 4. Mapeamento para o OWASP Top 10

### 4.1 OWASP Top 10:2021

| Categoria | Controles |
|---|---|
| A01 Broken Access Control | RBAC por rota; filtro por `comprador_id`; 404 para não dono; `comprador_id` só do token |
| A02 Cryptographic Failures | JWT RS256; senhas com hash no Keycloak; segredos aleatórios gerados; TLS como requisito de produção |
| A03 Injection | ORM com parâmetros vinculados; validação de entrada com Pydantic (tipos estritos, tamanhos, enums, regex do código de pagamento); caracteres de controle rejeitados em marca, modelo e cor (422), o que também evita injeção em logs |
| A04 Insecure Design | Modelagem de ameaças (este documento); invariantes no domínio e no banco; UPDATE condicional e índice único parcial contra venda dupla |
| A05 Security Misconfiguration | API alcançável só pelo gateway, com rotas declaradas (sem `/metrics` nem Admin API expostos); containers non-root e read-only; banco do Keycloak sem exposição e banco da API exposto só em `127.0.0.1` para demonstração; `start-dev` restrito ao ambiente local; erros sem stack trace |
| A06 Vulnerable and Outdated Components | Trivy no CI; Dependabot; versões fixadas de imagens e providers |
| A07 Identification and Authentication Failures | Autenticação delegada ao Keycloak (política de senha, *brute force detection*); validação completa do token; tokens de vida curta |
| A08 Software and Data Integrity Failures | `main` protegida, PR e CI obrigatórios; CD só a partir da `main`; imagem identificada pelo SHA |
| A09 Security Logging and Monitoring Failures | Log estruturado com `request_id`; respostas 5xx em nível `ERROR`; eventos de domínio; eventos do Keycloak; Prometheus coletando API e Kong, painel no Grafana e regras de alerta ativas e testadas no CI, inclusive para webhook recusado e rejeições na borda ([12-observabilidade.md](12-observabilidade.md)) |
| A10 Server-Side Request Forgery | A API não faz requisições a URLs fornecidas pelo usuário; a única chamada de saída é ao JWKS, com URL fixa por configuração |

### 4.2 OWASP API Security Top 10:2023 (riscos específicos de API)

| Risco | Controles |
|---|---|
| API1 Broken Object Level Authorization | Filtro por dono em `GET /api/v1/vendas/{id}` e `POST /api/v1/vendas/{id}/cancelar` |
| API2 Broken Authentication | Seção 3.1; webhook com credencial conferida no Kong e na API (seção 3.5) |
| API3 Broken Object Property Level Authorization | Schemas de entrada fechados (campos desconhecidos → 422; `status` e `versao` não editáveis); `comprador_id` só para gestor |
| API4 Unrestricted Resource Consumption | Paginação limitada (`limite` ≤ 100, `deslocamento` ≤ 1.000.000, acima disso 422); HPA; *rate limiting* por IP no Kong e payload ≤ 1 MB ([ADR-015](adrs/ADR-015-api-gateway-kong.md), seção 3.6) |
| API5 Broken Function Level Authorization | Papel exigido declarado em cada rota; testes de 401/403 por rota |
| API6 Unrestricted Access to Sensitive Business Flows | Reserva expira em 30 min; compra limitada a 60 req/min por IP no Kong; limite de reservas por comprador como evolução |
| API8 Security Misconfiguration | Ver A05 |
| API9 Improper Inventory Management | Versão no prefixo `/api/v1`; OpenAPI gerado do código e publicado em `/docs`; inventário de rotas expostas explícito na configuração declarativa do Kong |

## 5. LGPD

### 5.1 Papéis e dados tratados

No cenário do enunciado, a revenda é a **controladora** (art. 5º, VI) dos dados pessoais dos compradores; o Keycloak é software operado pela própria revenda, portanto não há operador externo nesta arquitetura (um IdP em nuvem, como Auth0 ou Cognito, seria um operador, nos termos do art. 5º, VII).

| Dado pessoal | Finalidade | Onde fica |
|---|---|---|
| Nome, sobrenome | Identificar o comprador na relação contratual | Keycloak (banco `keycloak`) |
| E-mail | Login, comunicação sobre a compra, recuperação de senha | Keycloak |
| CPF | Identificação civil para o contrato de compra e venda e documentação do veículo | Keycloak (atributo obrigatório do User Profile, com validação de formato; unicidade não garantida nativamente, o e-mail é o identificador único) |
| Telefone | Contato sobre a compra (pagamento, retirada) | Keycloak (atributo de usuário) |
| Credencial (hash de senha) | Autenticação | Keycloak |
| `sub` (identificador do usuário) | Vincular a venda ao comprador | Keycloak e, como `comprador_id`, banco `revenda` |
| Registros de acesso (IP, horário) | Segurança e auditoria | Logs da API e eventos do Keycloak |

Nenhum dado pessoal sensível (art. 5º, II) é tratado.

### 5.2 Princípios aplicados (art. 6º)

| Princípio | Aplicação |
|---|---|
| **Finalidade** (art. 6º, I) | Os dados são coletados para cadastro, autenticação e execução da compra; a finalidade é informada na tela de cadastro e não há uso secundário (marketing, perfilamento) |
| **Adequação** (art. 6º, II) | Cada dado coletado tem relação direta com a compra de um veículo (ex.: CPF para o contrato e a transferência do veículo) |
| **Necessidade / minimização** (art. 6º, III) | Coleta do mínimo necessário; a API transacional não recebe nem armazena nome, e-mail, CPF ou telefone, apenas o `sub`; o token não carrega dados de perfil; logs registram o pseudônimo, não dados de cadastro |
| **Segurança** (art. 6º, VII) | Controles técnicos das seções 3.1 a 3.9: segregação física, RBAC, segredos gerados, containers endurecidos |
| **Prevenção** (art. 6º, VIII) | Privacidade desde a concepção: a separação identidade × transacional foi decisão de arquitetura ([ADR-001](adrs/ADR-001-keycloak-identidade.md), [ADR-004](adrs/ADR-004-postgresql-schemas.md)), não um ajuste posterior, e foi reforçada com a entrega da identidade em repositório próprio ([ADR-014](adrs/ADR-014-identidade-em-repositorio-proprio.md)); modelagem de ameaças antes da implementação |

O art. 46 impõe ao agente de tratamento a adoção de medidas de segurança, técnicas e administrativas, aptas a proteger os dados pessoais de acessos não autorizados e de situações acidentais ou ilícitas; o seu § 2º determina que essas medidas sejam observadas desde a fase de concepção do produto ou do serviço até a sua execução. O art. 49 reforça que os sistemas utilizados no tratamento devem ser estruturados para atender aos requisitos de segurança e aos princípios gerais da Lei. A arquitetura descrita neste documento é a resposta técnica a esses dispositivos.

### 5.3 Base legal do cadastro

O tratamento dos dados de cadastro se apoia no **art. 7º, V**: tratamento "quando necessário para a execução de contrato ou de procedimentos preliminares relacionados a contrato do qual seja parte o titular, a pedido do titular dos dados". O cadastro é feito por iniciativa do próprio interessado, como etapa preliminar da compra (contrato de compra e venda), e a compra em si é a execução do contrato. O consentimento (art. 7º, I) não é a base adequada aqui, porque o tratamento é condição para a prestação contratada e não uma opção revogável a qualquer tempo sem prejuízo do contrato.

A conservação de dados de vendas concluídas após o término da relação se apoia no **cumprimento de obrigação legal ou regulatória pelo controlador** (art. 7º, II, e art. 16, I), como as obrigações fiscais da revenda.

### 5.4 Pseudonimização

O art. 13, § 4º, define pseudonimização como o tratamento por meio do qual um dado perde a possibilidade de associação, direta ou indireta, a um indivíduo, senão pelo uso de informação adicional mantida separadamente pelo controlador em ambiente controlado e seguro. A definição está inserida no artigo que trata de estudos em saúde pública, mas é a única definição legal do conceito na LGPD e é usada aqui como referência técnica.

Aplicação no projeto:

- A tabela `vendas.vendas` guarda apenas `comprador_id` = claim `sub` do token, um UUID gerado pelo Keycloak sem significado fora dele.
- A "informação adicional" que permite a reidentificação (o registro do usuário com nome, e-mail e CPF) fica em outra instância de banco, em outro namespace, com outras credenciais e acesso restrito por NetworkPolicy, declarada e implantada por outro repositório, com outro pipeline e outro state do Terraform; ou seja, "mantida separadamente [...] em ambiente controlado e seguro" (ver as camadas da separação na seção 3.3).
- **Ressalva importante**: dado pseudonimizado continua sendo dado pessoal, porque a própria revenda (controladora) consegue reidentificá-lo. A pseudonimização reduz o impacto de um vazamento do banco transacional, mas não retira esse banco do alcance da LGPD. Isso difere do dado **anonimizado** (art. 5º, III, e art. 12), que deixa de ser considerado dado pessoal.

### 5.5 Direitos do titular (art. 18)

Os direitos são atendidos no contexto **Identidade**, onde estão os dados pessoais:

| Direito (art. 18) | Como é atendido |
|---|---|
| Confirmação da existência de tratamento e acesso aos dados (I e II) | Console de conta do Keycloak (`/realms/revenda/account`): o titular vê os dados do seu cadastro. As compras ficam visíveis em `GET /api/v1/vendas/minhas` |
| Correção de dados incompletos, inexatos ou desatualizados (III) | O titular edita nome, telefone, e-mail e CPF no console de conta do Keycloak (o perfil declarativo não permite tornar um atributo editável só no cadastro; em produção, a alteração de CPF exigiria verificação de identidade) |
| Anonimização, bloqueio ou eliminação de dados desnecessários, excessivos ou tratados em desconformidade (IV) | Administrador do realm pode desabilitar (bloquear) ou excluir o usuário |
| Eliminação (VI) e término do tratamento (arts. 15 e 16) | Exclusão da conta pelo próprio titular (ação "Delete Account" habilitada no realm) ou pelo administrador |
| Portabilidade (V) e informação sobre compartilhamento (VII) | Fora do escopo técnico desta entrega; atendidos por procedimento administrativo (exportação do usuário pela API admin do Keycloak) |

Observação sobre o inciso VI: ele se refere à eliminação de dados tratados com base no **consentimento**. Como a base do cadastro é a execução de contrato, a eliminação decorre, na prática, do término do tratamento (art. 15) e do direito do inciso IV, ressalvadas as hipóteses de conservação do art. 16.

### 5.6 Exclusão da conta e vendas históricas

Quando o titular pede a exclusão:

1. O usuário é excluído do Keycloak: nome, e-mail, CPF, telefone e credenciais são apagados do banco `keycloak`.
2. As vendas no banco `revenda` **permanecem**, contendo apenas o `comprador_id` (pseudônimo), o veículo, o preço e as datas. Com o registro do Keycloak apagado, a API deixa de ter meio de reidentificar o comprador a partir desses dados.
3. A conservação do histórico de vendas se apoia no **art. 16, I** (cumprimento de obrigação legal ou regulatória pelo controlador), por exemplo, a guarda de registros fiscais e contábeis pelos prazos decadenciais e prescricionais tributários. Os dados de identificação exigidos por essas obrigações (como o CPF que consta em documento fiscal) seriam mantidos pelo sistema fiscal da revenda, que está fora do escopo desta API, sob a mesma base legal e com prazo de retenção definido.
4. Se houver venda `AGUARDANDO_PAGAMENTO` no momento da exclusão, ela expira normalmente (30 min) e o veículo volta à vitrine.

### 5.7 Acesso operacional aos dados do comprador (nota fiscal e transferência)

A separação não impede a operação da loja. Para emitir a nota fiscal ou preparar a transferência do veículo, a loja precisa do nome e do CPF do comprador de uma venda efetivada:

1. O gestor consulta a venda (`GET /api/v1/vendas/{id}` ou `GET /api/v1/vendas?status=EFETIVADA`) e obtém o `comprador_id`, que é o `sub` do comprador.
2. Um operador com papel administrativo no realm `revenda` (no ambiente local, o admin do console; em produção, um usuário com papel restrito de consulta de usuários, como `view-users` do client `realm-management`) abre o console do Keycloak e consulta o usuário por esse identificador (*Users* > busca pelo ID), onde estão nome, e-mail, CPF e telefone.

Os dados ficam **separados, mas operáveis**: a reidentificação exige uma segunda credencial, de outro sistema, concedida só a quem precisa dela, e as ações administrativas ficam registradas nos eventos de administração do Keycloak, habilitados no realm (acesso restrito e auditável). A API, o banco transacional e os logs continuam sem dado pessoal. Uma evolução é um endpoint interno de "dados para faturamento" no próprio contexto Identidade, chamado pelo sistema fiscal com credencial de serviço, em vez de consulta manual.

### 5.8 Outras obrigações (fora do escopo técnico)

Registro das operações de tratamento (art. 37), indicação do encarregado (art. 41), política de privacidade e comunicação de incidentes à ANPD e aos titulares (art. 48) são obrigações organizacionais da revenda. A arquitetura facilita o cumprimento delas: o inventário de dados da seção 5.1 serve de base para o registro das operações, e a segregação física reduz o escopo de um eventual incidente.
