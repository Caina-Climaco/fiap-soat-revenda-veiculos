# 3. Requisitos

Este documento lista os requisitos funcionais (RF) e não funcionais (RNF) da API de revenda de veículos, indicando a origem de cada um (o enunciado do Tech Challenge ou a modelagem de domínio, [02-modelagem-ddd.md](02-modelagem-ddd.md)) e fecha com a matriz de rastreabilidade RF → endpoint → caso de uso → teste. Os cenários de teste citados estão em [09-testes.md](09-testes.md).

## 3.1 Convenções

| Campo | Valores |
|---|---|
| Origem | **E** = enunciado; **M** = descoberto na modelagem |
| Prioridade | **Must** (obrigatório para a entrega), **Should** (importante, entra no prazo), **Could** (desejável) |
| Papéis | `gestor`, `cliente`, público (sem autenticação), gateway de pagamento (segredo do webhook, consumer `gateway-pagamento` no Kong) |

Todas as rotas da API usam o prefixo `/api/v1`, exceto as de saúde (`/health/*`).

## 3.2 Requisitos funcionais

| ID | Requisito | Origem | Prioridade | Regras relacionadas |
|---|---|---|---|---|
| RF-01 | O gestor cadastra um veículo informando marca, modelo, ano, cor e preço; o veículo nasce à venda | E | Must | RN-15, RN-16, RN-20, RN-21 |
| RF-02 | O gestor edita os dados de um veículo (marca, modelo, ano, cor, preço) enquanto ele está à venda | E | Must | RN-02, RN-15, RN-21 |
| RF-03 | Uma pessoa se cadastra como cliente em serviço de identidade apartado da API (nome, sobrenome, e-mail, CPF, telefone, senha) e recebe o papel `cliente` | E | Must | RN-06, RN-11 |
| RF-04 | Usuários se autenticam no serviço de identidade e a API autoriza cada operação pelo papel presente no token | E | Must | RN-05, RN-06 |
| RF-05 | O cliente autenticado inicia a compra de um veículo à venda; o veículo é reservado, o preço é congelado e a venda é criada aguardando pagamento com código de pagamento e prazo de expiração | E | Must | RN-01, RN-03, RN-05, RN-06, RN-12, RN-18 |
| RF-06 | Qualquer pessoa lista os veículos à venda ordenados por preço, do mais barato para o mais caro | E | Must | RN-04, RN-17 |
| RF-07 | Qualquer pessoa lista os veículos vendidos ordenados por preço, do mais barato para o mais caro | E | Must | RN-17 |
| RF-08 | O gateway de pagamento notifica pagamento **aprovado** e a API efetiva a venda e marca o veículo como vendido | E (efetivação exigida no vídeo) | Must | RN-07, RN-08, RN-14, RN-19 |
| RF-09 | O gateway notifica pagamento **recusado** e a API cancela a venda e libera o veículo | M | Must | RN-09, RN-19 |
| RF-10 | Qualquer pessoa consulta os detalhes de um veículo pelo identificador | M | Must | |
| RF-11 | O cliente lista as próprias compras | M | Must | RN-11, RN-13 |
| RF-12 | O dono da venda ou o gestor consulta uma venda pelo identificador; para outro cliente, a venda é tratada como inexistente | M | Should | RN-13 |
| RF-13 | O gestor lista todas as vendas, com filtro opcional por status | M | Should | |
| RF-14 | O comprador desiste ou o gestor cancela uma venda que ainda aguarda pagamento; o veículo é liberado | M | Should | RN-10 |
| RF-15 | A reserva expira após o TTL configurado; a venda é cancelada com motivo `RESERVA_EXPIRADA` e o veículo é liberado. A API aplica a expiração em cada escrita e leitura (expiração preguiçosa); um CronJob de saneamento a cada 10 min cancela as reservas vencidas que ninguém consultou, para leituras diretas do banco ([ADR-009](adrs/ADR-009-expiracao-preguicosa.md)) | M | Must | RN-04, RN-14 |
| RF-16 | A API expõe verificações de vida e de prontidão para o orquestrador | M | Must | |
| RF-17 | As listagens são paginadas (`limite`, padrão 20, máximo 100; `deslocamento`) e informam o total | M | Should | RN-17 |
| RF-18 | A API publica documentação OpenAPI interativa em `/docs`, com autenticação OAuth2 (Authorization Code + PKCE) no Keycloak | M | Should | |

### 3.2.1 Observações

