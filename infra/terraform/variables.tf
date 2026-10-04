variable "cluster_nome" {
  description = "Nome do cluster kind (o contexto do kubectl sera kind-<nome>)."
  type        = string
  default     = "revenda"
}

variable "kind_node_image" {
  description = <<-EOT
    Imagem do no do kind, fixada por digest. Vem das notas do release kind v0.33.0
    (mesma versao da CLI `kind` do PC, usada no CD para `kind load`, que exige
    CLI >= v0.32 com as imagens novas). Kubernetes 1.34 = mesmo minor do kubectl 1.34.
    O cluster e criado pela biblioteca kind v0.31.0 embutida no provider tehcyx/kind
    0.11.0; se a criacao falhar por incompatibilidade, use a imagem do release v0.31.0:
    kindest/node:v1.34.3@sha256:08497ee19eace7b4b5348db5c6a1591d7752b164530a36f855cb0f2bdcbadd48
    (trocar a imagem RECRIA o cluster: node_image e ForceNew).
  EOT
  type        = string
  default     = "kindest/node:v1.34.11@sha256:44e222ee2132dab25ff87301682f89eb82c7880ea3a1bf543bfe9708fd08d67d"
}

variable "kubeconfig_path" {
  description = "Arquivo kubeconfig onde o contexto do cluster e gravado. Vazio = ~/.kube/config (no Windows, %USERPROFILE%\\.kube\\config)."
  type        = string
  default     = ""
}

variable "pod_subnet" {
  description = "Faixa de IPs dos pods no kind (usada tambem na NetworkPolicy do banco exposto)."
  type        = string
  default     = "10.244.0.0/16"
}

variable "expor_banco_revenda" {
  description = <<-EOT
    Publica o revenda-db no host (localhost:15432 -> NodePort 30432) para a demonstracao
    do banco no video. O mapeamento de porta do kind existe sempre; esta variavel so
    muda o tipo do Service e a regra extra da NetworkPolicy (nao recria o cluster).
  EOT
  type        = bool
  default     = true
}

variable "postgres_imagem" {
  description = "Imagem oficial do PostgreSQL 16 (fixada por versao menor)."
  type        = string
  default     = "postgres:16.15-alpine"
}

variable "keycloak_imagem" {
  description = "Imagem oficial do Keycloak (contrato da secao 14.2: linha 26.4, fixada no patch)."
  type        = string
  default     = "quay.io/keycloak/keycloak:26.4.16"
}

variable "metrics_server_chart_versao" {
  description = "Versao do chart metrics-server (https://kubernetes-sigs.github.io/metrics-server/)."
  type        = string
  default     = "3.14.0"
}

variable "keycloak_admin_usuario" {
  description = "Usuario do admin bootstrap do Keycloak (realm master). A senha e gerada."
  type        = string
  default     = "admin"
}
