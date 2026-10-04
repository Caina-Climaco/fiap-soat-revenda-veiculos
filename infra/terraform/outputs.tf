# Nenhuma saida contem senha (nem como sensitive): os valores ficam so no state e nos
# Secrets do cluster. Para ler um segredo, use os comandos em `comandos_segredos`.

output "cluster" {
  description = "Nome do cluster kind e contexto do kubectl."
  value = {
    nome            = var.cluster_nome
    contexto        = local.kube_contexto
    kubeconfig_path = local.kubeconfig_path
    config_kind     = "infra/kind/cluster.yaml"
  }
}

output "urls" {
  description = "Enderecos locais (apenas 127.0.0.1)."
  value = {
    api                    = "http://localhost:8080"
    swagger                = "http://localhost:8080/docs"
    keycloak               = "http://localhost:8180"
    keycloak_admin_console = "http://localhost:8180/admin/"
    conta_do_cliente       = "http://localhost:8180/realms/revenda/account"
    oidc_issuer            = "http://localhost:8180/realms/revenda"
    oidc_jwks_interno      = "http://keycloak.identidade.svc.cluster.local:8080/realms/revenda/protocol/openid-connect/certs"
    revenda_db_host        = var.expor_banco_revenda ? "localhost:15432 (banco revenda)" : "nao exposto (use kubectl exec)"
  }
}

output "secrets" {
  description = "Secrets criados (namespace/nome => chaves). Contrato da secao 14.3."
  # Lista estatica: referenciar `data` dos Secrets tornaria a saida sensivel.
  value = {
    "revenda/revenda-db-credentials"     = ["DB_USER", "DB_PASSWORD", "DB_NAME"]
    "revenda/revenda-webhook-secret"     = ["WEBHOOK_SECRET"]
    "identidade/keycloak-db-credentials" = ["KC_DB_USERNAME", "KC_DB_PASSWORD"]
    "identidade/keycloak-admin"          = ["KC_BOOTSTRAP_ADMIN_USERNAME", "KC_BOOTSTRAP_ADMIN_PASSWORD"]
    "identidade/keycloak-gestor"         = ["GESTOR_PASSWORD"]
  }
  depends_on = [
    kubernetes_secret_v1.revenda_db_credentials,
    kubernetes_secret_v1.revenda_webhook_secret,
    kubernetes_secret_v1.keycloak_db_credentials,
    kubernetes_secret_v1.keycloak_admin,
    kubernetes_secret_v1.keycloak_gestor,
  ]
}

output "comandos_segredos" {
  description = "Como ler os segredos com kubectl (Git Bash/Linux; no PowerShell, decodifique com [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String(...)))."
  value = {
    senha_gestor     = "kubectl -n identidade get secret keycloak-gestor -o jsonpath='{.data.GESTOR_PASSWORD}' | base64 -d"
    admin_keycloak   = "kubectl -n identidade get secret keycloak-admin -o jsonpath='{.data.KC_BOOTSTRAP_ADMIN_PASSWORD}' | base64 -d"
    webhook_secret   = "kubectl -n revenda get secret revenda-webhook-secret -o jsonpath='{.data.WEBHOOK_SECRET}' | base64 -d"
    senha_revenda_db = "kubectl -n revenda get secret revenda-db-credentials -o jsonpath='{.data.DB_PASSWORD}' | base64 -d"
  }
}

output "comandos_uteis" {
  description = "Atalhos para a demonstracao."
  value = {
    pods          = "kubectl get pods -A -o wide"
    psql_revenda  = "kubectl -n revenda exec -it statefulset/revenda-db -- psql -U revenda -d revenda"
    psql_keycloak = "kubectl -n identidade exec -it statefulset/keycloak-db -- psql -U keycloak -d keycloak"
    logs_keycloak = "kubectl -n identidade logs deployment/keycloak --tail=100"
    hpa           = "kubectl -n revenda get hpa revenda-api"
    top           = "kubectl top pods -A"
  }
}
