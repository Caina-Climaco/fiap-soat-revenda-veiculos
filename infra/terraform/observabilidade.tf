# Monitoramento (ADR-016): Prometheus + Grafana no namespace observabilidade.
#   Prometheus  coleta a API (namespace revenda) e o Kong (namespace gateway) por descoberta
#               de pods e avalia as regras de alerta de infra/observabilidade/alertas.yml.
#               localhost:9090 -> NodePort 30900.
#   Grafana     fonte de dados e painel provisionados (infra/observabilidade/grafana).
#               localhost:3000 -> NodePort 30300; leitura anonima (Viewer), admin com senha
#               gerada no Secret grafana-admin.
# Sem armazenamento persistente: e um ambiente de demonstracao (retencao de 2 dias no pod).

locals {
  dir_observabilidade = "${path.module}/../observabilidade"
  prometheus_config   = file("${local.dir_observabilidade}/prometheus.yml")
  prometheus_alertas  = file("${local.dir_observabilidade}/alertas.yml")
  grafana_fonte       = file("${local.dir_observabilidade}/grafana/fonte-de-dados.yml")
  grafana_provedor    = file("${local.dir_observabilidade}/grafana/paineis.yml")
  grafana_painel      = file("${local.dir_observabilidade}/grafana/painel-revenda.json")
  # Namespaces que o Prometheus pode observar (leitura de pods, nada mais)
  namespaces_coletados = {
    revenda = kubernetes_namespace_v1.revenda.metadata[0].name
    gateway = kubernetes_namespace_v1.gateway.metadata[0].name
  }
}

resource "kubernetes_namespace_v1" "observabilidade" {
  metadata {
    name   = "observabilidade"
    labels = local.rotulos_comuns
  }
}

# ---- Prometheus --------------------------------------------------------------------

resource "kubernetes_service_account_v1" "prometheus" {
  metadata {
    name      = "prometheus"
    namespace = kubernetes_namespace_v1.observabilidade.metadata[0].name
    labels    = local.rotulos_comuns
  }
}

resource "kubernetes_role_v1" "prometheus_leitura" {
  for_each = local.namespaces_coletados

  metadata {
    name      = "prometheus-leitura-pods"
    namespace = each.value
    labels    = local.rotulos_comuns
  }
  rule {
    api_groups = [""]
    resources  = ["pods"]
    verbs      = ["get", "list", "watch"]
  }
}

resource "kubernetes_role_binding_v1" "prometheus_leitura" {
  for_each = local.namespaces_coletados

  metadata {
    name      = "prometheus-leitura-pods"
    namespace = each.value
    labels    = local.rotulos_comuns
  }
  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Role"
    name      = kubernetes_role_v1.prometheus_leitura[each.key].metadata[0].name
  }
  subject {
    kind      = "ServiceAccount"
    name      = kubernetes_service_account_v1.prometheus.metadata[0].name
    namespace = kubernetes_namespace_v1.observabilidade.metadata[0].name
  }
}

resource "kubernetes_config_map_v1" "prometheus" {
  metadata {
    name      = "prometheus-config"
    namespace = kubernetes_namespace_v1.observabilidade.metadata[0].name
    labels    = local.rotulos_comuns
  }
  data = {
    "prometheus.yml" = local.prometheus_config
    "alertas.yml"    = local.prometheus_alertas
  }
}