- **RF-03** não tem endpoint na API: é atendido pela tela de registro do realm `revenda` no Keycloak, mantido no repositório [fiap-soat-revenda-identidade](https://github.com/Caina-Climaco/fiap-soat-revenda-identidade). O papel `cliente` é o *default role* do realm.
- **RF-04** é transversal: a API valida o JWT (assinatura RS256 via JWKS com cache, `iss`, `exp`, audiência `revenda-api`) e lê os papéis em `realm_access.roles`.
- **RF-08** e **RF-09** são atendidos pelo mesmo endpoint de webhook; o payload informa `APROVADO` ou `RECUSADO`.

## 3.3 Requisitos não funcionais

Metas medidas no ambiente local (cluster kind de um nó no PC do autor), salvo indicação contrária.

| ID | Atributo | Requisito | Meta / critério de verificação |
|---|---|---|---|
| RNF-01 | Segurança: autenticação | Toda rota não pública exige JWT válido emitido pelo realm `revenda` | Token ausente, expirado, com assinatura inválida, `iss` ou audiência errados → 401 (teste de integração) |
| RNF-02 | Segurança: autorização | Controle de acesso por papel e por propriedade da venda | Matriz papel × rota coberta por testes; gestor comprando → 403; cliente em venda alheia → 404 |
| RNF-03 | Segurança: webhook | Webhook só aceita chamadas com `X-Webhook-Secret` igual ao segredo configurado, comparado em tempo constante; no ambiente kind, o Kong também exige a credencial (key-auth + ACL) antes de encaminhar | Segredo ausente ou inválido → 401 sem alteração de estado (teste de integração na API; e2e confere que, pelo gateway, a recusa vem do Kong) |
| RNF-04 | Segurança: segredos e imagem | Nenhum segredo versionado; senhas geradas pelo Terraform e entregues como `Secret` do Kubernetes; contêiner sem root e com sistema de arquivos somente leitura | `*.tfstate`, kubeconfig e `.env` no `.gitignore`; Trivy sem vulnerabilidade CRITICAL corrigível na imagem (CI falha caso contrário; HIGH corrigível é informativa, no job summary) |
| RNF-05 | Privacidade / LGPD | Dados pessoais só no serviço de identidade (outro repositório, pipeline, state, namespace e instância PostgreSQL); a API guarda apenas o `sub` (pseudônimo) | Nenhuma coluna de nome, e-mail, CPF ou telefone no banco `revenda` (verificado por inspeção do schema e no vídeo); logs sem dados pessoais e sem tokens |
| RNF-06 | Privacidade / LGPD | Minimização (art. 6º, III) e base legal de execução de contrato (art. 7º, V); direitos do titular atendidos no Identidade | Documentado em [07-seguranca-lgpd.md](07-seguranca-lgpd.md) |
| RNF-07 | Integridade / concorrência | Um veículo nunca tem duas vendas ativas | Teste de integração com N requisições simultâneas de compra do mesmo veículo: exatamente 1 resposta 201 e N−1 respostas 409; índice único parcial no banco |
| RNF-08 | Disponibilidade | A API roda com no mínimo 2 réplicas, com probes de vida e prontidão; prontidão falha (503) sem banco | Queda de um pod não interrompe as requisições; rollout sem indisponibilidade (`maxUnavailable: 0`) |
| RNF-09 | Escalabilidade | API sem estado; HPA de 2 a 5 réplicas com alvo de 60% de CPU | HPA ativo com metrics-server; o teste de carga (`tests/carga/listagens.js`) permite observar o HPA com `kubectl -n revenda get hpa -w` |
| RNF-10 | Desempenho | Listagens públicas rápidas | Teste de carga k6 `tests/carga/listagens.js`: 20 usuários virtuais por 1 min em `GET /api/v1/veiculos/a-venda` e `GET /api/v1/veiculos/vendidos`, com *thresholds* `p(95) < 300 ms` e taxa de erro < 1% (o k6 termina com código diferente de zero se um *threshold* falhar). Pelo API Gateway, a carga passa do *rate limiting* por IP: a medição é feita com o limite elevado ou sem gateway ([09-testes.md](09-testes.md), seção 9.6) |
| RNF-11 | Manutenibilidade | Clean Architecture por módulo; domínio sem dependência de framework; Vendas depende de Catálogo só pela porta `CatalogoPort` | Teste de arquitetura verifica que `*/domain` não importa FastAPI nem SQLAlchemy e que `vendas` não importa `catalogo`; ruff e mypy sem erros no CI |
| RNF-12 | Testabilidade | Relógio e repositórios injetáveis; testes por nível (unit, integration, e2e) | Cobertura de linhas ≥ 80% em `src/revenda` (unit + integration), com `--cov-fail-under=80` no CI |
| RNF-13 | Observabilidade | Logs estruturados em JSON com `request_id`, rota, status e latência; eventos de domínio registrados no log; endpoints de saúde; métricas no formato Prometheus em `GET /metrics` (latência, volume, erros e contadores de negócio), coletadas por Prometheus no cluster, com painel no Grafana e regras de alerta versionadas | Cada evento de domínio da tabela 2.2.1 aparece no log com identificadores (sem dados pessoais); `/metrics` expõe as séries descritas em [12-observabilidade.md](12-observabilidade.md); no CD, alvos `revenda-api` e `kong` `up` no Prometheus, 3 grupos de regras carregados e painel `revenda-visao-geral` no Grafana; regras de alerta cobertas por `promtool test rules` no CI |
| RNF-14 | Implantabilidade (CI/CD) | Toda mudança entra por Pull Request com CI verde; deploy automático ao mergear na `main`, com migração antes do rollout, CronJob de saneamento aplicado depois dele e e2e ao final | `main` protegida; CI em menos de 10 min; tempo do merge ao e2e verde menor que 15 min; imagem rastreável pelo SHA do commit |
| RNF-15 | Portabilidade | Ambiente reproduzível em qualquer máquina com Docker, kind, kubectl e Terraform; configuração por variáveis de ambiente | Identidade (repositório próprio) e depois `terraform apply` + CD deste repositório sobem o ambiente do zero; `docker compose up` (compose da identidade e depois o da API) sobe ambiente de desenvolvimento |
| RNF-16 | Interoperabilidade | Contrato REST documentado em OpenAPI; erros em `application/problem+json` (RFC 9457) | Todas as respostas de erro contêm `type`, `title`, `status`, `detail`, `instance` |
| RNF-17 | Eficiência de recursos | O ambiente completo cabe em um PC de desenvolvimento | Soma dos *limits* de memória dos componentes permanentes ≤ 6 GiB, mesmo com o HPA no máximo (5 × 256Mi da API + 1536Mi do Keycloak + 2 × 512Mi dos bancos + 200Mi do metrics-server + 512Mi do Kong + 768Mi do Prometheus + 512Mi do Grafana ≈ 5,7 GiB; Jobs transitórios fora da conta); Keycloak com *limit* de 1536Mi. A meta era 4 GiB antes do API Gateway e do monitoramento ([ADR-015](adrs/ADR-015-api-gateway-kong.md), [ADR-016](adrs/ADR-016-prometheus-grafana.md)) |
| RNF-18 | Segurança: proteção de borda | Toda entrada HTTP da API passa pelo API Gateway: *rate limiting* por IP (600/min em `/api/v1`, 60/min em `POST /api/v1/vendas`), payload máximo de 1 MB, `/metrics` sem rota externa; a API (ClusterIP) só aceita tráfego do Kong, do Prometheus e do nó | Respostas pelo gateway trazem cabeçalhos `RateLimit-*`; excedente → 429 do Kong; `GET /metrics` pelo host → 404 do Kong; NetworkPolicy `revenda-api-somente-gateway` aplicada pelo Terraform (e2e `e2e/test_e2e_gateway.py`) |

## 3.4 Matriz de rastreabilidade

Os nomes de casos de uso seguem a visão de componentes de [04-arquitetura.md](04-arquitetura.md). Os caminhos de teste são relativos a `tests/` e, quando útil, citam a função (`arquivo.py::funcao`). Os identificadores BDD-xx referem-se aos cenários de [09-testes.md](09-testes.md).

| RF | Endpoint | Caso de uso | Testes |
|---|---|---|---|
| RF-01 | `POST /api/v1/veiculos` | `CadastrarVeiculo` | `unit/catalogo/test_veiculo.py::test_cadastro_nasce_a_venda_com_versao_1_e_evento`; `unit/catalogo/test_casos_uso_catalogo.py::test_cadastrar_persiste_e_publica_evento_apos_confirmar`; `integration/test_api_catalogo.py::test_cadastro_201_com_location_e_convencoes_de_formato` e `::test_cadastro_invalido_422_com_lista_de_erros`; `integration/test_api_validacao.py` (caracteres de controle, `ano` estrito, mensagens em português); e2e `e2e/test_e2e_catalogo.py::test_e2e_cadastro_de_veiculo_pelo_gestor` |
| RF-02 | `PATCH /api/v1/veiculos/{id}` | `EditarVeiculo` | `unit/catalogo/test_veiculo.py::test_edicao_parcial_incrementa_versao`; `unit/catalogo/test_casos_uso_catalogo.py::test_editar_veiculo_a_venda`; `integration/test_api_catalogo.py::test_edicao_parcial_merge`, `::test_edicao_sem_mudanca_real_devolve_200_sem_nova_versao` e `::test_bdd_06_*`; `unit/catalogo/test_veiculo.py::test_edicao_sem_mudanca_real_nao_gera_versao_nem_evento`; e2e `e2e/test_e2e_catalogo.py::test_e2e_bdd06_*`; BDD-06 |
| RF-03 | Nenhum (registro no Keycloak, realm `revenda`) | Nenhum | e2e `e2e/conftest.py` cria os clientes pela Admin API do Keycloak com o client técnico `revenda-e2e-admin` (equivale ao autocadastro, com papel `cliente`) e `e2e/test_e2e_fluxo_compra.py::test_e2e_bdd01_fluxo_inicio_a_fim` os usa; tela de registro mostrada no vídeo |
| RF-04 | Todas as rotas protegidas | Dependências `autenticar` / `exigir_papel` (`shared/auth`) | `unit/shared/test_auth.py`; `integration/test_api_plataforma.py::test_tokens_invalidos_recebem_401` e `::test_algoritmos_none_e_hs256_sao_recusados`; `integration/test_api_vendas.py::test_bdd_04_compra_sem_cadastro`, `::test_bdd_05_gestor_tentando_comprar` e `::test_token_sem_papel_e_403`; `integration/test_api_catalogo.py::test_cadastro_exige_gestor`; e2e `e2e/test_e2e_vendas_seguranca.py`; BDD-04, BDD-05 |
| RF-05 | `POST /api/v1/vendas` | `IniciarCompra` | `unit/vendas/test_venda.py`; `unit/vendas/test_iniciar_compra.py`; `integration/test_api_vendas.py::test_bdd_01_compra_com_sucesso_e_efetivacao` e `::test_compra_de_veiculo_inexistente_indisponivel_e_payload_invalido`; `integration/test_concorrencia.py`; e2e `e2e/test_e2e_fluxo_compra.py::test_e2e_bdd01_fluxo_inicio_a_fim`; BDD-01, BDD-03 |
| RF-06 | `GET /api/v1/veiculos/a-venda` | `ListarAVenda` | `unit/catalogo/test_casos_uso_catalogo.py::test_listar_a_venda_ordena_por_preco_e_aciona_expiracao`; `integration/test_repositorios.py::test_listagem_ordena_por_preco_criado_em_e_id_com_paginacao`; `integration/test_api_catalogo.py::test_bdd_09_a_venda_do_mais_barato_ao_mais_caro`; e2e `e2e/test_e2e_catalogo.py::test_e2e_bdd09_listagem_a_venda_ordenada_por_preco`; BDD-09 |
| RF-07 | `GET /api/v1/veiculos/vendidos` | `ListarVendidos` | `unit/catalogo/test_casos_uso_catalogo.py::test_listar_vendidos`; `integration/test_api_catalogo.py::test_bdd_09_vendidos_do_mais_barato_ao_mais_caro`; e2e `e2e/test_e2e_fluxo_compra.py::test_e2e_webhook_aprovado_lista_vendidos_ordenados`; BDD-01, BDD-09 |
| RF-08 | `POST /api/v1/pagamentos/webhook` (`APROVADO`) | `ProcessarPagamento` | `unit/vendas/test_processar_pagamento.py::test_bdd_01_aprovado_efetiva_venda_e_vende_veiculo` e `::test_bdd_01_aprovado_repetido_nao_tem_efeito`; `integration/test_api_vendas.py::test_bdd_01_*` e `::test_webhook_tabela_de_estados`; e2e `e2e/test_e2e_fluxo_compra.py::test_e2e_bdd01_fluxo_inicio_a_fim`; BDD-01, BDD-07 |
| RF-09 | `POST /api/v1/pagamentos/webhook` (`RECUSADO`) | `ProcessarPagamento` | `unit/vendas/test_processar_pagamento.py::test_bdd_02_recusado_cancela_e_libera`; `integration/test_api_vendas.py::test_bdd_02_pagamento_recusado`; e2e `e2e/test_e2e_fluxo_compra.py::test_e2e_bdd02_pagamento_recusado_devolve_veiculo`; BDD-02 |
| RF-10 | `GET /api/v1/veiculos/{id}` | `ObterVeiculo` | `unit/catalogo/test_casos_uso_catalogo.py::test_obter` e `::test_obter_aciona_a_expiracao_antes_de_ler`; `integration/test_api_catalogo.py::test_consulta_de_veiculo` |
| RF-11 | `GET /api/v1/vendas/minhas` | `ListarVendas` (escopo do comprador) | `unit/vendas/test_cancelar_e_consultar.py::test_listagens`; `integration/test_api_vendas.py::test_listagens_de_vendas`; e2e `e2e/test_e2e_vendas_seguranca.py::test_e2e_minhas_compras_exige_cliente`; BDD-01 |
| RF-12 | `GET /api/v1/vendas/{id}` | `ObterVenda` | `unit/vendas/test_cancelar_e_consultar.py::test_nao_dono_recebe_nao_encontrada`; `integration/test_api_vendas.py::test_consulta_de_venda_dono_gestor_e_nao_dono`; e2e `e2e/test_e2e_vendas_seguranca.py::test_e2e_venda_de_outro_cliente_retorna_404` |
| RF-13 | `GET /api/v1/vendas?status=` | `ListarVendas` (escopo do gestor) | `integration/test_api_vendas.py::test_listagens_de_vendas` |
| RF-14 | `POST /api/v1/vendas/{id}/cancelar` | `CancelarVenda` | `unit/vendas/test_cancelar_e_consultar.py::test_dono_desiste`, `::test_gestor_cancela_pela_loja` e `::test_cancelar_venda_efetivada_e_conflito`; `integration/test_api_vendas.py::test_cancelamento_pelo_dono_e_pela_loja` e `::test_cancelamento_negado` |
| RF-15 | Escritas (`POST /api/v1/vendas`, webhook, cancelamento) e leituras (`a-venda`, `GET /api/v1/veiculos/{id}`, `GET /api/v1/vendas/{id}`, listagens de vendas) | `IniciarCompra`, `ProcessarPagamento`, `CancelarVenda`, `ListarAVenda`, `ObterVeiculo`, `ObterVenda`, `ListarVendas` (expiração preguiçosa, [ADR-009](adrs/ADR-009-expiracao-preguicosa.md)) | `unit/vendas/test_venda.py::test_bdd_08_efetivar_apos_expiracao_e_negado` e `::test_expirar_so_vale_para_reserva_vencida`; `unit/vendas/test_iniciar_compra.py::test_bdd_08_outro_cliente_compra_apos_expiracao`; `unit/vendas/test_processar_pagamento.py::test_bdd_08_*` e `::test_expirar_vencidas_em_lote`; `unit/vendas/test_cancelar_e_consultar.py::test_cancelamento_de_reserva_vencida_registra_expiracao`; leituras: `unit/vendas/test_leituras_com_expiracao.py`, `unit/catalogo/test_casos_uso_catalogo.py::test_obter_aciona_a_expiracao_antes_de_ler`; edição: `unit/catalogo/test_casos_uso_catalogo.py::test_editar_aciona_a_expiracao_antes_de_ler` e `integration/test_api_catalogo.py::test_edicao_apos_reserva_vencida_aplica_a_expiracao`; `integration/test_api_vendas.py::test_bdd_08_*`, `::test_leituras_aplicam_a_expiracao_antes_de_consultar` e `::test_cada_leitura_de_vendas_expira_sozinha`; saneamento (`python -m revenda.expirar`, CronJob `revenda-saneamento`): `unit/test_expirar.py` (laço em lotes, teto, log JSON, configuração) e `integration/test_expirar.py` (`::test_executar_cancela_as_vencidas_e_libera_os_veiculos`, `::test_teto_deixa_sobras_para_a_proxima_execucao`, `::test_main_le_o_ambiente_e_sai_com_zero`, `::test_comando_python_m_revenda_expirar`); BDD-08 |
| RF-16 | `GET /health/live`, `GET /health/ready` | Nenhum (`shared/saude`) | `integration/test_api_plataforma.py::test_health_live_e_ready` e `::test_health_ready_503_sem_banco`; probes no cluster |
| RF-17 | Listagens (`a-venda`, `vendidos`, `minhas`, `vendas`) | `ListarAVenda`, `ListarVendidos`, `ListarVendas` | `integration/test_api_catalogo.py::test_bdd_09_paginacao_mantem_a_ordem` e `::test_paginacao_invalida_422`; `integration/test_api_validacao.py::test_deslocamento_tem_teto_de_um_milhao`; `integration/test_api_vendas.py::test_listagens_de_vendas`; e2e `e2e/test_e2e_catalogo.py::test_e2e_listagens_publicas_validam_paginacao` |
| RF-18 | `GET /docs`, `GET /openapi.json` | Nenhum (`main.py`) | `integration/test_api_plataforma.py::test_openapi_documenta_oauth2_pkce_e_problem_json` e `::test_swagger_ui_usa_client_publico_com_pkce` |

### 3.4.1 Rastreabilidade RNF → verificação automatizada

| RNF | Onde é verificado |
|---|---|
| RNF-01, RNF-02 | `unit/shared/test_auth.py` e `integration/test_api_plataforma.py` (tokens assinados por chave RSA de teste, JWKS falso: `::test_tokens_invalidos_recebem_401`, `::test_cabecalhos_malformados_recebem_401`, `::test_algoritmos_none_e_hs256_sao_recusados`); `integration/test_api_vendas.py::test_bdd_05_gestor_tentando_comprar`, `::test_token_sem_papel_e_403` e `::test_consulta_de_venda_dono_gestor_e_nao_dono`; e2e `e2e/test_e2e_vendas_seguranca.py` |
| RNF-03 | `integration/test_api_vendas.py::test_bdd_07_webhook_com_segredo_invalido`; `unit/shared/test_config_e_logs.py::test_webhook_secret_e_obrigatorio_e_forte`; e2e `e2e/test_e2e_vendas_seguranca.py::test_e2e_bdd07_webhook_com_segredo_invalido_retorna_401`; BDD-07 |
| RNF-04 | Job `imagem` do `ci.yml` (Trivy na imagem e varredura de segredos); `.gitignore`; checklist do template de PR |
| RNF-05 | `integration/test_migracoes_e_schema.py::test_schema_sem_dados_pessoais` (inspeciona as colunas dos schemas `catalogo`, `vendas` e `public`); `integration/test_api_plataforma.py::test_logs_json_sem_token_sem_segredo_e_com_request_id` |
| RNF-07 | `integration/test_concorrencia.py` (`::test_bdd_03_compra_concorrente`, `::test_indice_unico_parcial_e_a_segunda_barreira_sob_concorrencia`); `integration/test_repositorios.py::test_indice_unico_parcial_barra_segunda_venda_ativa_sem_abortar_transacao`; BDD-03 |
| RNF-10 | Teste de carga k6 `tests/carga/listagens.js` ([09-testes.md](09-testes.md), seção 9.6) |
| RNF-11 | `unit/test_arquitetura.py`; `lint-imports`, ruff e mypy no job `qualidade` do `ci.yml` |
| RNF-12 | `pytest -m "unit or integration" --cov-fail-under=80` no job `testes` do `ci.yml` |
| RNF-13 | `infra/observabilidade/alertas.test.yml` (`promtool test rules` no job `infra`); etapa "Monitoramento" do `cd.yml`; `integration/test_api_plataforma.py::test_x_request_id_e_propagado_ou_gerado` e `::test_logs_json_sem_token_sem_segredo_e_com_request_id`; `unit/shared/test_config_e_logs.py::test_formatador_json_inclui_request_id_e_campos`; `unit/shared/test_erros_metricas_e_logs.py` (`/metrics` com rota template e contagem de 500, contadores de negócio por evento, nível do log de acesso, `hide_parameters`) ([12-observabilidade.md](12-observabilidade.md)) |
| RNF-14 | Proteção de branch; `cd.yml` com validação da `ref` no disparo manual, Job de migração antes do rollout, CronJob de saneamento (com execução de fumaça) depois dele e etapa e2e; `unit/test_migracao.py` (migração tolerante a rollback); `integration/test_expirar.py::test_comando_python_m_revenda_expirar` (ponto de entrada do CronJob); `kubeconform` de `k8s/base`, `k8s/migracao` e `k8s/saneamento` no job `infra` do `ci.yml` |
| RNF-16 | `integration/test_api_plataforma.py::test_rota_inexistente_e_metodo_nao_permitido_em_problem_json` e `::test_erro_inesperado_vira_500_sem_detalhes_internos` |
| RNF-18 | e2e `e2e/test_e2e_gateway.py` (cabeçalhos de *rate limiting*, limite próprio da compra, `/metrics` 404 na borda, `X-Request-ID` gerado ou propagado, webhook com credencial do consumer chega à API); `kong config parse` no job `infra` do `ci.yml` |
