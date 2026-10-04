locals {
  rotulos_comuns = {
    "app.kubernetes.io/part-of"    = "revenda-veiculos"
    "app.kubernetes.io/managed-by" = "terraform"
  }
}

# Contextos Catalogo e Vendas (revenda-api, revenda-db, Job de migracao)
resource "kubernetes_namespace_v1" "revenda" {
  metadata {
    name   = "revenda"
    labels = local.rotulos_comuns
  }
}

# Contexto Identidade e Acesso (Keycloak e o seu banco) - dados pessoais apartados
resource "kubernetes_namespace_v1" "identidade" {
  metadata {
    name   = "identidade"
    labels = local.rotulos_comuns
  }
}
