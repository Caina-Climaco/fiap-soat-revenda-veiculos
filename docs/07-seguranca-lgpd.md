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
| Segredo do webhook | Secret `revenda-webhook-secret` | Alto: efetivação de vendas sem pagamento |
| Segredos de banco e admin do Keycloak | Secrets do Kubernetes e state do Terraform | Crítico |
| Pipeline de CD e runner self-hosted | PC do autor | Crítico: execução de código arbitrário com acesso ao cluster |

Fronteiras de confiança: (1) internet/navegador → API e Keycloak; (2) gateway externo → webhook; (3) namespace `revenda` ↔ namespace `identidade`; (4) GitHub → runner self-hosted.

## 2. Modelo de ameaças (STRIDE por componente)

| Componente | S — Falsificação | T — Adulteração | R — Repúdio | I — Divulgação | D — Negação de serviço | E — Elevação de privilégio |
|---|---|---|---|---|---|---|
| **revenda-api (endpoints com JWT)** | Token forjado ou de outro emissor → assinatura RS256 via JWKS, `iss`, `aud`, `azp`, `exp` validados; `alg` fixo | Alteração de claims → assinatura; alteração de preço pelo cliente → preço vem do banco, não do corpo | Ações sem trilha → log estruturado com `sub`, `request_id`, eventos de domínio | Acesso a venda alheia (BOLA) → filtro por `comprador_id`; 404 para não dono; erros sem stack trace | Abuso das listagens → paginação com limite 100; HPA; *rate limiting* como evolução | Cliente chamando rota de gestor → RBAC por `realm_access.roles` em cada rota |
| **Webhook de pagamento** | Chamador se passando pelo gateway → `X-Webhook-Secret` comparado em tempo constante | Replay de notificação → idempotência por estado da venda; HMAC do corpo com timestamp como evolução | Gateway nega ter enviado → log do payload (sem segredo) e do `request_id` | Segredo exposto em log → header nunca é registrado | Inundação de chamadas → custo baixo por chamada; rate limiting como evolução | Efetivar venda sem pagamento → só com segredo válido |
| **Keycloak** | Senha fraca / força bruta → política de senha do realm e *brute force detection* habilitados | Alteração de papéis → console admin com senha gerada pelo Terraform, não exposta no repositório | Logins não rastreados → eventos de login e de admin habilitados no realm | Vazamento de dados pessoais pelo token → token só com `sub` e papéis (sem `profile`/`email`) | Sobrecarga do login → fora do escopo local | Autocadastro obtendo `gestor` → papel padrão é apenas `cliente`; `gestor` só por admin |
| **PostgreSQL revenda** | Conexão de pod não autorizado → NetworkPolicy + credencial por Secret | SQL injection → SQLAlchemy com parâmetros vinculados, sem SQL concatenado | — | Leitura do banco → não contém dados pessoais (só pseudônimo) | Esgotamento de conexões → pool limitado por réplica | Usuário da aplicação com DDL → evolução: separar papel de migração e de aplicação |
| **PostgreSQL keycloak** | Idem → NetworkPolicy só a partir do Keycloak | — | — | Exposição de dados pessoais → banco não exposto ao host; instância separada | — | API sem credencial para este banco |
| **CI/CD e runner self-hosted** | PR de fork executando no runner → CD só em `push` na `main`; fork PRs exigem aprovação | Alteração do pipeline sem revisão → `main` protegida, PR e CI obrigatórios | Deploy sem autoria → cada deploy vinculado a SHA e PR | Segredos no repositório → gerados pelo Terraform, `.gitignore`, varredura no CI | Deploys simultâneos → `concurrency: deploy-local` | Runner com admin no host → usuário dedicado sem sudo |
| **Imagem e dependências** | Imagem base adulterada → imagens oficiais com versão fixa | Dependência vulnerável → Trivy CRITICAL/HIGH no CI; lockfile | — | — | — | Container como root → `runAsNonRoot`, `readOnlyRootFilesystem`, sem capabilities |

## 3. Controles

### 3.1 Autenticação (OIDC) e validação do JWT

