# NetworkPolicies de entrada dos bancos (docs/07-seguranca-lgpd.md, secao 3.3).
# O CNI padrao do kind (kindnet) aplica NetworkPolicy desde o kind v0.24; ver
# infra/README.md ("Verificar no PC") para o teste de bloqueio.
#
# Somente regras de ENTRADA (policy_types = ["Ingress"]): a saida dos pods (DNS, JWKS,
# banco) nao e restringida.

# revenda-db: aceita apenas a API e o Job de migracao (mesmo namespace).
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
            values   = ["revenda-api", "revenda-migracao"]
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
