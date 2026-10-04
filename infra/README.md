# infra/terraform — plataforma local (kind)

Provisiona tudo o que é plataforma ([ADR-005](../docs/adrs/ADR-005-kind-terraform-nodeport.md), [docs/08](../docs/08-ci-cd-infra.md)): cluster kind `revenda`, namespaces `revenda` e `identidade`, segredos gerados, os dois PostgreSQL 16, o Keycloak com o realm `revenda` e o metrics-server. A aplicação (`revenda-api`) não é criada aqui: ela vem de `k8s/` pelo CD.

| Arquivo | Conteúdo |
|---|---|
| `versions.tf` | Terraform >= 1.9, providers com `~>`, backend `local` sem caminho fixo |
| `providers.tf` | `kubernetes` e `helm` configurados com as saídas do `kind_cluster` |
| `cluster.tf` | `kind_cluster.revenda`: 1 control-plane; portas do host em 127.0.0.1: 8080→30080 (API), 8180→30180 (Keycloak), 15432→30432 (revenda-db) |
| `namespaces.tf` | `revenda`, `identidade` |
| `secrets.tf` | `random_password` → Secrets (nomes e chaves da seção 14.3 do design brief) |
| `postgres.tf` | StatefulSet + Service + PVC (`standard`, 1 Gi) para `revenda-db` e `keycloak-db` |
| `keycloak.tf` | ConfigMap do realm, Deployment e Service NodePort 30180, Job `keycloak-gestor-senha` |
| `network_policies.tf` | Entrada nos bancos: `revenda-db` só de `app=revenda-api`/`app=revenda-migracao`; `keycloak-db` só de `app=keycloak` |
| `metrics_server.tf` | Chart `metrics-server` com `--kubelet-insecure-tls` |
| `outputs.tf` | URLs, nomes dos Secrets e comandos `kubectl` para lê-los (nenhuma senha) |

## Versões

| Item | Versão | Fonte |
|---|---|---|
| `tehcyx/kind` | `~> 0.11.0` (embute a biblioteca kind v0.31.0) | tags e `go.mod` de github.com/tehcyx/terraform-provider-kind |
| `hashicorp/kubernetes` | `~> 3.3` (3.3.0 corrige o `wait_for_rollout` de StatefulSet) | CHANGELOG do provider |
| `hashicorp/helm` | `~> 3.3` (sintaxe 3.x: `kubernetes = { ... }`) | CHANGELOG do provider |
| `hashicorp/random` | `~> 3.9` | CHANGELOG do provider |
| Nó do kind | `kindest/node:v1.34.11@sha256:44e2…d67d` | notas do release kind v0.33.0 |
| PostgreSQL | `postgres:16.15-alpine` | docker-library/postgres `versions.json` |
| Keycloak | `quay.io/keycloak/keycloak:26.4.16` | tags de github.com/keycloak/keycloak |
| metrics-server | chart `3.14.0` | tags `metrics-server-helm-chart-*` |

## Uso

O CD (`.github/workflows/cd.yml`) e os scripts `scripts/windows/04-subir-ambiente.ps1` e `05-destruir-ambiente.ps1` usam o **mesmo** state:

```powershell
$env:TF_DATA_DIR = "$env:USERPROFILE/.revenda/terraform-data"
terraform -chdir=infra/terraform init -backend-config="path=C:/Users/<voce>/.revenda/terraform.tfstate"
terraform -chdir=infra/terraform apply -target=kind_cluster.revenda   # 1a etapa: cluster
terraform -chdir=infra/terraform apply                                # 2a etapa: o resto
```

O state contém os segredos em texto claro: fica fora do repositório (ADR-011). Variáveis úteis: `expor_banco_revenda` (padrão `true`), `kind_node_image`, `keycloak_imagem`.

Segredos (Git Bash): `kubectl -n identidade get secret keycloak-gestor -o jsonpath='{.data.GESTOR_PASSWORD}' | base64 -d` — veja `terraform output comandos_segredos`.

## Verificar no PC (não executável no ambiente de autoria)

1. `terraform init` + `terraform validate` + `terraform fmt -check -recursive`; versionar o `.terraform.lock.hcl` gerado.
2. Primeira subida (`04-subir-ambiente.ps1`): o cluster é criado pela biblioteca kind v0.31 do provider com a imagem do kind v0.33. Se falhar, usar `-var kind_node_image=` com a imagem v1.34.3 indicada em `variables.tf`.
3. `kubectl -n identidade logs deployment/keycloak` mostra `Realm 'revenda' imported`; `kubectl -n identidade logs job/keycloak-gestor-senha` termina com "reconciliado".
4. Token do gestor (Git Bash): `curl -s -d grant_type=password -d client_id=revenda-e2e -d username=gestor.loja --data-urlencode password=<senha> http://localhost:8180/realms/revenda/protocol/openid-connect/token`.
5. NetworkPolicy: `kubectl -n revenda run teste --rm -it --image=postgres:16.15-alpine --restart=Never -- pg_isready -h revenda-db -t 3` deve **falhar** (sem rótulo); com `--labels=app=revenda-api` deve responder. Idem para `keycloak-db`.
6. `kubectl top pods -A` (metrics-server) e `psql -h localhost -p 15432 -U revenda revenda` (banco exposto).
7. Segundo `terraform apply` sem mudanças: plano vazio (idempotência).