- Protocolo **OpenID Connect** com o Keycloak como provedor. Swagger UI e front-end usam **Authorization Code + PKCE (S256)** com client público, sem segredo no navegador. O client `revenda-e2e` (password grant) existe só para os testes automatizados no ambiente local e não deve existir em produção (o password grant é desaconselhado pelas boas práticas atuais de OAuth).
- A API é um *resource server*: não armazena senhas nem sessões. Cada requisição é autenticada pelo access token, validado localmente:
  1. **Assinatura RS256** com a chave pública do **JWKS** do realm, selecionada pelo `kid`. O algoritmo é fixado no código (lista permitida = `RS256`), o que elimina ataques de `alg: none` e de confusão RS256/HS256.
  2. **`iss`** igual ao emissor configurado (`http://localhost:8180/realms/revenda`).
  3. **`exp`** (e `nbf`/`iat`, se presentes) com tolerância de 30 s.
  4. **`aud`** contendo `revenda-api` e **`azp`** na lista de clients autorizados: um token emitido pelo mesmo realm para outra aplicação não é aceito.
- O JWKS é obtido pelo endereço interno do Service do Keycloak e mantido em cache, com recarga ao surgir um `kid` novo (rotação de chaves) limitada a uma por minuto, para que tokens com `kid` aleatório não virem um vetor de negação de serviço contra o Keycloak.
- Tempo de vida do access token: 5 minutos (padrão do Keycloak), o que limita a janela de uso de um token vazado.

### 3.2 Autorização (RBAC) e controle por objeto

- Papéis de realm `cliente` e `gestor`, lidos de `realm_access.roles`. Cada rota declara o papel exigido (tabela em [05-api.md](05-api.md)); a verificação é feita na camada `interfaces`, antes de chamar o caso de uso.
- **Controle por objeto**: vendas são sempre filtradas pelo `comprador_id` do token quando o chamador é cliente; o não dono recebe 404 (não 403), para não confirmar a existência do recurso.
- O `comprador_id` vem exclusivamente do token, nunca do corpo da requisição.
- O autocadastro recebe apenas o papel padrão `cliente`; o papel `gestor` só é atribuído pelo administrador do realm.

### 3.3 Princípio do menor privilégio

| Onde | Aplicação |
|---|---|
| Tokens | Só as claims necessárias (`sub`, papéis, `aud`, `azp`); sem dados pessoais |
| Pods | `runAsNonRoot: true`, `runAsUser: 10001`, `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`, `readOnlyRootFilesystem: true` (com `emptyDir` em `/tmp`), `seccompProfile: RuntimeDefault`, `automountServiceAccountToken: false` |
| Rede | NetworkPolicy: banco da API só aceita API e Job de migração; banco do Keycloak só aceita o Keycloak. Bancos sem NodePort |
| Credenciais | API sem credencial do banco do Keycloak e vice-versa; Secrets montados apenas nos pods que os usam |
| Pipelines | `permissions: contents: read` nos workflows; o runner self-hosted roda como usuário sem privilégio de administrador |
| Banco | Evolução: papel `revenda_migracao` (DDL) separado de `revenda_app` (somente DML nos schemas `catalogo` e `vendas`) |

Sobre o suporte a NetworkPolicy: o CNI padrão do kind (kindnet) passou a implementar NetworkPolicy a partir da versão 0.24. O projeto exige essa versão ou superior e valida o bloqueio no teste de fumaça; se o CNI não aplicar as políticas, elas permanecem como declaração de intenção versionada.

### 3.4 Gestão de segredos

- Todos os segredos (senhas dos dois bancos, admin do Keycloak, senha do `gestor.loja` e segredo do webhook) são **gerados pelo Terraform** com `random_password` e gravados como `kubernetes_secret` ([ADR-011](adrs/ADR-011-segredos-terraform.md)). Nenhum valor sensível é digitado, versionado ou colocado em ConfigMap.
- `*.tfstate*`, `.terraform/`, kubeconfig e `.env` estão no `.gitignore`; o repositório tem apenas `.env.example` com valores fictícios.
- O state do Terraform contém os segredos em texto claro; por isso ele fica fora do repositório, em diretório do usuário do runner com permissão restrita (ver [08-ci-cd-infra.md](08-ci-cd-infra.md)).
- **Lição aprendida**: na fase 2, `secret.yaml`, kubeconfig e `tfstate` foram versionados por engano. Nesta fase, além do `.gitignore`, o CI executa uma varredura de segredos (Trivy com o *scanner* `secret` no repositório) e o template de PR contém o item de verificação "nenhum segredo adicionado".
- Rotação: alterar o `keepers` do `random_password` e reaplicar o Terraform gera novo valor; os pods são reiniciados pelo CD. Para produção, a evolução é um cofre de segredos (Vault, Sealed Secrets ou External Secrets).

### 3.5 Webhook do gateway

