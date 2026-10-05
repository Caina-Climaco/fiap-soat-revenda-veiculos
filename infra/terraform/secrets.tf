# Segredos da API gerados pelo Terraform (ADR-011). Nomes e chaves sao contrato com a API
# e o CD. Os valores ficam apenas no state local e nos Secrets do namespace revenda.
# Rotacao: `terraform apply -replace=random_password.<nome>`. Senhas so com letras e
# digitos (seguras em URL, JDBC e shell). Os segredos do Keycloak sao do repositorio
# fiap-soat-revenda-identidade.

resource "random_password" "revenda_db" {
  length  = 32
  special = false
}

resource "random_password" "webhook_secret" {
  length  = 48
  special = false
}

resource "kubernetes_secret_v1" "revenda_db_credentials" {
  metadata {
    name      = "revenda-db-credentials"
    namespace = kubernetes_namespace_v1.revenda.metadata[0].name
    labels    = local.rotulos_comuns
  }
  type = "Opaque"
  data = {
    DB_USER     = "revenda"
    DB_PASSWORD = random_password.revenda_db.result
    DB_NAME     = "revenda"
  }
}

resource "kubernetes_secret_v1" "revenda_webhook_secret" {
  metadata {
    name      = "revenda-webhook-secret"
    namespace = kubernetes_namespace_v1.revenda.metadata[0].name
    labels    = local.rotulos_comuns
  }
  type = "Opaque"
  data = {
    WEBHOOK_SECRET = random_password.webhook_secret.result
  }
}
