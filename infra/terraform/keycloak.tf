# Keycloak (contexto Identidade e Acesso) no namespace identidade - ADR-001.
# Realm "revenda" importado na inicializacao (--import-realm) a partir de
# keycloak/realm-revenda.json, montado por ConfigMap em /opt/keycloak/data/import.
#
# Import na inicializacao (Keycloak 26.7, imagem 26.7.1; conferido na documentacao "Importing and
# exporting realms" e no codigo-fonte da tag 26.7.1):
# - estrategia IGNORE_EXISTING: o realm so e criado na PRIMEIRA subida; mudancas
#   posteriores no JSON nao sao reaplicadas enquanto o realm existir no keycloak-db;
# - placeholders ${VAR} sao substituidos no TEXTO do arquivo pelas variaveis de ambiente
#   do container antes da leitura do JSON (AbstractFileBasedImportProvider); um
#   placeholder sem variavel correspondente fica inalterado (ex.: ${username} do perfil).
#   E assim que ${GESTOR_PASSWORD} vira a senha inicial do gestor.loja.
# Como o import nao reaplica a senha (IGNORE_EXISTING), o Job keycloak-gestor-senha
# (abaixo) a reconcilia com o Secret keycloak-gestor via kcadm.sh a cada mudanca.

locals {
  keycloak_rotulos = merge(local.rotulos_comuns, {
    app                           = "keycloak"
    "app.kubernetes.io/name"      = "keycloak"
    "app.kubernetes.io/instance"  = "keycloak"
    "app.kubernetes.io/component" = "identidade"
  })
}

resource "kubernetes_config_map_v1" "keycloak_realm" {
  metadata {
    name      = "keycloak-realm-revenda"
    namespace = kubernetes_namespace_v1.identidade.metadata[0].name
    labels    = local.rotulos_comuns
  }

  # O nome do arquivo NAO pode conter "-realm.json" (esse padrao e reservado ao formato
  # de diretorio de export e seria ignorado pelo import de arquivo unico).
  data = {
    "realm-revenda.json" = file("${path.module}/../../keycloak/realm-revenda.json")
  }
}

