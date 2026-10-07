# infra — plataforma local (kind)

A plataforma é definida por código em duas partes ([ADR-005](../docs/adrs/ADR-005-kind-terraform-nodeport.md), [docs/08](../docs/08-ci-cd-infra.md)):

- **`kind/cluster.yaml`**: o cluster kind `revenda`, criado pela **CLI `kind`**. O provider Terraform `tehcyx/kind` foi abandonado porque não tem assinatura de código e é bloqueado pelo Smart App Control do Windows 11.
- **`kong/`**: configuração declarativa do API Gateway (`kong.yml.tftpl`), template renderizado pelo Terraform ([ADR-015](../docs/adrs/ADR-015-api-gateway-kong.md)).
- **`observabilidade/`**: configuração do Prometheus, regras de alerta com testes e o provisionamento do Grafana ([ADR-016](../docs/adrs/ADR-016-prometheus-grafana.md)).
- **`runner/`**: imagem do runner self-hosted do GitHub Actions, que roda num container Linux no Docker Desktop (o runner nativo para Windows também é bloqueado pelo Smart App Control). Ver a seção "Runner do CD" abaixo.
- **`terraform/`**: o que é da API dentro do cluster: namespace `revenda`, segredos gerados, o PostgreSQL 16 `revenda-db`, as NetworkPolicies do banco e da API, o metrics-server, o API Gateway Kong (namespace `gateway`) e Prometheus e Grafana (namespace `observabilidade`).

A aplicação (`revenda-api`) não é criada aqui: ela vem de `k8s/` pelo CD.

