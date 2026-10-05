# ADR-005: Kubernetes local (kind via CLI) com plataforma provisionada por Terraform, NodePort sem Ingress

**Status:** Aceito
**Atualizado por:** [ADR-014](ADR-014-identidade-em-repositorio-proprio.md)
**Data:** 2026-10-03

## Contexto

É preciso um ambiente de execução que suporte deploy automatizado e seja demonstrável em vídeo, sem acesso a cloud. A Fase 2 já usou kind e Terraform, mas o Terraform só criava o cluster: o banco foi instalado à mão.

## Alternativas avaliadas

| Alternativa | Prós | Contras |
|---|---|---|
| **kind criado pela CLI + plataforma por Terraform** (escolhida) | Kubernetes real em Docker; custo zero; reproduzível; experiência prévia; só binários assinados no caminho do deploy | Depende do PC ligado; sem URL pública; o cluster fica fora do state do Terraform |
| kind criado pelo Terraform (provider `tehcyx/kind`), plano original | Cluster e conteúdo num único state | Binário do provider sem assinatura de código, bloqueado pelo Smart App Control do Windows 11 (ver Decisão) |
| Docker Compose apenas | Simples | Não exercita orquestração, probes, HPA e rollout, que são temas do curso |
| Minikube ou k3d | Equivalentes | Sem vantagem sobre o kind, que já é conhecido |
| PaaS gratuito (Render etc.) | URL pública | Limites de memória incompatíveis com o Keycloak; hibernação; banco gratuito expira |
| Ingress (ingress-nginx) para expor os serviços | Roteamento por host e path | O projeto ingress-nginx foi descontinuado pela comunidade Kubernetes em 2026; é mais um componente sem necessidade real num ambiente local |

## Decisão

O cluster e o seu conteúdo são definidos por código, em duas partes:

- **Cluster:** criado pela **CLI `kind`** a partir de `infra/kind/cluster.yaml`. O arquivo define o cluster `revenda`, com um nó control-plane, a imagem do nó fixada por digest, o `podSubnet` e os `extraPortMappings` em 127.0.0.1: host 8080 → NodePort 30080 (API), host 8180 → NodePort 30180 (Keycloak) e host 15432 → NodePort 30432 (`revenda-db`, opcional). A criação é idempotente: o CD e o script `scripts/windows/04-subir-ambiente.ps1` só rodam `kind create cluster --config infra/kind/cluster.yaml --wait 120s` quando `kind get clusters` não lista `revenda`.
- **Conteúdo do cluster:** o **Terraform** (`infra/terraform`, providers `kubernetes`, `helm` e `random`) gerencia:
  - namespaces `revenda` e `identidade`;
  - metrics-server (via Helm);
  - as duas instâncias PostgreSQL e o Keycloak;
  - os Secrets gerados e as NetworkPolicies.

  Os providers usam o contexto `kind-revenda` do kubeconfig.

**Por que o cluster não é criado pelo Terraform:** o plano inicial usava o provider comunitário `tehcyx/kind`. No PC Windows 11 do autor, o binário `terraform-provider-kind.exe` não tem assinatura de código e foi bloqueado pelo **Smart App Control** ("An Application Control policy has blocked this file"). Desligar o Smart App Control foi descartado. Os providers da HashiCorp e as CLIs `kind`, `kubectl` e `docker` têm assinatura válida e executam normalmente. A CLI `kind` já era requisito do CD (`kind load docker-image`), então a mudança não acrescenta ferramenta.

A aplicação é implantada pelos manifestos em `k8s/` (kustomize) no pipeline de CD. Os serviços são expostos por **NodePort**.

## Consequências

### Positivas
- Ambiente recriável do zero com `kind create cluster --config infra/kind/cluster.yaml` seguido de `terraform apply`, ambos automatizados no CD e no script 04. Corrige a lacuna da Fase 2.
- Um único `terraform apply`, sem `-target`: o cluster já existe antes do plano, e os providers só leem o kubeconfig.
- Nenhum binário sem assinatura no caminho do deploy, o que é compatível com o Smart App Control do Windows 11.
- Sem port-forward manual: a API fica em `http://localhost:8080` e o Keycloak em `http://localhost:8180`.

### Negativas
- O state do Terraform fica local, na máquina do runner.
- O cluster fica fora do state do Terraform. Mudar `infra/kind/cluster.yaml` (portas, imagem do nó) só tem efeito recriando o cluster (`scripts/windows/05-destruir-ambiente.ps1` e depois `04-subir-ambiente.ps1`), e o `terraform destroy` não apaga o cluster (o script 05 roda `kind delete cluster` em seguida).
- NodePort não oferece TLS nem roteamento por host.

## Mitigações
- O state fica num diretório fixo fora do repositório (`.gitignore`). O procedimento de recriação está documentado em [08-ci-cd-infra.md](../08-ci-cd-infra.md).
- Para produção, o caminho documentado é Gateway API com TLS num cluster gerenciado.

## Atualização (ADR-014, 2026-10-04)

Atualizado por [ADR-014](ADR-014-identidade-em-repositorio-proprio.md). O cluster kind `revenda` e a decisão de criá-lo pela CLI continuam iguais, mas o cluster virou a **plataforma local compartilhada** por dois repositórios:

- O `infra/kind/cluster.yaml` é idêntico neste repositório e no [fiap-soat-revenda-identidade](https://github.com/Caina-Climaco/fiap-soat-revenda-identidade); o CD de cada um (e o script 04 de cada um) cria o cluster se ele faltar.
- O Terraform **deste** repositório gerencia só o namespace `revenda`: Secrets `revenda-db-credentials` e `revenda-webhook-secret`, `revenda-db`, a NetworkPolicy dele e o metrics-server. State: `%USERPROFILE%\.revenda\revenda-api.tfstate` (antes, `terraform.tfstate`, com tudo junto).
- O namespace `identidade` (Keycloak, `keycloak-db`, segredos, NetworkPolicy do `keycloak-db`, Job `keycloak-reconciliar`) é gerenciado pelo Terraform do repositório de identidade, com o state `%USERPROFILE%\.revenda\identidade.tfstate`.
- A porta 8180 → NodePort 30180 continua no `cluster.yaml`, mas o Service que a usa é implantado pelo repositório de identidade.
- O script `05-destruir-ambiente.ps1` deste repositório faz `terraform destroy` só da API; o cluster só é apagado com `-ApagarCluster` (o que derruba também a identidade). O `-Recriar` do script 04 foi removido: para recriar do zero, use o 05 com `-ApagarCluster` e suba de novo na ordem identidade → API.
