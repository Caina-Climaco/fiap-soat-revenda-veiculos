# Os providers kubernetes e helm sao configurados com as saidas do kind_cluster.
# Na primeira execucao esses valores so existem depois que o cluster e criado; os
# recursos tipados (*_v1) e o helm_release aceitam isso porque o cliente so e
# inicializado no apply. Para eliminar qualquer risco, o CD e o script
# 04-subir-ambiente.ps1 aplicam em duas etapas (docs/08-ci-cd-infra.md, secao 1.4):
#   terraform apply -target=kind_cluster.revenda
#   terraform apply

provider "kind" {}

provider "kubernetes" {
  host                   = kind_cluster.revenda.endpoint
  client_certificate     = kind_cluster.revenda.client_certificate
  client_key             = kind_cluster.revenda.client_key
  cluster_ca_certificate = kind_cluster.revenda.cluster_ca_certificate
}

provider "helm" {
  kubernetes = {
    host                   = kind_cluster.revenda.endpoint
    client_certificate     = kind_cluster.revenda.client_certificate
    client_key             = kind_cluster.revenda.client_key
    cluster_ca_certificate = kind_cluster.revenda.cluster_ca_certificate
  }
}