resource "kubernetes_deployment_v1" "keycloak" {
  metadata {
    name      = "keycloak"
    namespace = kubernetes_namespace_v1.identidade.metadata[0].name
    labels    = local.keycloak_rotulos
  }

  spec {
    replicas = 1

    # start-dev usa cache local: nunca duas instancias ao mesmo tempo no mesmo banco.
    strategy {
      type = "Recreate"
    }

    selector {
      match_labels = {
        app = "keycloak"
      }
    }

    template {
      metadata {
        labels = local.keycloak_rotulos
        annotations = {
          # Reinicia o pod quando o arquivo de realm muda (o import continua IGNORE_EXISTING).
          "revenda.io/realm-sha256" = sha256(kubernetes_config_map_v1.keycloak_realm.data["realm-revenda.json"])
        }
      }

      spec {
        automount_service_account_token  = false
        enable_service_links             = false
        termination_grace_period_seconds = 30

        # UID 1000 = usuario "keycloak" da imagem oficial.
        security_context {
          run_as_non_root = true
          run_as_user     = 1000
          run_as_group    = 0
          seccomp_profile {
            type = "RuntimeDefault"
          }
        }

        container {
          name              = "keycloak"
          image             = var.keycloak_imagem
          image_pull_policy = "IfNotPresent"
          args              = ["start-dev", "--import-realm"]

          port {
            name           = "http"
            container_port = 8080
            protocol       = "TCP"
          }
          port {
            name           = "management"
            container_port = 9000
            protocol       = "TCP"
          }

          # KC_DB_USERNAME / KC_DB_PASSWORD
          env_from {
            secret_ref {
              name = kubernetes_secret_v1.keycloak_db_credentials.metadata[0].name
            }
          }
          # KC_BOOTSTRAP_ADMIN_USERNAME / KC_BOOTSTRAP_ADMIN_PASSWORD
          env_from {
            secret_ref {
              name = kubernetes_secret_v1.keycloak_admin.metadata[0].name
            }
          }
          # GESTOR_PASSWORD (placeholder do realm-revenda.json)
          env_from {
            secret_ref {
              name = kubernetes_secret_v1.keycloak_gestor.metadata[0].name
            }
          }

          env {
            name  = "KC_DB"
            value = "postgres"
          }
          env {
            name  = "KC_DB_URL"
            value = "jdbc:postgresql://keycloak-db.identidade.svc.cluster.local:5432/keycloak"
          }
          # Emissor publico dos tokens: iss = http://localhost:8180/realms/revenda
          env {
            name  = "KC_HOSTNAME"
            value = "http://localhost:8180"
          }
          # Chamadas internas (JWKS pela API em keycloak.identidade.svc:8080) usam o host da requisicao
          env {
            name  = "KC_HOSTNAME_BACKCHANNEL_DYNAMIC"
            value = "true"
          }
          env {
            name  = "KC_HTTP_ENABLED"
            value = "true"
          }
          env {
            name  = "KC_HEALTH_ENABLED"
            value = "true"
          }
          env {
            name  = "KC_LOG_LEVEL"
            value = "info"
          }
          # Heap: padrao da imagem (MaxRAMPercentage=70 do limite de 1536Mi, ~1 GiB)

          resources {
            requests = {
              cpu    = "500m"
              memory = "768Mi"
            }
            limits = {
              cpu    = "2"
              memory = "1536Mi"
            }
          }

          security_context {
            allow_privilege_escalation = false
            # start-dev recompila a configuracao em /opt/keycloak: raiz precisa ser gravavel
            read_only_root_filesystem = false
            capabilities {
              drop = ["ALL"]
            }
          }

          # Primeira subida: build do start-dev + migracao do schema + import do realm.
          # Ate 10 minutos (120 x 5 s) antes de o kubelet desistir.
          startup_probe {
            http_get {
              path = "/health/ready"
              port = "management"
            }
            period_seconds    = 5
            timeout_seconds   = 3
            failure_threshold = 120
          }

          readiness_probe {
            http_get {
              path = "/health/ready"
              port = "management"
            }
            period_seconds    = 10
            timeout_seconds   = 3
            failure_threshold = 3
          }

          liveness_probe {
            http_get {
              path = "/health/live"
              port = "management"
            }
            period_seconds    = 15
            timeout_seconds   = 3
            failure_threshold = 4
          }

          volume_mount {
            name       = "realm"
            mount_path = "/opt/keycloak/data/import"
            read_only  = true
          }
        }

        volume {
          name = "realm"
          config_map {
            name = kubernetes_config_map_v1.keycloak_realm.metadata[0].name
          }
        }
      }
    }
  }

  wait_for_rollout = true

  timeouts {
    create = "15m"
    update = "15m"
  }

  # O banco precisa estar pronto antes da primeira subida (senao o pod reinicia em loop)
  depends_on = [
    kubernetes_stateful_set_v1.postgres,
    kubernetes_service_v1.postgres,
    kubernetes_network_policy_v1.keycloak_db,
  ]
}

resource "kubernetes_service_v1" "keycloak" {
  metadata {
    name      = "keycloak"
    namespace = kubernetes_namespace_v1.identidade.metadata[0].name
    labels    = local.keycloak_rotulos
  }

  spec {
    type = "NodePort"
    selector = {
      app = "keycloak"
    }
    port {
      name        = "http"
      port        = 8080
      target_port = "http"
      node_port   = 30180
      protocol    = "TCP"
    }
  }
}

