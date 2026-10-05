# infra — plataforma local (kind)

A plataforma é definida por código em duas partes ([ADR-005](../docs/adrs/ADR-005-kind-terraform-nodeport.md), [docs/08](../docs/08-ci-cd-infra.md)):

- **`kind/cluster.yaml`**: o cluster kind `revenda`, criado pela **CLI `kind`**. O provider Terraform `tehcyx/kind` foi abandonado porque não tem assinatura de código e é bloqueado pelo Smart App Control do Windows 11.
- **`runner/`**: imagem do runner self-hosted do GitHub Actions, que roda num container Linux no Docker Desktop (o runner nativo para Windows também é bloqueado pelo Smart App Control). Ver a seção "Runner do CD" abaixo.
- **`terraform/`**: o que é da API dentro do cluster: namespace `revenda`, segredos gerados, o PostgreSQL 16 `revenda-db`, a NetworkPolicy dele e o metrics-server.

A aplicação (`revenda-api`) não é criada aqui: ela vem de `k8s/` pelo CD.

O cluster kind `revenda` é a **plataforma local compartilhada** com o serviço de identidade. O namespace `identidade` (Keycloak 26.7.1, `keycloak-db`, segredos, NetworkPolicy do `keycloak-db`, Job `keycloak-reconciliar`) é implantado pelo repositório [fiap-soat-revenda-identidade](https://github.com/Caina-Climaco/fiap-soat-revenda-identidade), com Terraform e state próprios ([ADR-014](../docs/adrs/ADR-014-identidade-em-repositorio-proprio.md)). O `kind/cluster.yaml` é idêntico nos dois repositórios, e quem chegar primeiro cria o cluster.

| Arquivo | Conteúdo |
|---|---|
| `kind/cluster.yaml` | Cluster `revenda`, 1 control-plane, imagem do nó por digest, `podSubnet` 10.244.0.0/16, portas do host em 127.0.0.1: 8080→30080 (API), 8180→30180 (Keycloak, Service do repositório de identidade), 15432→30432 (revenda-db). Idêntico ao do repositório de identidade |
| `terraform/versions.tf` | Terraform >= 1.9, providers `kubernetes`, `helm`, `random` com `~>`, backend `local` sem caminho fixo |
| `terraform/providers.tf` | `kubernetes` e `helm` com `config_path` (`kubeconfig_path`, padrão `~/.kube/config`) e `config_context = "kind-revenda"` |
| `terraform/namespaces.tf` | `revenda` (o `identidade` é do repositório de identidade) |
| `terraform/secrets.tf` | `random_password` → Secrets `revenda-db-credentials` (`DB_USER`, `DB_PASSWORD`, `DB_NAME`) e `revenda-webhook-secret` (`WEBHOOK_SECRET`) |
| `terraform/postgres.tf` | StatefulSet + Service + PVC (`standard`, 1 Gi) para `revenda-db` |
| `terraform/network_policies.tf` | Entrada no `revenda-db` só de `app=revenda-api`/`app=revenda-migracao` |
| `terraform/metrics_server.tf` | Chart `metrics-server` com `--kubelet-insecure-tls` |
| `terraform/outputs.tf` | URLs (incluindo o issuer consumido da identidade), nomes dos Secrets e comandos `kubectl` para lê-los (nenhuma senha) |

## Runner do CD (`runner/`)

| Item | Detalhe |
|---|---|
| Imagem | `infra/runner/Dockerfile`: base `ghcr.io/actions/actions-runner:2.337.0` (Ubuntu 24.04, usuário `runner` UID 1001, docker CLI); kind v0.33.0 (SHA-256 fixo), kubectl v1.34.12 (SHA-512 do CHANGELOG-1.34), Terraform 1.16.4 (zip conferido pelo `SHA256SUMS` assinado pela HashiCorp, fingerprint conferido), python3 3.12 + venv + pip, jq, curl, git |
| Entrypoint | `infra/runner/entrypoint.sh`: ajusta o grupo do `/var/run/docker.sock` sem rodar como root; registra na primeira execução (`config.sh --unattended … --labels kind-local --work _work --replace`) e guarda `.runner`/`.credentials*` no volume; nas seguintes, restaura do volume; `exec ./run.sh` |
| Execução | `scripts/windows/03-instalar-runner.ps1` faz `docker run -d --name revenda-runner --restart unless-stopped --network kind -v /var/run/docker.sock:/var/run/docker.sock -v revenda-runner-persist:/home/runner/persist --mount type=bind,source=%USERPROFILE%\.revenda,target=/revenda-state`. Remoção: `-Remover`. O runner da identidade é outro container (`revenda-runner-identidade`), registrado no outro repositório |
| Dentro do container | kubeconfig interno (`kind export kubeconfig --internal --name revenda` → `https://revenda-control-plane:6443`); API `http://revenda-control-plane:30080`; Keycloak `http://revenda-control-plane:30180` (o CD confere o realm antes do `terraform apply`); state `/revenda-state/revenda-api.tfstate` (o mesmo do Windows); `TF_DATA_DIR=/home/runner/persist/terraform-data` |
| Lock dos providers | O `.terraform.lock.hcl` precisa valer no Windows (script 04) e no Linux (container). Gere no PC com `terraform -chdir=infra/terraform providers lock -platform=windows_amd64 -platform=linux_amd64` e versione |

## Versões

| Item | Versão | Fonte |
|---|---|---|
| CLI kind | v0.33.0 (PC via winget; runner via GitHub Releases com SHA-256) | release kind v0.33.0 |
| Runner do Actions | imagem `ghcr.io/actions/actions-runner:2.337.0` | `images/Dockerfile` e `release.yml` de actions/runner |
| Nó do kind | `kindest/node:v1.34.11@sha256:44e2…d67d` | notas do release kind v0.33.0 |
| `hashicorp/kubernetes` | `~> 3.3` (3.3.0 corrige o `wait_for_rollout` de StatefulSet) | CHANGELOG do provider |
| `hashicorp/helm` | `~> 3.3` (sintaxe 3.x: `kubernetes = { ... }`) | CHANGELOG do provider |
| `hashicorp/random` | `~> 3.9` | CHANGELOG do provider |
| PostgreSQL | `postgres:16.15-alpine` | docker-library/postgres `versions.json` |
| metrics-server | chart `3.14.0` | tags `metrics-server-helm-chart-*` |

## Uso

Pré-requisito: o serviço de identidade no ar (repositório de identidade, script 04 ou CD de lá). Depois, no Windows, use `scripts/windows/04-subir-ambiente.ps1` e `05-destruir-ambiente.ps1`. Eles usam o **mesmo** state (`%USERPROFILE%\.revenda\revenda-api.tfstate`) e `TF_DATA_DIR` do CD (`.github/workflows/cd.yml`). O 04 exige o realm `revenda` em `http://localhost:8180` e avisa se ainda existir o state antigo `terraform.tfstate` (anterior à separação; ver a seção "Migração para dois repositórios" do [README](../README.md#8-migração-para-dois-repositórios)). O 05 destrói só a API; `-ApagarCluster` apaga também o cluster (e, com ele, a identidade). Equivalente manual (Git Bash):

```bash
kind get clusters | grep -qx revenda || kind create cluster --config infra/kind/cluster.yaml --wait 120s
kind export kubeconfig --name revenda
curl -fsS http://localhost:8180/realms/revenda/.well-known/openid-configuration >/dev/null   # identidade no ar?
export TF_DATA_DIR="$(cygpath -m "$USERPROFILE")/.revenda/terraform-data"
terraform -chdir=infra/terraform init -reconfigure -backend-config="path=$(cygpath -m "$USERPROFILE")/.revenda/revenda-api.tfstate"
terraform -chdir=infra/terraform apply
# destruir só a API: terraform destroy e apagar o state; o cluster é compartilhado
```

O state contém os segredos em texto claro: fica fora do repositório (ADR-011). Variáveis úteis: `expor_banco_revenda` (padrão `true`), `kubeconfig_path`, `postgres_imagem`. Mudanças em `kind/cluster.yaml` precisam ser feitas igualmente nos dois repositórios e só valem recriando o cluster (05 com `-ApagarCluster`, depois a identidade e por fim o 04 daqui). `pod_subnet` do Terraform deve ser igual ao `podSubnet` do arquivo.

Segredos (Git Bash): `kubectl -n revenda get secret revenda-webhook-secret -o jsonpath='{.data.WEBHOOK_SECRET}' | base64 -d`. Veja também `terraform output comandos_segredos`. Os segredos do namespace `identidade` estão documentados no repositório de identidade.

## Verificar no PC (não executável no ambiente de autoria)

1. `terraform init` (sem o provider kind), `terraform validate` e `terraform fmt -check -recursive`; versionar o `.terraform.lock.hcl` gerado. Se um state antigo citar `kind_cluster`, apague o state (nenhum recurso foi criado).
2. Com a identidade já implantada, `04-subir-ambiente.ps1`: `kind create cluster` com a imagem por digest (se faltar); `kubectl config current-context` = `kind-revenda`; o realm responde; um único `terraform apply` converge. Sem a identidade, o script falha com a mensagem pedindo para subi-la.
3. `kubectl get ns` mostra `revenda` e `identidade`; `terraform state list` (state `revenda-api.tfstate`) não tem nenhum recurso do namespace `identidade`.
4. Token do gestor (Git Bash): `curl -s -d grant_type=password -d client_id=revenda-e2e -d username=gestor.loja --data-urlencode password=<senha> http://localhost:8180/realms/revenda/protocol/openid-connect/token`.
5. NetworkPolicy: `kubectl -n revenda run teste --rm -it --image=postgres:16.15-alpine --restart=Never -- pg_isready -h revenda-db -t 3` deve **falhar** (sem rótulo); com `--labels=app=revenda-api` deve responder.
6. `kubectl top pods -A` (metrics-server) e `psql -h localhost -p 15432 -U revenda revenda` (banco exposto).
7. Segundo `04-subir-ambiente.ps1`: cluster mantido e plano vazio (idempotência). `05-destruir-ambiente.ps1`: namespace `revenda` e state da API removidos, identidade intacta; com `-ApagarCluster`, o cluster também é removido.
