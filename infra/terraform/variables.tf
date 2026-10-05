variable "cluster_nome" {
  description = "Nome do cluster kind criado pela CLI (infra/kind/cluster.yaml); os providers usam o contexto kind-<nome>."
  type        = string
  default     = "revenda"
}

variable "kubeconfig_path" {
  description = "Kubeconfig com o contexto kind-<cluster_nome> (gravado pela CLI kind). Vazio = ~/.kube/config (no Windows, %USERPROFILE%\\.kube\\config)."
  type        = string
  default     = ""
}

variable "pod_subnet" {
  description = "Faixa de IPs dos pods no kind: deve ser igual a networking.podSubnet de infra/kind/cluster.yaml (usada na NetworkPolicy do banco exposto)."
  type        = string
  default     = "10.244.0.0/16"
}

variable "expor_banco_revenda" {
  description = <<-EOT
    Publica o revenda-db no host (localhost:15432 -> NodePort 30432) para a demonstracao
    do banco no video. O mapeamento de porta do kind (infra/kind/cluster.yaml) existe
    sempre; esta variavel so muda o tipo do Service e a regra extra da NetworkPolicy.
  EOT
  type        = bool
  default     = true
}

variable "postgres_imagem" {
  description = "Imagem oficial do PostgreSQL 16 (fixada por versao menor)."
  type        = string
  default     = "postgres:16.15-alpine"
}

variable "metrics_server_chart_versao" {
  description = "Versao do chart metrics-server (https://kubernetes-sigs.github.io/metrics-server/)."
  type        = string
  default     = "3.14.0"
}