- Autenticado pelo header `X-Webhook-Secret`, comparado com o valor esperado em **tempo constante** (ex.: `hmac.compare_digest`), o que impede descobrir o segredo pela medição do tempo de resposta.
- O header nunca é registrado em log; respostas 401 não diferenciam "ausente" de "incorreto".
- Idempotência por estado: reenvios do gateway não causam efeito duplicado.
- Evoluções para produção: assinatura HMAC-SHA256 do corpo com timestamp (proteção contra replay e adulteração), lista de IPs de origem do gateway, mTLS e rotação do segredo com período de convivência de dois valores.

### 3.6 Proteção contra abuso (rate limiting) — evolução

Não implementado nesta entrega. Recomendações: limite por IP nas rotas públicas e por `sub` em `POST /api/v1/vendas` (por exemplo, no gateway de API ou com um middleware de *token bucket*), além de um **limite de reservas ativas por comprador**, que impediria um único cliente de reservar todo o estoque (risco de "fluxo de negócio sensível" do OWASP API Security Top 10). Mitigações já existentes: paginação com limite máximo, expiração das reservas em 30 minutos e HPA.

### 3.7 Containers, imagem e cadeia de suprimentos

- Imagem multi-stage baseada em `python:3.12-slim`, usuário não root (UID 10001), sem ferramentas de build na imagem final.
- **Trivy** no CI analisa a imagem e falha o job em vulnerabilidades `CRITICAL` ou `HIGH` com correção disponível (`--ignore-unfixed`).
- Dependências Python travadas em lockfile; Dependabot para dependências e GitHub Actions.
- Tag da imagem = SHA do commit ([ADR-010](adrs/ADR-010-kind-load-sem-registry.md)): o que roda no cluster é rastreável até o PR.

### 3.8 Transporte

No ambiente local, a comunicação é HTTP em `localhost` e o Keycloak roda em `start-dev`. Em produção: TLS em todas as conexões externas (terminação em Ingress ou Gateway API), Keycloak em modo `start` com `KC_HOSTNAME` HTTPS e cookies seguros, e TLS também entre aplicação e banco.

### 3.9 Logs e auditoria

- Log estruturado em JSON com `request_id`, rota, status, latência e `sub` (pseudônimo). Nunca são registrados: tokens, header `Authorization`, `X-Webhook-Secret`, senhas.
- Eventos de domínio (`CompraIniciada`, `VendaEfetivada`, `VendaCancelada`, `ReservaExpirada` etc.) são registrados como trilha de auditoria de negócio.
- No Keycloak, eventos de login e de administração ficam habilitados no realm.

## 4. Mapeamento para o OWASP Top 10

### 4.1 OWASP Top 10:2021

| Categoria | Controles |
|---|---|
| A01 Broken Access Control | RBAC por rota; filtro por `comprador_id`; 404 para não dono; `comprador_id` só do token |
| A02 Cryptographic Failures | JWT RS256; senhas com hash no Keycloak; segredos aleatórios gerados; TLS como requisito de produção |
| A03 Injection | ORM com parâmetros vinculados; validação de entrada com Pydantic (tipos, tamanhos, enums, regex do código de pagamento) |
| A04 Insecure Design | Modelagem de ameaças (este documento); invariantes no domínio e no banco; UPDATE condicional e índice único parcial contra venda dupla |
| A05 Security Misconfiguration | Containers non-root e read-only; bancos sem exposição; `start-dev` restrito ao ambiente local; erros sem stack trace |
| A06 Vulnerable and Outdated Components | Trivy no CI; Dependabot; versões fixadas de imagens e providers |
| A07 Identification and Authentication Failures | Autenticação delegada ao Keycloak (política de senha, *brute force detection*); validação completa do token; tokens de vida curta |
| A08 Software and Data Integrity Failures | `main` protegida, PR e CI obrigatórios; CD só a partir da `main`; imagem identificada pelo SHA |
| A09 Security Logging and Monitoring Failures | Log estruturado com `request_id`; eventos de domínio; eventos do Keycloak |
| A10 Server-Side Request Forgery | A API não faz requisições a URLs fornecidas pelo usuário; a única chamada de saída é ao JWKS, com URL fixa por configuração |

### 4.2 OWASP API Security Top 10:2023 (riscos específicos de API)

