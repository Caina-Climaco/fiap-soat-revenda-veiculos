# NetworkPolicies de entrada do banco e da API (docs/07-seguranca-lgpd.md, secao 3.3).
# O CNI padrao do kind (kindnet) aplica NetworkPolicy desde o kind v0.24; ver
# infra/README.md ("Checklist de verificacao manual") para o teste de bloqueio.
#
# Somente regras de ENTRADA (policy_types = ["Ingress"]): a saida dos pods (DNS, JWKS,
# banco) nao e restringida.

# revenda-db: aceita apenas a API, o Job de migracao e o CronJob de saneamento (mesmo namespace).
resource "kubernetes_network_policy_v1" "revenda_db" {
  metadata {
    name      = "revenda-db-somente-api"
    namespace = kubernetes_namespace_v1.revenda.metadata[0].name
    labels    = local.rotulos_comuns
  }

  spec {
    pod_selector {
      match_labels = {
        app = "revenda-db"
      }
    }

    policy_types = ["Ingress"]

    ingress {
      from {
        pod_selector {
          match_expressions {
            key      = "app"
            operator = "In"
            values   = ["revenda-api", "revenda-migracao", "revenda-saneamento"]
          }
        }
      }
      ports {
        port     = "5432"
        protocol = "TCP"
      }
    }

    # Demonstracao do banco no host (localhost:15432 -> NodePort 30432). O trafego de
    # NodePort chega ao pod com origem no gateway do no (primeiro IP da faixa de pods,
    # apos o SNAT do kube-proxy) ou num IP fora da faixa de pods; os demais pods
    # continuam bloqueados.
    dynamic "ingress" {
      for_each = var.expor_banco_revenda ? [1] : []
      content {
        from {
          ip_block {
            cidr   = "0.0.0.0/0"
            except = [var.pod_subnet]
          }
        }
        from {
          ip_block {
            cidr = "${cidrhost(var.pod_subnet, 1)}/32"
          }
        }
        ports {
          port     = "5432"
          protocol = "TCP"
        }
      }
    }
  }
}

# revenda-api: dentro do cluster, so o Kong (namespace gateway) chega a API, e o Prometheus
# (namespace observabilidade) le /metrics. Nenhum outro namespace (por exemplo, identidade)
# alcanca a API diretamente: o caminho de entrada e sempre o API Gateway (ADR-015).
# O trafego do proprio no (probes do kubelet) entra pelo IP do no / gateway da faixa de
# pods, liberado pelas duas ultimas regras, como no revenda-db.
resource "kubernetes_network_policy_v1" "revenda_api" {
  metadata {
    name      = "revenda-api-somente-gateway"
    namespace = kubernetes_namespace_v1.revenda.metadata[0].name
    labels    = local.rotulos_comuns
  }

  spec {
    pod_selector {
      match_labels = {
        app = "revenda-api"
      }
    }

    policy_types = ["Ingress"]

    ingress {
      from {
        namespace_selector {
          match_labels = {
            "kubernetes.io/metadata.name" = kubernetes_namespace_v1.gateway.metadata[0].name
          }
        }
        pod_selector {
          match_labels = {
            app = "kong"
          }
        }
      }
      from {
        namespace_selector {
          match_labels = {
            "kubernetes.io/metadata.name" = kubernetes_namespace_v1.observabilidade.metadata[0].name
          }
        }
        pod_selector {
          match_labels = {
            app = "prometheus"
          }
        }
      }
      ports {
        port     = "8000"
        protocol = "TCP"
      }
    }

    ingress {
      from {
        ip_block {
          cidr   = "0.0.0.0/0"
          except = [var.pod_subnet]
        }
      }
      from {
        ip_block {
          cidr = "${cidrhost(var.pod_subnet, 1)}/32"
        }
      }
      ports {
        port     = "8000"
        protocol = "TCP"
      }
    }
  }
}