# Reconcilia o usuario gestor.loja com o Secret keycloak-gestor (idempotente):
# cria o usuario se nao existir, define a senha (nao temporaria), garante o papel gestor e
# remove os papeis padrao de cliente (default-roles-revenda e cliente).
# Necessario porque o import do realm e IGNORE_EXISTING: sem este Job, uma rotacao da
# senha (terraform apply -replace=random_password.keycloak_gestor) ou um state recriado
# com o keycloak-db preservado deixariam o Secret divergente da senha real.
# Recriado (e reexecutado) quando a senha do gestor ou o Deployment do Keycloak mudam.
# Atencao: o admin bootstrap so e criado na primeira subida; rotacionar keycloak_admin
# exige recriar o keycloak-db (ver keycloak/README.md).
resource "kubernetes_job_v1" "keycloak_gestor_senha" {
  metadata {
    name      = "keycloak-gestor-senha"
    namespace = kubernetes_namespace_v1.identidade.metadata[0].name
    labels = merge(local.rotulos_comuns, {
      app                           = "keycloak-gestor-senha"
      "app.kubernetes.io/name"      = "keycloak-gestor-senha"
      "app.kubernetes.io/component" = "identidade"
    })
  }

  spec {
    backoff_limit           = 3
    active_deadline_seconds = 600

    template {
      metadata {
        labels = merge(local.rotulos_comuns, {
          app = "keycloak-gestor-senha"
        })
      }

      spec {
        restart_policy                  = "Never"
        automount_service_account_token = false
        enable_service_links            = false

        security_context {
          run_as_non_root = true
          run_as_user     = 1000
          run_as_group    = 0
          seccomp_profile {
            type = "RuntimeDefault"
          }
        }

        container {
          name              = "kcadm"
          image             = var.keycloak_imagem
          image_pull_policy = "IfNotPresent"
          command           = ["/bin/bash", "-c"]
          args = [<<-EOT
            set -euo pipefail
            KCADM=/opt/keycloak/bin/kcadm.sh
            CFG=/tmp/kcadm.config
            SERVIDOR=http://keycloak.identidade.svc.cluster.local:8080
            REALM=revenda
            USUARIO=gestor.loja
            for tentativa in {1..30}; do
              # Senhas via KC_CLI_PASSWORD (nao aparecem na linha de comando do processo)
              if KC_CLI_PASSWORD="$KC_BOOTSTRAP_ADMIN_PASSWORD" "$KCADM" config credentials --config "$CFG" \
                   --server "$SERVIDOR" --realm master --user "$KC_BOOTSTRAP_ADMIN_USERNAME" >/dev/null; then
                break
              fi
              if [ "$tentativa" -eq 30 ]; then echo "Falha no login do admin no Keycloak"; exit 1; fi
              echo "Keycloak ainda indisponivel (tentativa $tentativa); aguardando 10 s"
              sleep 10
            done
            existe="$("$KCADM" get users --config "$CFG" -r "$REALM" -q username="$USUARIO" -q exact=true --fields id --format csv --noquotes)"
            if [ -z "$existe" ]; then
              echo "Usuario $USUARIO ausente no realm: criando"
              "$KCADM" create users --config "$CFG" -r "$REALM" \
                -s username="$USUARIO" -s enabled=true -s email=gestor@revenda.local -s emailVerified=true \
                -s firstName=Gestor -s 'lastName=da Loja' -s 'attributes.cpf=["00000000000"]'
            fi
            KC_CLI_PASSWORD="$GESTOR_PASSWORD" "$KCADM" set-password --config "$CFG" -r "$REALM" --username "$USUARIO"
            "$KCADM" add-roles --config "$CFG" -r "$REALM" --uusername "$USUARIO" --rolename gestor
            # Usuario criado pela Admin API recebe default-roles-revenda (composite com
            # cliente). O gestor fica so com o papel gestor, igual ao import do realm.
            # Idempotente: a remocao de um papel que o usuario nao tem e ignorada.
            for papel in default-roles-revenda cliente; do
              if "$KCADM" remove-roles --config "$CFG" -r "$REALM" --uusername "$USUARIO" --rolename "$papel" 2>/dev/null; then
                echo "Papel $papel removido (ou ja ausente) de $USUARIO"
              else
                echo "Papel $papel nao estava atribuido a $USUARIO: ignorado"
              fi
            done
            echo "Usuario $USUARIO reconciliado com o Secret keycloak-gestor"
          EOT
          ]

          # KC_BOOTSTRAP_ADMIN_USERNAME / KC_BOOTSTRAP_ADMIN_PASSWORD
          env_from {
            secret_ref {
              name = kubernetes_secret_v1.keycloak_admin.metadata[0].name
            }
          }
          # GESTOR_PASSWORD
          env_from {
            secret_ref {
              name = kubernetes_secret_v1.keycloak_gestor.metadata[0].name
            }
          }

          resources {
            requests = {
              cpu    = "100m"
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

          volume_mount {
            name       = "tmp"
            mount_path = "/tmp"
          }
        }

        volume {
          name = "tmp"
          empty_dir {}
        }
      }
    }
  }

  wait_for_completion = true

  timeouts {
    create = "12m"
    update = "12m"
  }

  depends_on = [
    kubernetes_deployment_v1.keycloak,
    kubernetes_service_v1.keycloak,
  ]

  lifecycle {
    replace_triggered_by = [
      random_password.keycloak_gestor,
      kubernetes_deployment_v1.keycloak,
    ]
  }
}