| Risco | Controles |
|---|---|
| API1 Broken Object Level Authorization | Filtro por dono em `GET /api/v1/vendas/{id}` e `POST /api/v1/vendas/{id}/cancelar` |
| API2 Broken Authentication | Seção 3.1 |
| API3 Broken Object Property Level Authorization | Schemas de entrada fechados (campos desconhecidos → 422; `status` e `versao` não editáveis); `comprador_id` só para gestor |
| API4 Unrestricted Resource Consumption | Paginação limitada; HPA; rate limiting como evolução |
| API5 Broken Function Level Authorization | Papel exigido declarado em cada rota; testes de 401/403 por rota |
| API6 Unrestricted Access to Sensitive Business Flows | Reserva expira em 30 min; limite de reservas por comprador como evolução |
| API8 Security Misconfiguration | Ver A05 |
| API9 Improper Inventory Management | Versão no prefixo `/api/v1`; OpenAPI gerado do código e publicado em `/docs` |

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
| **Prevenção** (art. 6º, VIII) | Privacidade desde a concepção: a separação identidade × transacional foi decisão de arquitetura ([ADR-001](adrs/ADR-001-keycloak-identidade.md), [ADR-004](adrs/ADR-004-postgresql-schemas.md)), não um ajuste posterior; modelagem de ameaças antes da implementação |

O art. 46 impõe ao agente de tratamento a adoção de medidas de segurança, técnicas e administrativas, aptas a proteger os dados pessoais de acessos não autorizados e de situações acidentais ou ilícitas; o seu § 2º determina que essas medidas sejam observadas desde a fase de concepção do produto ou do serviço até a sua execução. O art. 49 reforça que os sistemas utilizados no tratamento devem ser estruturados para atender aos requisitos de segurança e aos princípios gerais da Lei. A arquitetura descrita neste documento é a resposta técnica a esses dispositivos.

### 5.3 Base legal do cadastro

O tratamento dos dados de cadastro se apoia no **art. 7º, V**: tratamento "quando necessário para a execução de contrato ou de procedimentos preliminares relacionados a contrato do qual seja parte o titular, a pedido do titular dos dados". O cadastro é feito por iniciativa do próprio interessado, como etapa preliminar da compra (contrato de compra e venda), e a compra em si é a execução do contrato. O consentimento (art. 7º, I) não é a base adequada aqui, porque o tratamento é condição para a prestação contratada e não uma opção revogável a qualquer tempo sem prejuízo do contrato.

A conservação de dados de vendas concluídas após o término da relação se apoia no **cumprimento de obrigação legal ou regulatória pelo controlador** (art. 7º, II, e art. 16, I), como as obrigações fiscais da revenda.

### 5.4 Pseudonimização

O art. 13, § 4º, define pseudonimização como o tratamento por meio do qual um dado perde a possibilidade de associação, direta ou indireta, a um indivíduo, senão pelo uso de informação adicional mantida separadamente pelo controlador em ambiente controlado e seguro. A definição está inserida no artigo que trata de estudos em saúde pública, mas é a única definição legal do conceito na LGPD e é usada aqui como referência técnica.

Aplicação no projeto:

- A tabela `vendas.vendas` guarda apenas `comprador_id` = claim `sub` do token, um UUID gerado pelo Keycloak sem significado fora dele.
- A "informação adicional" que permite a reidentificação (o registro do usuário com nome, e-mail e CPF) fica em outra instância de banco, em outro namespace, com outras credenciais e acesso restrito por NetworkPolicy, ou seja, "mantida separadamente [...] em ambiente controlado e seguro".
- **Ressalva importante**: dado pseudonimizado continua sendo dado pessoal, porque a própria revenda (controladora) consegue reidentificá-lo. A pseudonimização reduz o impacto de um vazamento do banco transacional, mas não retira esse banco do alcance da LGPD. Isso difere do dado **anonimizado** (art. 5º, III, e art. 12), que deixa de ser considerado dado pessoal.

### 5.5 Direitos do titular (art. 18)

Os direitos são atendidos no contexto **Identidade**, onde estão os dados pessoais:

| Direito (art. 18) | Como é atendido |
|---|---|
| Confirmação da existência de tratamento e acesso aos dados (I e II) | Console de conta do Keycloak (`/realms/revenda/account`): o titular vê os dados do seu cadastro. As compras ficam visíveis em `GET /api/v1/vendas/minhas` |
| Correção de dados incompletos, inexatos ou desatualizados (III) | O titular edita nome, telefone e e-mail no console de conta; alterações de CPF passam pelo administrador (verificação de identidade) |
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

### 5.7 Outras obrigações (fora do escopo técnico)

Registro das operações de tratamento (art. 37), indicação do encarregado (art. 41), política de privacidade e comunicação de incidentes à ANPD e aos titulares (art. 48) são obrigações organizacionais da revenda. A arquitetura facilita o cumprimento delas: o inventário de dados da seção 5.1 serve de base para o registro das operações, e a segregação física reduz o escopo de um eventual incidente.
