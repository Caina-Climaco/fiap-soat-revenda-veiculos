# 11. Roteiro do vídeo de entrega

Este documento é o roteiro do vídeo exigido pelo enunciado: mostrar a solução funcionando **na infraestrutura e no uso**, com um teste início-a-fim que passa por **cadastro de cliente, cadastro de veículo, compra e efetivação da compra**. Duração alvo: cerca de 12 minutos. Para cada bloco há o tempo, o que mostrar na tela e uma fala sugerida, em primeira pessoa, para adaptar livremente. Antes de gravar, siga o [checklist de preparação](#112-checklist-de-preparação).

> **Vídeo entregue.** O vídeo final (12:58, legendado) condensa este roteiro em cinco blocos, na ordem que o enunciado pede: infraestrutura (blocos 3 e 4 daqui), deploy automatizado (bloco 5), uso ponta a ponta (bloco 6), separação dos dados (bloco 7) e monitoramento ([12-observabilidade.md](12-observabilidade.md)). README, modelagem, ADRs, LGPD, lista de PRs e cobertura ficaram de fora de propósito: são verificados pelos links do PDF de entrega, não pelo vídeo.

Os comandos e endereços aqui são os mesmos do [README](../README.md#3-como-usar-localmente); a sequência de uso segue o fluxo de [02-modelagem-ddd.md](02-modelagem-ddd.md) (Domain Storytelling, seção 2.1) e o cenário BDD-01 de [09-testes.md](09-testes.md).

## 11.1 Blocos e tempos

| # | Bloco | Início | Duração | O que comprova |
|---|---|---|---|---|
| 1 | Abertura e problema | 0:00 | 0:45 | Contexto e escopo |
| 2 | Modelagem DDD e decisões | 0:45 | 1:15 | Event Storming, contextos, ADRs |
| 3 | Arquitetura e separação de dados | 2:00 | 1:00 | C4, identidade apartada, LGPD |
| 4 | Infraestrutura | 3:00 | 1:15 | Cluster kind, Terraform, runner |
| 5 | Pipeline | 4:15 | 2:00 | PR, checks obrigatórios, CD, e2e (deploy automatizado) |
| 6 | Uso ponta a ponta | 6:15 | 3:45 | Cadastro de veículo e de cliente, compra, efetivação |
| 7 | Prova da separação de dados | 10:00 | 0:50 | Banco da API sem dados pessoais |
| 8 | Qualidade | 10:50 | 0:40 | Testes e cobertura |
| 9 | Encerramento | 11:30 | 0:30 | Resumo |
| | **Total** | | **cerca de 12:00** | |

O bloco 5 depende do tempo real do CI e do CD. Duas formas de manter o vídeo em 12 minutos: (a) gravar o bloco 5 com cortes de edição enquanto os checks e o deploy rodam; ou (b) abrir o PR logo depois do bloco 1 (fora da gravação ou com corte) e voltar a ele no bloco 5, quando os checks já estiverem verdes.

## 11.2 Checklist de preparação

### Ambiente no ar

- [ ] Docker Desktop iniciado; aplicativos pesados fechados (só o Keycloak tem limite de 1536 MiB de memória; risco R-02 de [10-plano-execucao.md](10-plano-execucao.md)).
- [ ] Plataforma e API de pé: `kubectl get pods -A` com tudo `Running` (namespaces `revenda`, `gateway`, `observabilidade`, `identidade`, `kube-system`), e o Job `revenda-migracao` `Completed`.
- [ ] `http://localhost:8080/health/ready` responde `{"status":"ok",...}` e `http://localhost:8180/realms/revenda/.well-known/openid-configuration` responde.
- [ ] `http://localhost:3000` abre o painel "Revenda de Veículos — visão geral" e `http://localhost:9090/targets` mostra os jobs `revenda-api` e `kong` como `UP`.
- [ ] Último run do CD verde em *Actions > CD*.
- [ ] Runner `online` em *Settings > Actions > Runners* (container `revenda-runner`; se não estiver, `docker start revenda-runner` ou rode de novo `scripts\windows\03-instalar-runner.ps1`).
- [ ] Para o bloco 8 (opcional, se for rodar a suíte ao vivo): `.env` criado a partir do `.env.example` e `docker compose up -d postgres` (porta 5432, não conflita com o kind).
- [ ] `psql` instalado, se for usá-lo no bloco 7 (senão, use a alternativa com `kubectl exec`).

### Segredos à mão

Use os comandos da [seção 11.3](#113-comandos-para-obter-os-segredos-powershell). Prefira copiar para a área de transferência (`| Set-Clipboard`) a exibir os valores na tela.

- [ ] Senha do `gestor.loja`.
- [ ] Segredo do webhook.
- [ ] Senha do admin do Keycloak.
- [ ] Senha do banco da API (bloco 7).

### Abas e janelas abertas

| Janela | Abas |
|---|---|
| Navegador A, janela normal (gestor) | Swagger `http://localhost:8080/docs`; GitHub: repositório, *Pull requests*, *Actions*, *Settings > Branches*, *Settings > Actions > Runners*; console admin `http://localhost:8180/admin/` |
| Navegador A, janela anônima (cliente 1) | Swagger `http://localhost:8080/docs` |
| Navegador A, janela normal (monitoramento) | Grafana `http://localhost:3000`; Prometheus `http://localhost:9090/alerts` |
| Navegador B, ou outro perfil (cliente 2) | Swagger `http://localhost:8080/docs`, já autenticado como cliente 2 |
| VS Code | `docs/02-modelagem-ddd.md` (pré-visualização Markdown com Mermaid), `docs/04-arquitetura.md`, `docs/adrs/README.md`, `infra/terraform/`, `infra/kind/cluster.yaml` |
| Terminal PowerShell | Na raiz do repositório, com a função `Segredo` já definida |

O Keycloak mantém uma sessão por navegador; por isso cada pessoa (gestor, cliente 1, cliente 2) fica numa janela ou navegador diferente. Janelas anônimas do mesmo navegador compartilham a sessão entre si.

### Dados de apoio

- [ ] **Cliente 2 cadastrado antes de gravar** (pela tela de registro, no navegador B), para o teste de compra concorrente não tomar tempo do vídeo.
- [ ] Dados fictícios para o cliente 1, cadastrado ao vivo: por exemplo, usuário `maria.silva`, e-mail `maria.silva@example.com`, nome Maria, sobrenome Silva, CPF `12345678901` (fictício), telefone `11987654321`. O cliente 2 pode usar CPF `98765432101` (fictício). Os dois têm só o formato válido, não os dígitos verificadores; o realm valida apenas o formato (11 dígitos).
- [ ] Os três veículos do bloco 6 em um bloco de notas, prontos para colar:
  ```json
  { "marca": "Toyota", "modelo": "Corolla XEi 2.0", "ano": 2022, "cor": "Prata", "preco": "124900.00" }
  { "marca": "Volkswagen", "modelo": "Gol 1.0 MPI", "ano": 2021, "cor": "Branco", "preco": "54900.00" }
  { "marca": "Fiat", "modelo": "Argo Drive 1.3", "ano": 2023, "cor": "Vermelho", "preco": "79900.00" }
  ```
- [ ] Uma mudança pequena para o PR do bloco 5 (por exemplo, uma linha de documentação), e nenhuma outra alteração pendente no working tree (`git status` limpo fora dela).

### Zoom e aparência

- [ ] Terminal com fonte de 16 a 18 pt; navegador com zoom de 125% a 150% no Swagger e no GitHub; VS Code com zoom aumentado (`Ctrl` + `=`).
- [ ] Notificações do Windows em modo "não perturbe"; nada sensível em outras abas.
- [ ] Resolução de gravação 1920x1080; uma janela por vez na tela.

### Dados limpos (opcional)

O e2e do CD cadastra veículos de teste (modelos com "E2E", com centavos aleatórios no preço) e eles permanecem no catálogo. Como o bloco 5 dispara um novo deploy, esses veículos reaparecem antes do bloco 6. Há três caminhos:

1. **Explicar na fala** (recomendado): "os veículos com E2E no modelo foram criados pelo teste automatizado do deploy que acabamos de ver". Isso reforça a demonstração do pipeline.
2. **Limpar só os dados transacionais** depois que o CD do bloco 5 terminar (com corte de edição). Apaga veículos e vendas do banco da API; usuários do Keycloak não são afetados:
   ```powershell
   kubectl -n revenda exec statefulset/revenda-db -- psql -U revenda -d revenda -c "TRUNCATE vendas.vendas, catalogo.veiculos;"
   ```
3. **Recriar tudo do zero** antes de gravar (cluster, bancos, usuários e segredos novos):
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\windows\05-destruir-ambiente.ps1 -Forcar
   powershell -ExecutionPolicy Bypass -File .\scripts\windows\04-subir-ambiente.ps1
   gh workflow run cd.yml -R Caina-Climaco/fiap-soat-revenda-veiculos
   ```
   Depois: confirme o runner online, aguarde o CD verde e **leia os segredos de novo** (o state foi recriado, então as senhas mudaram). Recadastre o cliente 2.

## 11.3 Comandos para obter os segredos (PowerShell)

Na raiz do repositório, com o contexto `kind-revenda` ativo (`kubectl config current-context`):

```powershell
function Segredo([string]$ns, [string]$nome, [string]$chave) {
  $b64 = kubectl -n $ns get secret $nome -o "jsonpath={.data.$chave}"
  [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($b64))
}

# Senha do gestor.loja (login no Swagger)
Segredo identidade keycloak-gestor GESTOR_PASSWORD | Set-Clipboard

# Segredo do webhook (Authorize > webhook, no Swagger)
Segredo revenda revenda-webhook-secret WEBHOOK_SECRET | Set-Clipboard

# Admin do Keycloak (console http://localhost:8180/admin/, realm master)
Segredo identidade keycloak-admin KC_BOOTSTRAP_ADMIN_USERNAME
Segredo identidade keycloak-admin KC_BOOTSTRAP_ADMIN_PASSWORD | Set-Clipboard

# Banco da API (psql em localhost:15432, usuário revenda, banco revenda)
$env:PGPASSWORD = Segredo revenda revenda-db-credentials DB_PASSWORD
```

O mesmo, em Git Bash: `kubectl -n identidade get secret keycloak-gestor -o jsonpath='{.data.GESTOR_PASSWORD}' | base64 -d` (troque namespace, Secret e chave). `terraform output comandos_segredos` lista esses comandos sem mostrar valores.

## 11.4 Roteiro por bloco

### Bloco 1 — Abertura e problema (0:00 a 0:45)

**Tela**: README do repositório no GitHub (topo, com o badge do CI), depois a seção "1. O que é".

**Fala sugerida**:
> Olá, eu sou o Cainã Clímaco, e este é o meu Trabalho Substitutivo da Fase 3 do Tech Challenge da PósTech de Software Architecture. O problema é uma revenda de veículos que quer vender pela internet. Eu entrego o back-end: uma API para cadastrar e editar veículos, permitir a compra por clientes previamente cadastrados, efetivar a compra quando o pagamento é confirmado e listar os veículos à venda e os vendidos, sempre do mais barato para o mais caro. O cadastro dos clientes fica num serviço de identidade separado, e toda mudança chega ao ambiente por Pull Request e pipeline. Vou mostrar a modelagem, a arquitetura, a infraestrutura, o pipeline e um teste ponta a ponta.

### Bloco 2 — Modelagem DDD e decisões (0:45 a 2:00)

**Tela**: no VS Code, pré-visualização de `docs/02-modelagem-ddd.md`: diagrama do Event Storming (seção 2.2), mapa de contextos (2.4.3), máquina de estados da Venda (2.6.2) e a tabela de regras descobertas (2.7). Em seguida, `docs/adrs/README.md`.

**Fala sugerida**:
> Comecei pela modelagem. No Event Storming aparecem os eventos do processo: veículo cadastrado, compra iniciada, veículo reservado, pagamento aprovado ou recusado, venda efetivada e reserva expirada. Daí saíram quatro contextos: Vendas, que é o subdomínio principal; Catálogo, de suporte; Identidade, genérico, resolvido com o Keycloak; e o gateway de pagamento, externo. Vendas conversa com Catálogo por uma porta, e o webhook do gateway funciona como camada anticorrupção.
> O enunciado avisa que nem tudo está descrito, então a modelagem descobriu regras: a compra reserva o veículo por 30 minutos, o preço fica congelado, veículo reservado não pode ser editado, um veículo só pode ter uma venda ativa e o gestor não compra. As decisões estão registradas em dezesseis ADRs, como Keycloak, monólito modular, concorrência por UPDATE condicional, expiração preguiçosa, identidade em repositório próprio, API Gateway com Kong e monitoramento com Prometheus e Grafana.

### Bloco 3 — Arquitetura e separação de dados (2:00 a 3:00)

**Tela**: `docs/04-arquitetura.md`, diagrama C4 de containers (seção 3) e, rapidamente, o diagrama de implantação (seção 5). Depois `docs/07-seguranca-lgpd.md`, seção 5.2 (tabela de princípios).

**Fala sugerida**:
> A solução tem dois sistemas. A revenda-api é um monólito modular em Python com FastAPI, com os módulos Catálogo e Vendas em Clean Architecture, e um PostgreSQL com um schema por módulo. O Keycloak fica em outro repositório, com pipeline, Terraform e state próprios, em outro namespace e com outro PostgreSQL. Essa é a separação que o enunciado pede: nome, e-mail, CPF e telefone existem só no banco do Keycloak. A API valida o token e guarda na venda apenas o identificador opaco do usuário. Isso aplica o princípio da necessidade da LGPD, artigo 6º, inciso III: o banco transacional não tem dados pessoais diretos, e a ligação com a pessoa só existe no serviço de identidade, mantido separadamente.

### Bloco 4 — Infraestrutura (3:00 a 4:15)

**Tela e comandos** (PowerShell):

```powershell
kubectl get nodes -o wide
kubectl get pods -A
kubectl get statefulsets,svc -n revenda
kubectl get statefulsets,svc -n identidade
```

Depois, no VS Code: `infra/kind/cluster.yaml` (portas 8080, 8180, 15432, 3000 e 9090) e a pasta `infra/terraform` (`secrets.tf`, `postgres.tf`, `gateway.tf`, `observabilidade.tf`). No terminal, o state (fora do repositório):

```powershell
$env:TF_DATA_DIR = "$($env:USERPROFILE -replace '\\','/')/.revenda/terraform-data"
terraform -chdir=infra/terraform state list
terraform -chdir=infra/terraform output urls
```

Por fim, no GitHub: *Settings > Actions > Runners*, mostrando o runner online com as labels `self-hosted`, `Linux` e `kind-local`.

**Fala sugerida**:
> Tudo roda no meu PC, sem nuvem. O cluster é um kind de um nó, criado pela CLI do kind a partir deste arquivo. No começo eu usava o provider do kind no Terraform, mas o binário dele não é assinado e o Smart App Control do Windows 11 bloqueou. Então a CLI cria o cluster, e cada repositório tem o seu Terraform para o que fica dentro dele. O da API cuida dos namespaces revenda, gateway e observabilidade: o PostgreSQL da API, o Kong, o Prometheus e o Grafana, as NetworkPolicies, o metrics-server e as senhas, que são geradas aleatoriamente e viram Secrets. O do serviço de identidade cuida do namespace identidade, com o Keycloak, o realm e o PostgreSQL dele. Nada sensível está nos repositórios; os dois states ficam no meu perfil de usuário.
> Aqui estão os pods: a API com duas réplicas e HPA, o Kong, o Prometheus e o Grafana, os dois bancos e o Keycloak. E estes são os runners self-hosted do GitHub Actions, um por repositório: rodam em containers Linux no Docker Desktop, ligados à rede do kind, e são eles que fazem o deploy.

### Bloco 5 — Pipeline (4:15 a 6:15)

**Tela e comandos**:

1. Terminal, com a mudança pequena já feita:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\windows\abrir-pr.ps1 `
     -Branch docs/ajuste-roteiro -Titulo "docs: ajustar roteiro do video" -Acompanhar
   ```
2. GitHub, página do PR: os checks `qualidade`, `testes`, `imagem` e `infra` (marcados como *Required*) e o `titulo-pr`.
3. *Settings > Branches*, regra da `main`: PR obrigatório, os quatro checks obrigatórios, branch atualizada, histórico linear, regras valendo para administradores.
4. Com os checks verdes: **Squash and merge**.
5. *Actions > CD*: o run disparado pelo push na `main`, executando no runner `kind-local`. Abrir o job `deploy` e passar pelos passos: cluster, Terraform, build da imagem com o SHA, carga no kind, Job de migração, rollout, testes ponta a ponta.
6. Ao terminar: o passo "Testes ponta a ponta (pytest -m e2e)" com os testes `PASSED` e o **Summary** do run (commit, imagem, réplicas prontas, resultado e contagem do e2e).

**Fala sugerida**:
> Nenhuma mudança vai direto para a main. Este script cria a branch, faz o commit e abre o Pull Request. O CI roda no runner do GitHub: lint, tipagem e regras de arquitetura; testes de unidade e integração com cobertura mínima de 80%; build da imagem com varredura do Trivy; e validação do Terraform e dos manifestos. Esses quatro checks são obrigatórios na proteção da main, que também exige PR, histórico linear e vale até para mim como administrador.
> Com tudo verde, faço o squash merge. O push na main dispara o CD no meu runner: ele garante o cluster, aplica o Terraform, constrói a imagem com a tag do commit, carrega no kind, roda a migração num Job e só então atualiza o Deployment. No fim, roda os testes ponta a ponta contra o ambiente real, com tokens reais do Keycloak. Aqui está o resumo: a imagem implantada e todos os testes e2e passando.

### Bloco 6 — Uso ponta a ponta (6:15 a 10:00)

Todas as chamadas pelo Swagger UI (`http://localhost:8080/docs`), *Try it out* > *Execute*. Mostre sempre o código de status e o corpo da resposta.

| Tempo | Passo | Tela | Resultado esperado |
|---|---|---|---|
| 6:15 | Gestor faz login | Navegador A (normal): **Authorize** > seção `keycloak` (client `revenda-swagger`, escopo `openid`) > tela do Keycloak > `gestor.loja` + senha | Volta ao Swagger autenticado |
| 6:40 | Cadastra 3 veículos | `POST /api/v1/veiculos` três vezes, com os JSONs preparados | 201, `status: "A_VENDA"`, `versao: 1`, header `Location` |
| 7:15 | Edita um preço | `PATCH /api/v1/veiculos/{veiculo_id}` do Gol com `{ "preco": "52900.00" }` | 200, `versao: 2` |
| 7:30 | Cliente se cadastra | Navegador A (anônima): **Authorize** > tela do Keycloak > link de cadastro (*Register*) > usuário, e-mail, nome, sobrenome, **CPF**, telefone e senha | Volta ao Swagger já autenticado como cliente |
| 8:00 | Vitrine ordenada | `GET /api/v1/veiculos/a-venda` (sem token) | Itens do mais barato ao mais caro |
| 8:20 | Compra | Cliente 1: `POST /api/v1/vendas` com `{ "veiculo_id": "<id do Argo>" }` | 201, `status: "AGUARDANDO_PAGAMENTO"`, `codigo_pagamento` `PAG-...`, `preco_venda`, `expira_em` (30 min) |
| 8:45 | Compra concorrente | Navegador B (cliente 2): `POST /api/v1/vendas` com o mesmo `veiculo_id` | 409, `type: urn:revenda:problema:veiculo-indisponivel` |
| 9:05 | Gateway aprova | Navegador A (normal): **Authorize** > seção `webhook` > colar o `WEBHOOK_SECRET`; `POST /api/v1/pagamentos/webhook` com `{ "codigo_pagamento": "PAG-...", "status": "APROVADO" }` | 200, `status: "EFETIVADA"`, `efetivada_em` preenchido |
| 9:30 | Vendidos ordenados | `GET /api/v1/veiculos/vendidos` | O Argo com `status: "VENDIDO"`, em ordem de preço |
| 9:40 | Minhas compras | Navegador A (anônima, cliente 1): `GET /api/v1/vendas/minhas` | A venda `EFETIVADA` |

Se sobrar tempo: `GET /api/v1/veiculos/a-venda` de novo (o Argo não aparece mais) ou o gestor tentando `POST /api/v1/vendas` (403).

**Fala sugerida**:
> Agora o uso, como um front-end faria. O gestor da loja entra pelo Keycloak; o Swagger usa Authorization Code com PKCE, sem segredo no navegador. Cadastro três veículos e edito o preço do Gol: a versão do veículo sobe para dois.
> Numa janela anônima, uma cliente se cadastra na tela do próprio Keycloak, informando o CPF. Ela recebe automaticamente o papel de cliente. A vitrine é pública e vem ordenada por preço, do mais barato para o mais caro.
> A cliente compra o Argo. A resposta é 201: a venda está aguardando pagamento, com um código de pagamento e prazo de 30 minutos. O veículo fica reservado e o preço está congelado. Se outro cliente tenta comprar o mesmo carro, recebe 409: veículo indisponível. Isso é garantido no banco, por um UPDATE condicional e um índice único parcial.
> Agora faço o papel do gateway de pagamento: ele chama o webhook com o código e o resultado APROVADO, autenticado por um segredo compartilhado no header. A venda é efetivada e o veículo passa a vendido. Ele aparece na lista de vendidos, também ordenada por preço, e a cliente vê a compra efetivada em minhas compras.

### Trecho opcional — API Gateway e monitoramento (cerca de 1 min, no fim do bloco 6 ou com corte)

**Tela**: terminal (Git Bash) e, depois, o navegador no Grafana e no Prometheus.

```bash
# Cabeçalhos do Kong: limite por IP, saldo, correlação e o próprio gateway
curl -s -D - -o /dev/null http://localhost:8080/api/v1/veiculos/a-venda | grep -iE 'ratelimit|x-request-id|via'
# Webhook sem a credencial: barrado na borda (401 do Kong, sem X-Kong-Upstream-Latency)
curl -s -i -X POST http://localhost:8080/api/v1/pagamentos/webhook -H "Content-Type: application/json" \
  -d '{"codigo_pagamento":"PAG-000000000000","status":"APROVADO"}' | head -n 12
# /metrics não é publicado pelo gateway
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/metrics      # 404
```

Depois: `http://localhost:3000` (linhas Negócio, API e Kong, com a venda que acabou de ser efetivada e o 401 em "Barradas na borda") e `http://localhost:9090/alerts` (as 8 regras, em `inactive` ou `firing`).

**Fala sugerida**:
> Na frente da API há um API Gateway, o Kong, em modo declarativo: a configuração está versionada no repositório e é validada no CI. Ele é a única entrada: limita requisições por IP, com limite menor na compra, gera o X-Request-ID e só deixa o webhook passar com a credencial do gateway de pagamento; sem ela, a resposta 401 vem do próprio Kong, e a API valida o segredo de novo. O /metrics nem é publicado. As métricas da API e do Kong vão para um Prometheus no cluster, e o Grafana mostra o painel de negócio e os golden signals. As regras de alerta também estão no repositório, com testes no CI.

### Bloco 7 — Prova da separação de dados (10:00 a 10:50)

**Tela e comandos** (PowerShell, com `$env:PGPASSWORD` definido na [seção 11.3](#113-comandos-para-obter-os-segredos-powershell)):

```powershell
psql -h localhost -p 15432 -U revenda -d revenda
```

```sql
\d vendas.vendas
SELECT comprador_id, status, preco_venda, codigo_pagamento FROM vendas.vendas ORDER BY criada_em DESC LIMIT 3;
```

Sem `psql` instalado, o mesmo dentro do pod:

```powershell
kubectl -n revenda exec -it statefulset/revenda-db -- psql -U revenda -d revenda
```

Em seguida, console admin `http://localhost:8180/admin/` (usuário `admin`) > seletor de realm: `revenda` > *Users* > buscar `maria.silva` > abrir o usuário: o **ID** é igual ao `comprador_id` da venda, e o formulário mostra nome, e-mail, CPF e telefone. Para fechar, no terminal: `kubectl get statefulsets -A` (dois bancos, em namespaces diferentes) e `kubectl -n identidade get svc keycloak-db` (ClusterIP, sem porta no host).

**Fala sugerida**:
> Para provar a separação, abro o banco da API. A tabela de vendas tem o veículo, o preço, o status e o comprador_id, que é só um UUID. Não há coluna de nome, e-mail, CPF ou telefone. Esse mesmo UUID é o ID do usuário no Keycloak, e só lá estão os dados pessoais, num outro PostgreSQL, em outro namespace, que nem é exposto fora do cluster. A API não tem credencial para esse banco.

### Bloco 8 — Qualidade (10:50 a 11:30)

**Tela**: *Actions > CI* > último run da `main` > job `testes` > passo "Unidade + integracao com cobertura (minimo 80%)", rolando até a linha `TOTAL` do relatório. Opcionalmente, ao vivo (com o PostgreSQL do compose de pé e `TEST_DATABASE_URL` definido como no [README](../README.md#41-unidade-e-integração)):

```powershell
uv run pytest -m "unit or integration" --cov=revenda --cov-branch --cov-report=term
uv run lint-imports
```

**Fala sugerida**:
> A suíte tem testes de unidade para o domínio e os casos de uso, com relógio fixo, e testes de integração contra um PostgreSQL real, incluindo o teste de concorrência que dispara compras simultâneas do mesmo carro. O CI exige 80% de cobertura; a suíte chega a cerca de 99%. O import-linter garante as regras da Clean Architecture, e os testes ponta a ponta rodam a cada deploy.

### Bloco 9 — Encerramento (11:30 a 12:00)

**Tela**: README no GitHub, seção "2.12 Documentação" (tabela de docs e ADRs).

**Fala sugerida**:
> Resumindo: uma API com cadastro e edição de veículos, compra por clientes cadastrados num serviço de identidade separado, efetivação por webhook de pagamento e listagens ordenadas por preço, com proteção contra venda dupla e expiração de reservas. A infraestrutura é código, o deploy é automático a cada merge e o fluxo ponta a ponta é testado no próprio pipeline. Toda a documentação, a modelagem e os ADRs estão no repositório. Obrigado.

## 11.5 Se algo der errado durante a gravação

| Sintoma | Ação |
|---|---|
| 401 no Swagger depois de alguns minutos | O access token vale 5 minutos: clique em **Authorize** > *Logout* e entre de novo (a sessão do Keycloak continua, então o login é imediato) |
| O CD fica em *Queued* | Runner offline: `docker ps --filter name=revenda-runner`; se parado, `docker start revenda-runner` |
| CD falhou no e2e | Abrir o passo "Diagnostico em falha"; reexecutar com *Re-run jobs* ou *Actions > CD > Run workflow* |
| Cadastro no Keycloak recusa o CPF | O campo exige exatamente 11 dígitos, sem pontos nem traço |
| Webhook responde 401 | Segredo errado ou não informado em **Authorize** > `webhook` (com o gateway, a resposta vem do Kong: `{"message": ...}`) |
| Resposta 429 do Kong | Limite por IP excedido (600/min em `/api/v1`, 60/min na compra): espere o minuto virar (cabeçalho `Retry-After`) |
| Grafana ou Prometheus não abrem (3000/9090) | Cluster criado antes das novas portas: recriar (README, seção 9); ou `kubectl -n observabilidade get pods` |
| Webhook responde 409 `reserva-expirada` | Passaram 30 minutos desde a compra: refaça a compra com outro veículo |
| `psql` não conecta em 15432 | Use a alternativa com `kubectl exec` do bloco 7 |