resource "kubernetes_deployment_v1" "prometheus" {
  metadata {
    name      = "prometheus"
    namespace = kubernetes_namespace_v1.observabilidade.metadata[0].name
    labels    = merge(local.rotulos_comuns, { app = "prometheus" })
  }

  spec {
    replicas = 1
    strategy {
      type = "Recreate"
    }
    selector {
      match_labels = {
        app = "prometheus"
      }
    }

    template {
      metadata {
        labels = merge(local.rotulos_comuns, { app = "prometheus" })
        annotations = {
          "revenda.io/config-sha256" = sha256("${local.prometheus_config}${local.prometheus_alertas}")
        }
      }

      spec {
        service_account_name            = kubernetes_service_account_v1.prometheus.metadata[0].name
        automount_service_account_token = true
        enable_service_links            = false

        security_context {
          run_as_non_root = true
          run_as_user     = 65534
          run_as_group    = 65534
          fs_group        = 65534
          seccomp_profile {
            type = "RuntimeDefault"
          }
        }

        container {
          name              = "prometheus"
          image             = var.prometheus_imagem
          image_pull_policy = "IfNotPresent"
          args = [
            "--config.file=/etc/prometheus/prometheus.yml",
            "--storage.tsdb.path=/prometheus",
            "--storage.tsdb.retention.time=2d",
          ]

          port {
            name           = "http"
            container_port = 9090
            protocol       = "TCP"
          }

          resources {
            requests = {
              cpu    = "100m"
              memory = "256Mi"
            }
            limits = {
              cpu    = "1"
              memory = "768Mi"
            }
          }

          security_context {
            allow_privilege_escalation = false
            read_only_root_filesystem  = true
            capabilities {
              drop = ["ALL"]
            }
          }

          readiness_probe {
            http_get {
              path = "/-/ready"
              port = "http"
            }
            period_seconds  = 5
            timeout_seconds = 3
          }
          liveness_probe {
            http_get {
              path = "/-/healthy"
              port = "http"
            }
            initial_delay_seconds = 15
            period_seconds        = 15
          }

          volume_mount {
            name       = "config"
            mount_path = "/etc/prometheus"
            read_only  = true
          }
          volume_mount {
            name       = "dados"
            mount_path = "/prometheus"
          }
        }

        volume {
          name = "config"
          config_map {
            name = kubernetes_config_map_v1.prometheus.metadata[0].name
          }
        }
        volume {
          name = "dados"
          empty_dir {}
        }
      }
    }
  }

  wait_for_rollout = true
  timeouts {
    create = "5m"
    update = "5m"
  }

  depends_on = [kubernetes_role_binding_v1.prometheus_leitura]
}

resource "kubernetes_service_v1" "prometheus" {
  metadata {
    name      = "prometheus"
    namespace = kubernetes_namespace_v1.observabilidade.metadata[0].name
    labels    = merge(local.rotulos_comuns, { app = "prometheus" })
  }
  spec {
    type = "NodePort"
    selector = {
      app = "prometheus"
    }
    port {
      name        = "http"
      port        = 9090
      target_port = "http"
      node_port   = 30900
      protocol    = "TCP"
    }
  }
}

# ---- Grafana -----------------------------------------------------------------------

resource "random_password" "grafana_admin" {
  length  = 24
  special = false
}

resource "kubernetes_secret_v1" "grafana_admin" {
  metadata {
    name      = "grafana-admin"
    namespace = kubernetes_namespace_v1.observabilidade.metadata[0].name
    labels    = local.rotulos_comuns
  }
  type = "Opaque"
  data = {
    GF_SECURITY_ADMIN_USER     = "admin"
    GF_SECURITY_ADMIN_PASSWORD = random_password.grafana_admin.result
  }
}

resource "kubernetes_config_map_v1" "grafana_provisionamento" {
  metadata {
    name      = "grafana-provisionamento"
    namespace = kubernetes_namespace_v1.observabilidade.metadata[0].name
    labels    = local.rotulos_comuns
  }
  data = {
    "fonte-de-dados.yml" = local.grafana_fonte
    "paineis.yml"        = local.grafana_provedor
  }
}

resource "kubernetes_config_map_v1" "grafana_paineis" {
  metadata {
    name      = "grafana-paineis"
    namespace = kubernetes_namespace_v1.observabilidade.metadata[0].name
    labels    = local.rotulos_comuns
  }
  data = {
    "painel-revenda.json" = local.grafana_painel
  }
}

