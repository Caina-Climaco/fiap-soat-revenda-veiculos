# 3. Requisitos

Este documento lista os requisitos funcionais (RF) e não funcionais (RNF) da API de revenda de veículos, indicando a origem de cada um — o enunciado do Tech Challenge ou a modelagem de domínio ([02-modelagem-ddd.md](02-modelagem-ddd.md)) — e fecha com a matriz de rastreabilidade RF → endpoint → caso de uso → teste. Os cenários de teste citados estão em [09-testes.md](09-testes.md).

## 3.1 Convenções

| Campo | Valores |
|---|---|
| Origem | **E** = enunciado; **M** = descoberto na modelagem |
| Prioridade | **Must** (obrigatório para a entrega), **Should** (importante, entra no prazo), **Could** (desejável) |
| Papéis | `gestor`, `cliente`, público (sem autenticação), gateway (segredo do webhook) |

Todas as rotas da API usam o prefixo `/api/v1`, exceto as de saúde (`/health/*`).

## 3.2 Requisitos funcionais

| ID | Requisito | Origem | Prioridade | Regras relacionadas |
|---|---|---|---|---|
| RF-01 | O gestor cadastra um veículo informando marca, modelo, ano, cor e preço; o veículo nasce à venda | E | Must | RN-15, RN-16 |
| RF-02 | O gestor edita os dados de um veículo (marca, modelo, ano, cor, preço) enquanto ele está à venda | E | Must | RN-02, RN-15 |
| RF-03 | Uma pessoa se cadastra como cliente em serviço de identidade apartado da API (nome, sobrenome, e-mail, CPF, telefone, senha) e recebe o papel `cliente` | E | Must | RN-06, RN-11 |
| RF-04 | Usuários se autenticam no serviço de identidade e a API autoriza cada operação pelo papel presente no token | E | Must | RN-05, RN-06 |
| RF-05 | O cliente autenticado inicia a compra de um veículo à venda; o veículo é reservado, o preço é congelado e a venda é criada aguardando pagamento com código de pagamento e prazo de expiração | E | Must | RN-01, RN-03, RN-05, RN-06, RN-12, RN-18 |
| RF-06 | Qualquer pessoa lista os veículos à venda ordenados por preço, do mais barato para o mais caro | E | Must | RN-04, RN-17 |
| RF-07 | Qualquer pessoa lista os veículos vendidos ordenados por preço, do mais barato para o mais caro | E | Must | RN-17 |
| RF-08 | O gateway de pagamento notifica pagamento **aprovado** e a API efetiva a venda e marca o veículo como vendido | E (efetivação exigida no vídeo) | Must | RN-07, RN-08, RN-14, RN-19 |
| RF-09 | O gateway notifica pagamento **recusado** e a API cancela a venda e libera o veículo | M | Must | RN-09, RN-19 |
| RF-10 | Qualquer pessoa consulta os detalhes de um veículo pelo identificador | M | Must | — |
| RF-11 | O cliente lista as próprias compras | M | Must | RN-11, RN-13 |
| RF-12 | O dono da venda ou o gestor consulta uma venda pelo identificador; para outro cliente, a venda é tratada como inexistente | M | Should | RN-13 |
| RF-13 | O gestor lista todas as vendas, com filtro opcional por status | M | Should | — |
| RF-14 | O comprador desiste ou o gestor cancela uma venda que ainda aguarda pagamento; o veículo é liberado | M | Should | RN-10 |
| RF-15 | A reserva expira após o TTL configurado; a venda é cancelada com motivo `RESERVA_EXPIRADA` e o veículo é liberado | M | Must | RN-04, RN-14 |
| RF-16 | A API expõe verificações de vida e de prontidão para o orquestrador | M | Must | — |
| RF-17 | As listagens são paginadas (`limite`, padrão 20, máximo 100; `deslocamento`) e informam o total | M | Should | RN-17 |
| RF-18 | A API publica documentação OpenAPI interativa em `/docs`, com autenticação OAuth2 (Authorization Code + PKCE) no Keycloak | M | Should | — |

### 3.2.1 Observações

- **RF-03** não tem endpoint na API: é atendido pela tela de registro do realm `revenda` no Keycloak. O papel `cliente` é o *default role* do realm.
- **RF-04** é transversal: a API valida o JWT (assinatura RS256 via JWKS com cache, `iss`, `exp`, audiência `revenda-api`) e lê os papéis em `realm_access.roles`.
- **RF-08** e **RF-09** são atendidos pelo mesmo endpoint de webhook; o payload informa `APROVADO` ou `RECUSADO`.

## 3.3 Requisitos não funcionais

Metas medidas no ambiente local (cluster kind de um nó no PC do autor), salvo indicação contrária.

