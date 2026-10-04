locals {
  # O provider grava o contexto kind-<nome> neste arquivo (mescla com o existente).
  # Sem um caminho explicito ele gravaria "<diretorio atual>/revenda-config", dentro do repositorio.
  kubeconfig_path = var.kubeconfig_path != "" ? var.kubeconfig_path : pathexpand("~/.kube/config")
}

# Cluster kind de um no (control-plane). Servicos publicados por NodePort + extraPortMappings
# (ADR-005). As portas do host escutam apenas em 127.0.0.1: nada fica exposto na rede local.
resource "kind_cluster" "revenda" {
  name            = var.cluster_nome
  node_image      = var.kind_node_image
  wait_for_ready  = true
  kubeconfig_path = local.kubeconfig_path

  kind_config {
    kind        = "Cluster"
    api_version = "kind.x-k8s.io/v1alpha4"

    networking {
      pod_subnet = var.pod_subnet
    }

    node {
      role = "control-plane"

      # API (Service revenda-api, criado pelos manifestos em k8s/base)
      extra_port_mappings {
        container_port = 30080
        host_port      = 8080
        listen_address = "127.0.0.1"
        protocol       = "TCP"
      }

      # Keycloak
      extra_port_mappings {
        container_port = 30180
        host_port      = 8180
        listen_address = "127.0.0.1"
        protocol       = "TCP"
      }

      # revenda-db (so responde quando expor_banco_revenda = true; ver postgres.tf)
      extra_port_mappings {
        container_port = 30432
        host_port      = 15432
        listen_address = "127.0.0.1"
        protocol       = "TCP"
      }
    }
  }

  lifecycle {
    # kubeconfig_path e ForceNew no provider. O valor expandido de "~" pode variar na
    # forma (PowerShell x Git Bash), o que recriaria o cluster sem necessidade.
    ignore_changes = [kubeconfig_path]
  }
}
