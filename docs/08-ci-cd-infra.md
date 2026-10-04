# 08 — CI/CD e infraestrutura

Este documento descreve como o ambiente é criado e como o código chega a ele: a infraestrutura como código (cluster kind criado pela CLI `kind`; namespaces, bancos, Keycloak e segredos pelo Terraform), os manifestos Kubernetes da aplicação com kustomize, os pipelines de integração e entrega contínuas no GitHub Actions, as regras de governança do repositório, a segurança do runner self-hosted e o procedimento de rollback. A premissa do enunciado é que toda mudança, de implantação ou de código, passa por Pull Request e pipeline. As decisões estão nos [ADR-005](adrs/ADR-005-kind-terraform-nodeport.md), [ADR-006](adrs/ADR-006-ci-hospedado-cd-self-hosted.md), [ADR-010](adrs/ADR-010-kind-load-sem-registry.md) e [ADR-011](adrs/ADR-011-segredos-terraform.md).

## 1. Infraestrutura como código (CLI kind + Terraform)

O **cluster** é criado pela CLI `kind` a partir de `infra/kind/cluster.yaml`, e não pelo Terraform. O provider comunitário `tehcyx/kind` não tem assinatura de código e foi bloqueado pelo Smart App Control do Windows 11 no PC do runner ([ADR-005](adrs/ADR-005-kind-terraform-nodeport.md)). O arquivo define:

- o nome `revenda` e um nó control-plane;
- a imagem do nó, `kindest/node:v1.34.11`, fixada por digest (release kind v0.33.0);
- `podSubnet: 10.244.0.0/16`;
- os `extraPortMappings` em `127.0.0.1`: `30080 → 8080` (API), `30180 → 8180` (Keycloak) e `30432 → 15432` (`revenda-db`, só responde com `expor_banco_revenda = true`).

A criação é idempotente, no CD e em `scripts/windows/04-subir-ambiente.ps1`:

```bash
kind get clusters | grep -qx revenda || kind create cluster --config infra/kind/cluster.yaml --wait 120s
kind export kubeconfig --name revenda      # no Windows (script 04): API em 127.0.0.1
# no CD (container na rede docker kind): kind export kubeconfig --internal --name revenda
```

Todo o resto (o que fica **dentro** do cluster) é Terraform.

### 1.1 Providers

| Provider | Uso |
|---|---|
| `hashicorp/kubernetes` | Namespaces, Secrets, ConfigMaps, StatefulSets, Deployments, Services, NetworkPolicies |
| `hashicorp/helm` | Instala o `metrics-server` (necessário para o HPA) |
| `hashicorp/random` | Gera as senhas e o segredo do webhook (`random_password`) |

As versões dos providers são fixadas em `versions.tf` (`required_providers` com restrição `~>`) e o `.terraform.lock.hcl` é versionado. Os três providers são assinados pela HashiCorp. `kubernetes` e `helm` usam `config_path` (padrão `~/.kube/config`, variável `kubeconfig_path`) e `config_context = "kind-revenda"`.

### 1.2 Recursos