| ID | Atributo | Requisito | Meta / critério de verificação |
|---|---|---|---|
| RNF-01 | Segurança — autenticação | Toda rota não pública exige JWT válido emitido pelo realm `revenda` | Token ausente, expirado, com assinatura inválida, `iss` ou audiência errados → 401 (teste de integração) |
| RNF-02 | Segurança — autorização | Controle de acesso por papel e por propriedade da venda | Matriz papel × rota coberta por testes; gestor comprando → 403; cliente em venda alheia → 404 |
| RNF-03 | Segurança — webhook | Webhook só aceita chamadas com `X-Webhook-Secret` igual ao segredo configurado, comparado em tempo constante | Segredo ausente ou inválido → 401 sem alteração de estado (teste de integração) |
| RNF-04 | Segurança — segredos e imagem | Nenhum segredo versionado; senhas geradas pelo Terraform e entregues como `Secret` do Kubernetes; contêiner sem root e com sistema de arquivos somente leitura | `*.tfstate`, kubeconfig e `.env` no `.gitignore`; Trivy sem vulnerabilidade CRITICAL/HIGH corrigível na imagem (CI falha caso contrário) |
| RNF-05 | Privacidade / LGPD | Dados pessoais só no serviço de identidade, em instância PostgreSQL distinta; a API guarda apenas o `sub` (pseudônimo) | Nenhuma coluna de nome, e-mail, CPF ou telefone no banco `revenda` (verificado por inspeção do schema e no vídeo); logs sem dados pessoais e sem tokens |
| RNF-06 | Privacidade / LGPD | Minimização (art. 6º, III) e base legal de execução de contrato (art. 7º, V); direitos do titular atendidos no Identidade | Documentado em [07-seguranca-lgpd.md](07-seguranca-lgpd.md) |
| RNF-07 | Integridade / concorrência | Um veículo nunca tem duas vendas ativas | Teste de integração com N requisições simultâneas de compra do mesmo veículo: exatamente 1 resposta 201 e N−1 respostas 409; índice único parcial no banco |
| RNF-08 | Disponibilidade | A API roda com no mínimo 2 réplicas, com probes de vida e prontidão; prontidão falha (503) sem banco | Queda de um pod não interrompe as requisições; rollout sem indisponibilidade (`maxUnavailable: 0`) |
| RNF-09 | Escalabilidade | API sem estado; HPA de 2 a 5 réplicas com alvo de 60% de CPU | HPA ativo com metrics-server; teste de carga opcional mostra aumento de réplicas |
| RNF-10 | Desempenho | Listagens públicas rápidas com estoque realista | p95 < 300 ms em `GET /api/v1/veiculos/a-venda` e `GET /api/v1/veiculos/vendidos` com 1.000 veículos cadastrados, 20 usuários virtuais por 1 min; p95 < 500 ms em `POST /api/v1/vendas` (sem carga concorrente) |
| RNF-11 | Manutenibilidade | Clean Architecture por módulo; domínio sem dependência de framework; Vendas depende de Catálogo só pela porta `CatalogoPort` | Teste de arquitetura verifica que `*/domain` não importa FastAPI nem SQLAlchemy e que `vendas` não importa `catalogo`; ruff e mypy sem erros no CI |
| RNF-12 | Testabilidade | Relógio e repositórios injetáveis; testes por nível (unit, integration, e2e) | Cobertura de linhas ≥ 80% em `src/revenda` (unit + integration), com `--cov-fail-under=80` no CI |
| RNF-13 | Observabilidade | Logs estruturados em JSON com `request_id`, rota, status e latência; eventos de domínio registrados no log; endpoints de saúde | Cada evento de domínio da tabela 2.2.1 aparece no log com identificadores (sem dados pessoais) |
| RNF-14 | Implantabilidade (CI/CD) | Toda mudança entra por Pull Request com CI verde; deploy automático ao mergear na `main`, com migração antes do rollout e e2e ao final | `main` protegida; CI em menos de 10 min; tempo do merge ao e2e verde menor que 15 min; imagem rastreável pelo SHA do commit |
| RNF-15 | Portabilidade | Ambiente reproduzível em qualquer máquina com Docker, kind, kubectl e Terraform; configuração por variáveis de ambiente | `terraform apply` + CD sobem o ambiente do zero; `docker compose up` sobe ambiente de desenvolvimento |
| RNF-16 | Interoperabilidade | Contrato REST documentado em OpenAPI; erros em `application/problem+json` (RFC 9457) | Todas as respostas de erro contêm `type`, `title`, `status`, `detail`, `instance` |
| RNF-17 | Eficiência de recursos | O ambiente completo cabe em um PC de desenvolvimento | Soma dos *limits* de memória do cluster ≤ 4 GiB; Keycloak com *limit* de 1 GiB |

## 3.4 Matriz de rastreabilidade

Os nomes de casos de uso seguem a visão de componentes de [04-arquitetura.md](04-arquitetura.md). Os arquivos de teste são os previstos na estrutura `tests/{unit,integration,e2e}` e devem ser mantidos atualizados conforme a implementação. Os identificadores BDD-xx referem-se aos cenários de [09-testes.md](09-testes.md).