O cluster kind `revenda` é a **plataforma local compartilhada** com o serviço de identidade. O namespace `identidade` (Keycloak 26.7.1, `keycloak-db`, segredos, NetworkPolicy do `keycloak-db`, Job `keycloak-reconciliar`) é implantado pelo repositório [fiap-soat-revenda-identidade](https://github.com/Caina-Climaco/fiap-soat-revenda-identidade), com Terraform e state próprios ([ADR-014](../docs/adrs/ADR-014-identidade-em-repositorio-proprio.md)). O `kind/cluster.yaml` é idêntico nos dois repositórios, e quem chegar primeiro cria o cluster.

| Arquivo | Conteúdo |
|---|---|
| `kind/cluster.yaml` | Cluster `revenda`, 1 control-plane, imagem do nó por digest, `podSubnet` 10.244.0.0/16, portas do host em 127.0.0.1: 8080→30080 (API Gateway Kong), 8180→30180 (Keycloak, Service do repositório de identidade), 15432→30432 (revenda-db), 3000→30300 (Grafana), 9090→30900 (Prometheus). Idêntico ao do repositório de identidade |
| `kong/kong.yml.tftpl` | Configuração declarativa do Kong (DB-less): serviço `revenda-api`, rotas `api`, `compra`, `webhook-pagamento`, `documentacao` e `saude`, plugins (`rate-limiting`, `key-auth`, `acl`, `correlation-id`, `request-size-limiting`, `prometheus`) e o consumer `gateway-pagamento`. Placeholders `${webhook_secret}`, `${limite_geral_minuto}`, `${limite_compra_minuto}`; o CI renderiza com valores de teste e roda `kong config parse` |
| `observabilidade/prometheus.yml` | Jobs `prometheus`, `revenda-api` e `kong`, com descoberta de pods só nos namespaces `revenda` e `gateway` |
| `observabilidade/alertas.yml` | Regras de alerta (grupos `revenda-api`, `negocio`, `gateway`) |
| `observabilidade/alertas.test.yml` | Testes de unidade das regras (`promtool test rules`, no CI) |
| `observabilidade/grafana/` | `fonte-de-dados.yml` (Prometheus, uid `prometheus`), `paineis.yml` (provedor de painéis) e `painel-revenda.json` (painel `revenda-visao-geral`) |
| `terraform/versions.tf` | Terraform >= 1.9, providers `kubernetes`, `helm`, `random` com `~>`, backend `local` sem caminho fixo |
| `terraform/providers.tf` | `kubernetes` e `helm` com `config_path` (`kubeconfig_path`, padrão `~/.kube/config`) e `config_context = "kind-revenda"` |
| `terraform/namespaces.tf` | `revenda` (o `identidade` é do repositório de identidade; `gateway` e `observabilidade` ficam em `gateway.tf` e `observabilidade.tf`) |
| `terraform/secrets.tf` | `random_password` → Secrets `revenda-db-credentials` (`DB_USER`, `DB_PASSWORD`, `DB_NAME`) e `revenda-webhook-secret` (`WEBHOOK_SECRET`) |
| `terraform/postgres.tf` | StatefulSet + Service + PVC (`standard`, 1 Gi) para `revenda-db` |
| `terraform/network_policies.tf` | Entrada no `revenda-db` só de `app=revenda-api`/`app=revenda-migracao`/`app=revenda-saneamento`; `revenda-api-somente-gateway`: entrada na API (8000) só do Kong (ns `gateway`), do Prometheus (ns `observabilidade`) e do nó |
| `terraform/gateway.tf` | Namespace `gateway`, Secret `kong-config` (template renderizado), Deployment `kong` (DB-less, 1 réplica, Admin API só em 127.0.0.1), Services `kong` (NodePort 30080) e `kong-status` (ClusterIP 8100) |
| `terraform/observabilidade.tf` | Namespace `observabilidade`; Prometheus (ServiceAccount, Roles de leitura de pods em `revenda` e `gateway`, ConfigMap, Deployment com retenção de 2 dias em `emptyDir`, Service NodePort 30900); Grafana (`random_password` + Secret `grafana-admin`, ConfigMaps de provisionamento e painel, Deployment, Service NodePort 30300) |
| `terraform/metrics_server.tf` | Chart `metrics-server` com `--kubelet-insecure-tls` |
| `terraform/variables.tf` | Entre outras: `kong_imagem` (`kong:3.9.3`), `kong_limite_geral_minuto` (600), `kong_limite_compra_minuto` (60), `prometheus_imagem` (`prom/prometheus:v3.14.0`), `grafana_imagem` (`grafana/grafana:13.2.3`) |
| `terraform/outputs.tf` | URLs (incluindo o issuer consumido da identidade), nomes dos Secrets e comandos `kubectl` para lê-los (nenhuma senha) |

## Runner do CD (`runner/`)

| Item | Detalhe |
|---|---|
| Imagem | `infra/runner/Dockerfile`: base `ghcr.io/actions/actions-runner:2.337.0` (Ubuntu 24.04, usuário `runner` UID 1001, docker CLI); kind v0.33.0 (SHA-256 fixo), kubectl v1.34.12 (SHA-512 do CHANGELOG-1.34), Terraform 1.16.4 (zip conferido pelo `SHA256SUMS` assinado pela HashiCorp, fingerprint conferido), python3 3.12 + venv + pip, jq, curl, git |
| Entrypoint | `infra/runner/entrypoint.sh`: ajusta o grupo do `/var/run/docker.sock` sem rodar como root; registra na primeira execução (`config.sh --unattended … --labels kind-local --work _work --replace`) e guarda `.runner`/`.credentials*` no volume; nas seguintes, restaura do volume; `exec ./run.sh` |
| Execução | `scripts/windows/03-instalar-runner.ps1` faz `docker run -d --name revenda-runner --restart unless-stopped --network kind -v /var/run/docker.sock:/var/run/docker.sock -v revenda-runner-persist:/home/runner/persist --mount type=bind,source=%USERPROFILE%\.revenda,target=/revenda-state`. Remoção: `-Remover`. O runner da identidade é outro container (`revenda-runner-identidade`), registrado no outro repositório |
| Dentro do container | kubeconfig interno (`kind export kubeconfig --internal --name revenda` → `https://revenda-control-plane:6443`); API (pelo Kong) `http://revenda-control-plane:30080`; Prometheus `:30900`; Grafana `:30300`; Keycloak `http://revenda-control-plane:30180` (o CD confere o realm antes do `terraform apply`); state `/revenda-state/revenda-api.tfstate` (o mesmo do Windows); `TF_DATA_DIR=/home/runner/persist/terraform-data` |
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
| Kong Gateway OSS | `kong:3.9.3` (DB-less) | variável `kong_imagem` |
| Prometheus | `prom/prometheus:v3.14.0` | variável `prometheus_imagem` |
| Grafana OSS | `grafana/grafana:13.2.3` | variável `grafana_imagem` |

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

O state contém os segredos em texto claro: fica fora do repositório (ADR-011). Variáveis úteis: `expor_banco_revenda` (padrão `true`), `kubeconfig_path`, `postgres_imagem`, `kong_limite_geral_minuto` e `kong_limite_compra_minuto`. Mudanças em `kind/cluster.yaml` precisam ser feitas igualmente nos dois repositórios e só valem recriando o cluster (05 com `-ApagarCluster`, depois a identidade e por fim o 04 daqui). `pod_subnet` do Terraform deve ser igual ao `podSubnet` do arquivo.

Segredos (Git Bash): `kubectl -n revenda get secret revenda-webhook-secret -o jsonpath='{.data.WEBHOOK_SECRET}' | base64 -d`; admin do Grafana: `kubectl -n observabilidade get secret grafana-admin -o jsonpath='{.data.GF_SECURITY_ADMIN_PASSWORD}' | base64 -d`. Veja também `terraform output comandos_segredos`. Os segredos do namespace `identidade` estão documentados no repositório de identidade.

## Checklist de verificação manual (no PC)

1. `terraform init` (sem o provider kind), `terraform validate` e `terraform fmt -check -recursive`; versionar o `.terraform.lock.hcl` gerado. Se um state antigo citar `kind_cluster`, apague o state (nenhum recurso foi criado).
2. Com a identidade já implantada, `04-subir-ambiente.ps1`: `kind create cluster` com a imagem por digest (se faltar); `kubectl config current-context` = `kind-revenda`; o realm responde; um único `terraform apply` converge. Sem a identidade, o script falha com a mensagem pedindo para subi-la.
3. `kubectl get ns` mostra `revenda`, `gateway`, `observabilidade` e `identidade`; `terraform state list` (state `revenda-api.tfstate`) não tem nenhum recurso do namespace `identidade`.
4. Token do gestor (Git Bash): `curl -s -d grant_type=password -d client_id=revenda-e2e -d username=gestor.loja --data-urlencode password=<senha> http://localhost:8180/realms/revenda/protocol/openid-connect/token`.
5. NetworkPolicy: `kubectl -n revenda run teste --rm -it --image=postgres:16.15-alpine --restart=Never -- pg_isready -h revenda-db -t 3` deve **falhar** (sem rótulo); com `--labels=app=revenda-api` deve responder.
6. `kubectl top pods -A` (metrics-server) e `psql -h localhost -p 15432 -U revenda revenda` (banco exposto).
   Depois do CD: `curl -i http://localhost:8080/health/ready` (cabeçalho `Via` do Kong), `curl -o /dev/null -w '%{http_code}' http://localhost:8080/metrics` → 404, `http://localhost:9090/targets` com `revenda-api` e `kong` `UP` e `http://localhost:3000` com o painel. NetworkPolicy da API: `kubectl -n revenda run teste --rm -it --image=curlimages/curl --restart=Never -- curl -m 3 http://revenda-api/health/live` deve **falhar** (só Kong e Prometheus chegam).
7. Segundo `04-subir-ambiente.ps1`: cluster mantido e plano vazio (idempotência). `05-destruir-ambiente.ps1`: namespace `revenda` e state da API removidos, identidade intacta; com `-ApagarCluster`, o cluster também é removido.