| Recurso | Detalhe |
|---|---|
| `kubernetes_namespace` | `revenda` e `identidade` |
| `helm_release.metrics_server` | Chart `metrics-server` em `kube-system`, com `--kubelet-insecure-tls` (certificados autoassinados do kubelet no kind) |
| `random_password` | `revenda_db` e `keycloak_db` (32 caracteres), `keycloak_admin` (24), `keycloak_gestor` (20), `webhook_secret` (48; a API exige no mínimo 16) |
| `kubernetes_secret` | `revenda-db-credentials` e `revenda-webhook-secret` (ns `revenda`); `keycloak-db-credentials`, `keycloak-admin` e `keycloak-gestor` (ns `identidade`) |
| PostgreSQL da API | StatefulSet `revenda-db` (`postgres:16.15-alpine`, PVC 1 Gi) + Service `revenda-db`: **NodePort 30432 por padrão** (`expor_banco_revenda = true`, publicado no host em `127.0.0.1:15432` para a demonstração do banco); ClusterIP com `expor_banco_revenda = false` |
| PostgreSQL do Keycloak | StatefulSet `keycloak-db` (`postgres:16.15-alpine`, PVC 1 Gi) + Service ClusterIP `keycloak-db` (nunca exposto) |
| Keycloak | ConfigMap com `keycloak/realm-revenda.json`; Deployment `keycloak` (`quay.io/keycloak/keycloak:26.7.1`, `start-dev --import-realm`, *request*/*limit* de memória 768Mi/1536Mi, `KC_HOSTNAME=http://localhost:8180`, `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true`, `KC_HEALTH_ENABLED=true`, admin via `KC_BOOTSTRAP_ADMIN_USERNAME/PASSWORD`); Service NodePort 30180 |
| Job `keycloak-gestor-senha` | `kcadm.sh` (mesma imagem do Keycloak): cria o `gestor.loja` se faltar, reaplica a senha do Secret `keycloak-gestor`, garante o papel `gestor` e **remove os papéis padrão de cliente** (`default-roles-revenda` e `cliente`, que um usuário criado pela Admin API herdaria) |
| `kubernetes_network_policy` | `revenda-db` aceita só pods com rótulo `app` igual a `revenda-api` ou `revenda-migracao` (mais o tráfego do NodePort quando `expor_banco_revenda = true`); `keycloak-db` aceita só pods `app=keycloak` |

O arquivo de realm usa *placeholders* de variáveis de ambiente (ex.: `${GESTOR_PASSWORD}`) resolvidos pelo Keycloak na importação; a senha do `gestor.loja` vem do Secret `keycloak-gestor` e, portanto, não fica versionada. Como o import usa a estratégia `IGNORE_EXISTING` (o realm só é criado na primeira subida; mudanças posteriores no arquivo não são reaplicadas a um realm existente), o Job `keycloak-gestor-senha` reconcilia o `gestor.loja` com o Secret de forma idempotente a cada `apply`.

Fronteira de responsabilidade: a **CLI kind** cria o cluster; o **Terraform** cuida do restante da plataforma (namespaces, segredos, bancos, Keycloak, metrics-server), que muda raramente; o **kustomize** cuida da aplicação `revenda-api`, que muda a cada merge.

### 1.3 State: onde fica e por quê

- Backend `local`, com caminho informado no `terraform init` (configuração parcial): `-backend-config="path=$USERPROFILE/.revenda/terraform.tfstate"`. `TF_DATA_DIR` também aponta para fora do repositório.
- O diretório fica no perfil do usuário do PC (`%USERPROFILE%\.revenda`). O runner em container o recebe por bind mount em `/revenda-state`: o state é um só para o script 04 (Windows) e para o CD (container), e os dois usam o Terraform 1.16.4. Cada lado tem o seu `TF_DATA_DIR`, porque os providers são de plataformas diferentes.
- **Por quê**: (1) o cluster só existe nesse PC, então um backend remoto não traria benefício de colaboração; (2) o state contém os segredos gerados em texto claro e, por isso, **nunca** pode ir para o repositório (lição da fase 2); (3) fora do *workspace* do runner, o state sobrevive à limpeza do checkout entre execuções.
- Evolução: backend remoto com criptografia e *locking* (ex.: S3 + DynamoDB, GCS ou Terraform Cloud) quando houver ambiente compartilhado.

### 1.4 Uma única aplicação

Como o cluster já existe quando o Terraform roda, os providers só leem o kubeconfig e o CD executa um único `terraform apply -auto-approve`, sem `-target`. O `terraform destroy` remove o conteúdo do cluster, mas não o cluster: ele é apagado por `kind delete cluster --name revenda` (`scripts/windows/05-destruir-ambiente.ps1` faz os dois e remove o state).

### 1.5 Recriar o ambiente do zero

```bash
# Windows: scripts\windows\05-destruir-ambiente.ps1 e depois 04-subir-ambiente.ps1, ou:
kind delete cluster --name revenda           # remove cluster e volumes
rm -f ~/.revenda/terraform.tfstate*          # remove state (segredos serão regenerados)
# Em seguida: GitHub > Actions > CD > Run workflow (branch main)
# ou, localmente:
kind create cluster --config infra/kind/cluster.yaml --wait 120s
terraform -chdir=infra/terraform init -backend-config="path=$USERPROFILE/.revenda/terraform.tfstate"
terraform -chdir=infra/terraform apply
```

Depois de recriado, o CD reconstrói a imagem, carrega no kind, aplica a migração e os manifestos. Os dados anteriores são perdidos (ambiente acadêmico).

## 2. Manifestos Kubernetes (kustomize)

### 2.1 Estrutura

```text
k8s/
├── base/                    # aplicada a cada deploy
│   ├── kustomization.yaml   # namespace revenda; images: revenda-api -> tag neutra "dev"
│   ├── configmap.yaml       # revenda-api-config: DB_HOST, DB_PORT, OIDC_*, RESERVA_TTL_MINUTOS, LOG_LEVEL
│   ├── deployment.yaml
│   ├── service.yaml         # NodePort 30080 -> porta http (8000)
│   └── hpa.yaml
└── migracao/
    ├── kustomization.yaml
    └── job.yaml             # revenda-migracao: python -m revenda.migracao (seção 2.4)
```

No repositório a imagem tem a tag neutra `revenda-api:dev`. O CD **não** commita a tag do deploy: renderiza os manifestos com `kubectl kustomize`, troca `revenda-api:dev` por `revenda-api:<sha>` com `sed` num arquivo temporário e aplica esse arquivo com `kubectl apply -f`. O CI renderiza com o mesmo `kubectl kustomize` e valida o resultado com `kubeconform -strict`.

### 2.2 Deployment `revenda-api`

| Item | Valor |
|---|---|
| Réplicas | Controladas pelo HPA (mínimo 2); o campo `replicas` é omitido do Deployment para não conflitar com o HPA a cada `apply` |
| Estratégia | `RollingUpdate`, `maxUnavailable: 0`, `maxSurge: 1`; `revisionHistoryLimit: 5` |
| Imagem | `revenda-api:<sha>`, container `api`, `imagePullPolicy: IfNotPresent` (a imagem existe só no nó do kind; nunca usar `latest`, que forçaria `Always`) |
| Porta | 8000 (Uvicorn), nomeada `http` |
| `startupProbe` | `GET /health/live`, `periodSeconds: 2`, `failureThreshold: 30` |
| `livenessProbe` | `GET /health/live`, `periodSeconds: 10`, `failureThreshold: 3` |
| `readinessProbe` | `GET /health/ready` (verifica o banco), `periodSeconds: 5`, `failureThreshold: 3` |
| Recursos | `requests: cpu 100m, memory 128Mi`; `limits: cpu 500m, memory 256Mi` |
| `securityContext` | `runAsNonRoot`, `runAsUser: 10001`, `readOnlyRootFilesystem`, `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`, `seccompProfile: RuntimeDefault`; `automountServiceAccountToken: false` |
| Volumes | `emptyDir` em `/tmp` (64Mi) |
| Env | `envFrom`: ConfigMap `revenda-api-config` e Secrets `revenda-db-credentials` e `revenda-webhook-secret` |
| Anotações do pod | `prometheus.io/scrape: "true"`, `prometheus.io/port: "8000"`, `prometheus.io/path: /metrics`, para descoberta automática por um Prometheus no cluster ([12-observabilidade.md](12-observabilidade.md)) |
| Rótulos | `app: revenda-api` (seletor do Service e rótulo aceito pela NetworkPolicy do `revenda-db`), rótulos `app.kubernetes.io/*` e `revenda.io/acesso-db: "true"` (este último informativo: nenhuma NetworkPolicy o usa; a regra do banco é por `app`) |

### 2.3 HPA

`autoscaling/v2`, `minReplicas: 2`, `maxReplicas: 5`, métrica de CPU com `averageUtilization: 60` (em relação ao `request` de 100m), `scaleDown.stabilizationWindowSeconds: 120`. Depende do `metrics-server` instalado pelo Terraform. O teste de carga `tests/carga/listagens.js` (k6) gera tráfego nas listagens públicas para observar o HPA ([09-testes.md](09-testes.md), seção 9.6).

### 2.4 Job de migração

`revenda-migracao`: mesma imagem da API, comando `python -m revenda.migracao` (no diretório `/app`, onde ficam `alembic.ini` e `migrations/`), `backoffLimit: 2`, `activeDeadlineSeconds: 300`, `ttlSecondsAfterFinished: 600`, `restartPolicy: Never`, mesmo `securityContext` da API e rótulo `app: revenda-migracao` (aceito pela NetworkPolicy do `revenda-db`). Autossuficiente: recebe `DB_HOST`/`DB_PORT` no próprio manifesto e as credenciais do Secret `revenda-db-credentials`, sem depender do ConfigMap da base.

O Job é **tolerante a rollback**. Antes de migrar, ele compara a revisão gravada no banco (`alembic_version`) com as revisões que a imagem conhece:

| Situação | Ação do Job |
|---|---|
| Banco vazio ou numa revisão conhecida pela imagem | `alembic upgrade head` |
| Banco numa revisão **desconhecida** pela imagem (criada por uma versão mais nova, caso típico de rollback) | Não altera nada e termina com sucesso |

Assim, reimplantar um SHA anterior não falha na migração: o schema mais novo permanece e, como as migrações seguem *expand/contract* ([06-dados.md](06-dados.md), seção 5.3), o código anterior continua compatível com ele. Detalhes em [06-dados.md](06-dados.md), seção 5.

## 3. Pipelines

### 3.1 Fluxo PR → CI → merge → CD → e2e

```mermaid
flowchart LR
  dev["Branch feat/*, fix/*,<br/>docs/*, infra/*"] -->|"git push"| pr["Pull Request<br/>para main"]
  pr --> ci{"CI (ubuntu-latest)<br/>qualidade, testes,<br/>imagem, infra"}
  ci -->|"falhou"| fix["Corrige na branch"] --> pr
  ci -->|"verde"| merge["Squash merge na main<br/>(título Conventional Commits)"]
  merge --> ci2["CI na main"]
  merge -->|"push na main"| cd["CD (self-hosted, kind-local)<br/>environment local"]
  disp["workflow_dispatch<br/>ref = SHA"] --> val{"ref ancestral<br/>de origin/main?"}
  val -->|"não"| recusa["CD recusado"]
  val -->|"sim"| cd
  subgraph CDJOB["Job deploy (container do runner, rede docker kind)"]
    direction TB
    kc["kind create cluster (se faltar)<br/>kind export kubeconfig --internal"] --> tf["terraform apply"] --> build["docker build<br/>revenda-api:SHA"] --> load["kind load docker-image"]
    load --> mig["Job revenda-migracao<br/>tolerante a rollback"] --> roll["kubectl kustomize + sed<br/>kubectl apply -f<br/>rollout status"] --> e2e["pytest -m e2e<br/>revenda-control-plane:30080 / :30180"] --> sum["Resumo no<br/>job summary"]
  end
  cd --> kc
  e2e -->|"falhou"| rb["Rollback<br/>(seção 6)"]
```

### 3.2 `ci.yml`: integração contínua

Gatilhos: `pull_request` para `main` e `push` na `main`. Runner: `ubuntu-latest`. `permissions: contents: read`. `concurrency` com grupo `ci-<número do PR ou ref>` e `cancel-in-progress: ${{ github.event_name == 'pull_request' }}`: um push novo no PR cancela a execução anterior do mesmo PR; na `main` nada é cancelado. Não há `paths-ignore`: os checks obrigatórios rodam em todo PR, inclusive nos só de documentação.

| Job | Passos | Falha quando |
|---|---|---|
| `qualidade` | Checkout; Python 3.12; uv com cache; `uv sync --frozen`; `ruff check`; `ruff format --check`; `mypy src`; `lint-imports` (contratos de camadas e módulos) | Erro de lint, formatação, tipagem ou violação da regra de dependência |
| `testes` | *Service container* `postgres:16-alpine` (banco `revenda_test`); `uv sync --frozen`; `uv run pytest -m "unit or integration" --cov=revenda --cov-branch --cov-report=term-missing --cov-report=xml --cov-fail-under=80` (os testes de integração aplicam `alembic upgrade head` do zero no início da sessão); publica o `coverage.xml` como artefato | Teste falho ou cobertura < 80% |
| `imagem` | Build com Buildx (tag `revenda-api:${{ github.sha }}`, sem push, cache do GitHub Actions); Trivy na imagem (`severity: CRITICAL,HIGH`, `ignore-unfixed: true`, `exit-code: 1`); Trivy `fs` com scanner `secret` no repositório. A `trivy-action` é fixada por SHA de commit | Vulnerabilidade crítica/alta corrigível ou segredo detectado |
| `infra` | `terraform fmt -check -recursive`; `terraform init -backend=false`; `terraform validate`; `kubectl kustomize` de `k8s/base` e `k8s/migracao` validado com `kubeconform -strict` (binário com checksum); `infra/kind/cluster.yaml` validado com `yq` (YAML válido, os três `extraPortMappings`, imagem por digest); `hadolint` em `infra/runner/Dockerfile` e `shellcheck` em `infra/runner/entrypoint.sh`; contrato mínimo do realm com `jq` (papéis, clients) | Formatação, configuração inválida ou manifesto fora do schema |
| `titulo-pr` | Só em `pull_request`: valida o título do PR contra a expressão regular de Conventional Commits | Título fora do padrão (não é *required check*) |

Os quatro primeiros jobs rodam em paralelo e são os *required status checks* da `main`. O CI não tem acesso a segredos nem ao cluster.

### 3.3 `cd.yml`: entrega contínua

Gatilhos: `push` na `main` (ou seja, PR mergeado) e `workflow_dispatch` com input opcional `ref` (rollback). Runner: `runs-on: [self-hosted, Linux, kind-local]`, o container Linux `revenda-runner` no Docker Desktop do PC do autor, ligado à rede docker `kind`. Por estar nessa rede, o runner usa o kubeconfig **interno** (`kind export kubeconfig --internal`, API em `https://revenda-control-plane:6443`) e testa a aplicação pelo nome do nó: `http://revenda-control-plane:30080` (API) e `http://revenda-control-plane:30180` (Keycloak), e não por `localhost:8080`/`8180`, que são portas do host Windows. O `iss` dos tokens continua `http://localhost:8180/realms/revenda`, porque `KC_HOSTNAME` é fixo.

O state fica em `/revenda-state/terraform.tfstate` (bind mount de `%USERPROFILE%\.revenda`, o mesmo arquivo do script 04), com `TF_DATA_DIR` no volume do container (providers Linux). `environment: local`. `concurrency: { group: deploy-local, cancel-in-progress: false }`: deploys são enfileirados, nunca interrompidos no meio. `permissions: contents: read`.

| Passo | O que faz | Critério de sucesso |
|---|---|---|
| 1. Checkout | `actions/checkout` do SHA do push ou do `ref` informado | — |
| 2. Validação da `ref` (só `workflow_dispatch`) | Busca `origin/main` e recusa o deploy se o commit pedido não for ancestral dela (`git merge-base --is-ancestor`) | Só commits que já passaram pela `main` são implantados |
| 3. Contexto | Calcula `SHA` e `IMAGEM=revenda-api:<sha>`; confere o bind mount do state e as ferramentas no PATH | — |
| 4. Cluster kind | Se `kind get clusters` não lista `revenda`: `kind create cluster --config infra/kind/cluster.yaml --wait 120s`; depois `kind export kubeconfig --internal --name revenda` | Contexto `kind-revenda` acessível de dentro do container |
| 5. Terraform | `terraform init -backend-config="path=/revenda-state/terraform.tfstate"`; um único `terraform apply -auto-approve` | Plataforma convergida (idempotente) |
| 6. Build | `docker build -t revenda-api:<sha> .` (reaproveita a imagem se ela já existir no Docker local, caso de rollback) | Imagem construída |
| 7. Carga no kind | `kind load docker-image revenda-api:<sha> --name revenda` | Imagem disponível no nó |
| 8. Migração | `kubectl delete job revenda-migracao --ignore-not-found --wait=true`; `kubectl kustomize k8s/migracao` + `sed` da imagem + `kubectl apply -f`; espera `complete` ou `failed` em paralelo (até 300 s) | Job com sucesso; em falha, imprime `describe` e logs e encerra **sem** alterar o Deployment |
| 9. Deploy | `kubectl kustomize k8s/base` + `sed` da imagem + `kubectl apply -f`; anotação `kubernetes.io/change-cause`; `kubectl rollout status deployment/revenda-api --timeout=180s`; confere a imagem final do container `api` | Todas as réplicas novas *ready* com a imagem do SHA |
| 10. Espera | `GET /health/ready` da API (até 180 s) e discovery do Keycloak (até 300 s), pelos endereços `revenda-control-plane` | Respostas 2xx |
| 11. e2e | Lê dos Secrets, via `kubectl`, a senha do gestor, o segredo do webhook e o admin do Keycloak (mascarados com `::add-mask::`); cria um venv com `tests/e2e/requirements.txt`; `pytest tests/e2e -m e2e` com `E2E_EXIGIR=1` e relatório JUnit | Fluxo início-a-fim verde ([09-testes.md](09-testes.md)) |
| 12. Diagnóstico (em falha) | Pods, eventos e logs da API e do Keycloak | — |
| 13. Resumo | `$GITHUB_STEP_SUMMARY`: SHA, imagem, réplicas prontas, resultado e contagem do e2e, URLs locais | — |

Se o e2e falhar após o rollout, o job falha (deploy marcado como vermelho) e o autor executa o rollback da seção 6. O rollback não é automático, para preservar o estado para diagnóstico.

## 4. Governança Git

### 4.1 Proteção da `main`

Configurada por *branch protection rule* no GitHub (`scripts/windows/02-criar-repositorio.ps1`):

| Regra | Valor |
|---|---|
| Exigir Pull Request antes do merge | Sim |
| Aprovações exigidas | **0**: trabalho individual; o GitHub não permite que o autor aprove o próprio PR. A revisão é substituída pelo CI obrigatório e pelo checklist do template |
| *Status checks* obrigatórios | `qualidade`, `testes`, `imagem`, `infra`; branch atualizada com a `main` antes do merge |
| Force push e exclusão da branch | Bloqueados |
| Incluir administradores | Sim (o próprio autor não contorna as regras) |
| Método de merge | Somente *squash merge*; o título do PR vira a mensagem do commit na `main` |
| Histórico linear | Sim |

### 4.2 Fluxo de branches

| Prefixo | Uso | Exemplo |
|---|---|---|
| `feat/*` | Nova funcionalidade | `feat/webhook-pagamento` |
| `fix/*` | Correção | `fix/ordenacao-vendidos` |
| `docs/*` | Documentação | `docs/adr-concorrencia` |
| `infra/*` | Terraform, manifestos, pipelines | `infra/hpa-revenda-api` |

Branches de vida curta, criadas a partir da `main` e apagadas após o merge.

### 4.3 Conventional Commits

Títulos de PR no formato `tipo(escopo): descrição`, com tipos `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`, `build`, `perf`, `style` e `revert`, e escopos como `catalogo`, `vendas`, `identidade`, `infra`, `ci`. Exemplos: `feat(vendas): efetivar venda via webhook`, `fix(catalogo): ordenar vendidos por preço`. Como `infra` não é um tipo do padrão, mudanças de infraestrutura usam `build`, `ci` ou `chore` com escopo `infra` (ex.: `build(infra): adicionar HPA da revenda-api`), mesmo vindo de uma branch `infra/*`. O job `titulo-pr` do CI valida o título com uma expressão regular; o script `abrir-pr.ps1` faz a mesma checagem antes de abrir o PR.

### 4.4 Template de PR (`.github/pull_request_template.md`)

| Seção | Conteúdo |
|---|---|
| **O que muda** | A mudança em 1 a 3 frases |
| **Por que** | História, requisito (RF/RNF) ou ADR que motiva a mudança |
| **Tipo** | Caixas para `feat`, `fix`, `infra` (Terraform, manifestos, pipelines), `docs` e `test` / `refactor` / `chore` |
| **Checklist** | Título segue Conventional Commits; testes adicionados ou atualizados e cobertura ≥ 80%; documentação (`docs/`, README ou ADR) atualizada quando aplicável; nenhum segredo, kubeconfig, `.env` ou `tfstate` adicionado; nenhum dado pessoal (nome, CPF, e-mail, telefone) entra no banco da API |

## 5. Segurança do runner self-hosted

O repositório é público, e a documentação do GitHub desaconselha runners self-hosted em repositórios públicos. Os controles abaixo existem por isso ([ADR-006](adrs/ADR-006-ci-hospedado-cd-self-hosted.md)).

| Controle | Detalhe |
|---|---|
| Só código revisado | O `cd.yml` é o único workflow self-hosted e dispara apenas em `push` na `main` e em `workflow_dispatch`; **nenhum** workflow com `runs-on: self-hosted` reage a `pull_request`. O CI dos PRs roda só no runner hospedado |
| `ref` restrita à `main` | No `workflow_dispatch`, o CD recusa qualquer `ref` que não seja ancestral de `origin/main`: não é possível implantar uma branch não mergeada |
| Label dedicada | Runner registrado com a label `kind-local`; somente o `cd.yml` a utiliza |
| PRs de forks | Configuração do repositório que exige aprovação para executar workflows de colaboradores externos (aplicada pelo script 02) |
| Runner em container | O runner nativo para Windows foi bloqueado pelo Smart App Control, então ele roda no container Linux `revenda-runner` (`infra/runner/Dockerfile`, base `ghcr.io/actions/actions-runner:2.337.0`; kind, kubectl, Terraform e Python com versão fixa e checksum). Ele é instalado e removido por `scripts/windows/03-instalar-runner.ps1` e reinicia sozinho (`--restart unless-stopped`). Só são montados o socket do Docker, o volume `revenda-runner-persist` (registro e `TF_DATA_DIR`) e `%USERPROFILE%\.revenda` (state) |
| Usuário sem root | Dentro do container o runner roda como `runner` (UID 1001). O entrypoint descobre o GID do `/var/run/docker.sock` e põe o usuário nesse grupo. Ressalva: o socket do Docker equivale, na prática, a privilégio de administrador sobre o Docker do host, e quem controla um job controla os containers do PC. Por isso só código já revisado e mergeado na `main` roda nele; em produção o ideal seria um runner efêmero isolado em VM |
| Token de registro | Uso único, obtido via `gh api` no momento da instalação e passado só por variável de ambiente (nunca na linha de comando nem no log). O entrypoint o apaga do ambiente antes de iniciar o runner |
| Environment `local` | O job de CD usa o environment `local`, que admite regras de proteção (ex.: restringir à branch `main`) e segredos de environment, se necessários |
| Segredos | O runner não guarda segredos da aplicação no GitHub; os valores vêm do Terraform/cluster e são mascarados nos logs |
| Workspace | Checkout limpo a cada execução; state do Terraform fora do workspace |
| Atualização | O runner se atualiza sozinho dentro do container. Ao recriar o container, ele volta à versão da imagem e se atualiza de novo. Para mudar a base, troque o `ARG RUNNER_VERSION` do Dockerfile (por PR) e rode o script 03 |

## 6. Rollback

Como cada imagem é identificada pelo SHA, voltar uma versão é reimplantar o SHA anterior. Há dois procedimentos.

**A. Reimplantar o SHA anterior pelo pipeline (preferencial, auditável)**

1. Identificar o último SHA bom (histórico de execuções do CD ou `git log main`).
2. GitHub → Actions → CD → *Run workflow*, informando `ref = <sha-anterior>`. O SHA precisa ser ancestral de `origin/main`; qualquer outra `ref` é recusada no primeiro passo.
3. O CD faz checkout desse SHA, reaproveita `revenda-api:<sha-anterior>` se a imagem ainda estiver no Docker local (ou a reconstrói), aplica e executa o e2e.
4. Migração: o Job da versão anterior encontra o banco numa revisão que a imagem dele não conhece (criada pela versão mais nova), **não altera o schema e termina com sucesso**; o rollout segue. Não há `alembic downgrade` automático: a compatibilidade vem da regra *expand/contract* ([06-dados.md](06-dados.md), seção 5.3).
5. Atenção: o Terraform também é aplicado com a versão daquele SHA; se o PR problemático alterou infraestrutura, a infraestrutura também é revertida.

**B. Emergencial no cluster**

```bash
kubectl -n revenda rollout undo deployment/revenda-api
kubectl -n revenda rollout status deployment/revenda-api
```

Retorna à *ReplicaSet* anterior em segundos (o CD aplica a imagem final de uma vez, sem ReplicaSet intermediário, para que o `undo` volte de fato à versão anterior). Em seguida, a correção definitiva deve entrar por PR (`git revert` do commit numa branch `fix/*`), para que a `main` volte a refletir o que está implantado e o próximo deploy não reintroduza o problema.