| RF | Endpoint | Caso de uso | Testes |
|---|---|---|---|
| RF-01 | `POST /api/v1/veiculos` | `CadastrarVeiculo` | `tests/unit/catalogo/test_veiculo.py`; `tests/integration/test_api_veiculos.py`; e2e `tests/e2e/test_fluxo_compra.py` |
| RF-02 | `PATCH /api/v1/veiculos/{id}` | `EditarVeiculo` | `tests/unit/catalogo/test_veiculo.py`; `tests/integration/test_api_veiculos.py`; BDD-06 |
| RF-03 | — (registro no Keycloak, realm `revenda`) | — | e2e `tests/e2e/test_fluxo_compra.py` (cria cliente via Admin API do Keycloak); verificação manual no vídeo |
| RF-04 | Todas as rotas protegidas | Dependências `autenticar` / `exigir_papel` (`shared/auth`) | `tests/unit/shared/test_auth.py`; `tests/integration/test_autorizacao.py`; BDD-04, BDD-05 |
| RF-05 | `POST /api/v1/vendas` | `IniciarCompra` | `tests/unit/vendas/test_venda.py`; `tests/unit/vendas/test_iniciar_compra.py`; `tests/integration/test_api_vendas.py`; BDD-01, BDD-03 |
| RF-06 | `GET /api/v1/veiculos/a-venda` | `ListarAVenda` | `tests/integration/test_repositorio_veiculos.py`; `tests/integration/test_api_veiculos.py`; BDD-09 |
| RF-07 | `GET /api/v1/veiculos/vendidos` | `ListarVendidos` | `tests/integration/test_api_veiculos.py`; BDD-01, BDD-09 |
| RF-08 | `POST /api/v1/pagamentos/webhook` (`APROVADO`) | `ProcessarPagamento` | `tests/unit/vendas/test_processar_pagamento.py`; `tests/integration/test_api_webhook.py`; BDD-01, BDD-07 |
| RF-09 | `POST /api/v1/pagamentos/webhook` (`RECUSADO`) | `ProcessarPagamento` | `tests/unit/vendas/test_processar_pagamento.py`; `tests/integration/test_api_webhook.py`; BDD-02 |
| RF-10 | `GET /api/v1/veiculos/{id}` | `ObterVeiculo` | `tests/integration/test_api_veiculos.py` |
| RF-11 | `GET /api/v1/vendas/minhas` | `ListarVendas` (escopo do comprador) | `tests/integration/test_api_vendas.py`; BDD-01 |
| RF-12 | `GET /api/v1/vendas/{id}` | `ObterVenda` | `tests/integration/test_api_vendas.py`; `tests/integration/test_autorizacao.py` |
| RF-13 | `GET /api/v1/vendas?status=` | `ListarVendas` (escopo do gestor) | `tests/integration/test_api_vendas.py` |
| RF-14 | `POST /api/v1/vendas/{id}/cancelar` | `CancelarVenda` | `tests/unit/vendas/test_venda.py`; `tests/integration/test_api_vendas.py` |
| RF-15 | `POST /api/v1/vendas`, `POST /api/v1/pagamentos/webhook`, `POST /api/v1/vendas/{id}/cancelar`, `GET /api/v1/veiculos/a-venda` | `IniciarCompra`, `ProcessarPagamento`, `CancelarVenda`, `ListarAVenda` (expiração preguiçosa) | `tests/unit/vendas/test_venda.py` (relógio fixo); `tests/unit/vendas/test_iniciar_compra.py`; BDD-08 |
| RF-16 | `GET /health/live`, `GET /health/ready` | — (`shared`) | `tests/integration/test_health.py`; probes no cluster |
| RF-17 | Listagens (`a-venda`, `vendidos`, `minhas`, `vendas`) | `ListarAVenda`, `ListarVendidos`, `ListarVendas` | `tests/integration/test_api_veiculos.py`; `tests/integration/test_api_vendas.py` |
| RF-18 | `GET /docs`, `GET /openapi.json` | — (`main.py`) | `tests/integration/test_openapi.py` (esquema gerado contém `securitySchemes` OAuth2) |

### 3.4.1 Rastreabilidade RNF → verificação automatizada

| RNF | Onde é verificado |
|---|---|
| RNF-01, RNF-02 | `tests/integration/test_autorizacao.py` (tokens assinados por chave RSA de teste, JWKS falso) |
| RNF-03 | `tests/integration/test_api_webhook.py`; BDD-07 |
| RNF-04 | Job Trivy no `ci.yml`; revisão do `.gitignore` no template de PR |
| RNF-05 | `tests/integration/test_schema_sem_dados_pessoais.py` (inspeciona colunas do schema `vendas`) |
| RNF-07 | `tests/integration/test_concorrencia.py`; BDD-03 |
| RNF-10 | Script de carga opcional (k6 ou hey) descrito em [09-testes.md](09-testes.md) |
| RNF-11 | `tests/unit/test_arquitetura.py`; ruff e mypy no `ci.yml` |
| RNF-12 | `pytest --cov-fail-under=80` no `ci.yml` |
| RNF-14 | Proteção de branch; `cd.yml` com etapa e2e |