resource "kubernetes_deployment_v1" "grafana" {
  metadata {
    name      = "grafana"
    namespace = kubernetes_namespace_v1.observabilidade.metadata[0].name
    labels    = merge(local.rotulos_comuns, { app = "grafana" })
  }

  spec {
    replicas = 1
    strategy {
      type = "Recreate"
    }
    selector {
      match_labels = {
        app = "grafana"
      }
    }

    template {
      metadata {
        labels = merge(local.rotulos_comuns, { app = "grafana" })
        annotations = {
          "revenda.io/config-sha256" = sha256("${local.grafana_fonte}${local.grafana_provedor}${local.grafana_painel}")
        }
      }

      spec {
        automount_service_account_token = false
        enable_service_links            = false

        security_context {
          run_as_non_root = true
          run_as_user     = 472
          run_as_group    = 0
          fs_group        = 472
          seccomp_profile {
            type = "RuntimeDefault"
          }
        }

        container {
          name              = "grafana"
          image             = var.grafana_imagem
          image_pull_policy = "IfNotPresent"

          port {
            name           = "http"
            container_port = 3000
            protocol       = "TCP"
          }

          # GF_SECURITY_ADMIN_USER / GF_SECURITY_ADMIN_PASSWORD
          env_from {
            secret_ref {
              name = kubernetes_secret_v1.grafana_admin.metadata[0].name
            }
          }
          # Raiz somente leitura: log so no console (o padrao da imagem tambem grava em arquivo)
          env {
            name  = "GF_LOG_MODE"
            value = "console"
          }
          env {
            name  = "GF_AUTH_ANONYMOUS_ENABLED"
            value = "true"
          }
          env {
            name  = "GF_AUTH_ANONYMOUS_ORG_ROLE"
            value = "Viewer"
          }
          env {
            name  = "GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH"
            value = "/var/lib/grafana/paineis/painel-revenda.json"
          }
          env {
            name  = "GF_USERS_DEFAULT_LANGUAGE"
            value = "pt-BR"
          }
          env {
            name  = "GF_ANALYTICS_REPORTING_ENABLED"
            value = "false"
          }
          env {
            name  = "GF_ANALYTICS_CHECK_FOR_UPDATES"
            value = "false"
          }
          env {
            name  = "GF_NEWS_NEWS_FEED_ENABLED"
            value = "false"
          }

          resources {
            requests = {
              cpu    = "50m"
              memory = "128Mi"
            }
            limits = {
              cpu    = "1"
              memory = "512Mi"
            }
          }

          security_context {
            allow_privilege_escalation = false
            read_only_root_filesystem  = true
            capabilities {
              drop = ["ALL"]
            }
          }

          readiness_probe {
            http_get {
              path = "/api/health"
              port = "http"
            }
            period_seconds  = 5
            timeout_seconds = 3
          }
          liveness_probe {
            http_get {
              path = "/api/health"
              port = "http"
            }
            initial_delay_seconds = 30
            period_seconds        = 15
          }

          volume_mount {
            name       = "dados"
            mount_path = "/var/lib/grafana"
          }
          volume_mount {
            name       = "paineis"
            mount_path = "/var/lib/grafana/paineis"
            read_only  = true
          }
          volume_mount {
            name       = "provisionamento"
            mount_path = "/etc/grafana/provisioning/datasources/fonte-de-dados.yml"
            sub_path   = "fonte-de-dados.yml"
            read_only  = true
          }
          volume_mount {
            name       = "provisionamento"
            mount_path = "/etc/grafana/provisioning/dashboards/paineis.yml"
            sub_path   = "paineis.yml"
            read_only  = true
          }
          volume_mount {
            name       = "tmp"
            mount_path = "/tmp"
          }
        }

        volume {
          name = "dados"
          empty_dir {}
        }
        volume {
          name = "paineis"
          config_map {
            name = kubernetes_config_map_v1.grafana_paineis.metadata[0].name
          }
        }
        volume {
          name = "provisionamento"
          config_map {
            name = kubernetes_config_map_v1.grafana_provisionamento.metadata[0].name
          }
        }
        volume {
          name = "tmp"
          empty_dir {}
        }
      }
    }
  }

  wait_for_rollout = true
  timeouts {
    create = "5m"
    update = "5m"
  }
}

resource "kubernetes_service_v1" "grafana" {
  metadata {
    name      = "grafana"
    namespace = kubernetes_namespace_v1.observabilidade.metadata[0].name
    labels    = merge(local.rotulos_comuns, { app = "grafana" })
  }
  spec {
    type = "NodePort"
    selector = {
      app = "grafana"
    }
    port {
      name        = "http"
      port        = 3000
      target_port = "http"
      node_port   = 30300
      protocol    = "TCP"
    }
  }
}
