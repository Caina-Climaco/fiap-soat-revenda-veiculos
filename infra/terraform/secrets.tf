# Segredos gerados pelo Terraform (ADR-011). Nomes e chaves sao contrato com a API, o
# Keycloak e o CD (design brief, secao 14.3). Os valores ficam apenas no state local e
# nos Secrets do cluster. Rotacao: `terraform apply -replace=random_password.<nome>`.
#
# Senhas de banco e do admin: so letras e digitos (seguras em URL, JDBC e shell).
# Senha do gestor: entra no arquivo de realm por placeholder ${GESTOR_PASSWORD}, que o
# Keycloak substitui no texto ANTES de interpretar o JSON; por isso os especiais
# permitidos excluem aspas, barra invertida, "$", "{" e "}".

resource "random_password" "revenda_db" {
  length  = 32
  special = false
}

resource "random_password" "keycloak_db" {
  length  = 32
  special = false
}

resource "random_password" "keycloak_admin" {
  length  = 24
  special = false
}

resource "random_password" "keycloak_gestor" {
  length           = 20
  special          = true
  override_special = "!#%*-_=+"
  min_upper        = 2
  min_lower        = 2
  min_numeric      = 2
  min_special      = 1
}

resource "random_password" "webhook_secret" {
  length  = 48
  special = false
}

# ---- namespace revenda -----------------------------------------------------

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

# ---- namespace identidade --------------------------------------------------

resource "kubernetes_secret_v1" "keycloak_db_credentials" {
  metadata {
    name      = "keycloak-db-credentials"
    namespace = kubernetes_namespace_v1.identidade.metadata[0].name
    labels    = local.rotulos_comuns
  }
  type = "Opaque"
  data = {
    KC_DB_USERNAME = "keycloak"
    KC_DB_PASSWORD = random_password.keycloak_db.result
  }
}

resource "kubernetes_secret_v1" "keycloak_admin" {
  metadata {
    name      = "keycloak-admin"
    namespace = kubernetes_namespace_v1.identidade.metadata[0].name
    labels    = local.rotulos_comuns
  }
  type = "Opaque"
  data = {
    KC_BOOTSTRAP_ADMIN_USERNAME = var.keycloak_admin_usuario
    KC_BOOTSTRAP_ADMIN_PASSWORD = random_password.keycloak_admin.result
  }
}

resource "kubernetes_secret_v1" "keycloak_gestor" {
  metadata {
    name      = "keycloak-gestor"
    namespace = kubernetes_namespace_v1.identidade.metadata[0].name
    labels    = local.rotulos_comuns
  }
  type = "Opaque"
  data = {
    GESTOR_PASSWORD = random_password.keycloak_gestor.result
  }
}
