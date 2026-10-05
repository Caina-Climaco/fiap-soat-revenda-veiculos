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
    api                   = "http://localhost:8080"
    swagger               = "http://localhost:8080/docs"
    oidc_issuer_consumido = "http://localhost:8180/realms/revenda (servico de identidade, outro repositorio)"
    revenda_db_host       = var.expor_banco_revenda ? "localhost:15432 (banco revenda)" : "nao exposto (use kubectl exec)"
  }
}

output "secrets" {
  description = "Secrets criados (namespace/nome => chaves). Contrato com o CD e os manifestos k8s/."
  # Lista estatica: referenciar `data` dos Secrets tornaria a saida sensivel.
  value = {
    "revenda/revenda-db-credentials" = ["DB_USER", "DB_PASSWORD", "DB_NAME"]
    "revenda/revenda-webhook-secret" = ["WEBHOOK_SECRET"]
  }
  depends_on = [
    kubernetes_secret_v1.revenda_db_credentials,
    kubernetes_secret_v1.revenda_webhook_secret,
  ]
}

output "comandos_segredos" {
  description = "Como ler os segredos com kubectl (Git Bash/Linux; no PowerShell, decodifique com [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String(...)))."
  value = {
    webhook_secret   = "kubectl -n revenda get secret revenda-webhook-secret -o jsonpath='{.data.WEBHOOK_SECRET}' | base64 -d"
    senha_revenda_db = "kubectl -n revenda get secret revenda-db-credentials -o jsonpath='{.data.DB_PASSWORD}' | base64 -d"
  }
}

output "comandos_uteis" {
  description = "Atalhos para a demonstracao."
  value = {
    pods         = "kubectl -n revenda get pods -o wide"
    psql_revenda = "kubectl -n revenda exec -it statefulset/revenda-db -- psql -U revenda -d revenda"
    hpa          = "kubectl -n revenda get hpa revenda-api"
    top          = "kubectl -n revenda top pods"
  }
}
