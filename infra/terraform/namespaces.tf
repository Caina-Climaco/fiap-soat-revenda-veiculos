locals {
  rotulos_comuns = {
    "app.kubernetes.io/part-of"    = "revenda-veiculos"
    "app.kubernetes.io/managed-by" = "terraform"
  }
}

# Contextos Catalogo e Vendas (revenda-api, revenda-db, Job de migracao).
# O namespace identidade (Keycloak e o banco com os dados pessoais) NAO e deste
# repositorio: e criado e mantido pelo repositorio fiap-soat-revenda-identidade (ADR-014).
resource "kubernetes_namespace_v1" "revenda" {
  metadata {
    name   = "revenda"
    labels = local.rotulos_comuns
  }
}
