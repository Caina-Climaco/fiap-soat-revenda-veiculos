# Versoes do Terraform e dos providers (docs/08-ci-cd-infra.md, secao 1.1).
# As restricoes "~>" aceitam apenas correcoes/minors compativeis; o arquivo
# .terraform.lock.hcl (gerado no primeiro `terraform init`) deve ser versionado.

terraform {
  required_version = ">= 1.9.0"

  required_providers {
    # Cria o cluster kind. Embute a biblioteca sigs.k8s.io/kind v0.31.0
    # (independe da versao da CLI `kind` instalada no PC).
    kind = {
      source  = "tehcyx/kind"
      version = "~> 0.11.0"
    }
    # Namespaces, Secrets, ConfigMap, StatefulSets, Deployment, Services e NetworkPolicies
    # (recursos tipados *_v1; a serie 3.x deprecou os recursos sem sufixo).
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 3.3"
    }
    # metrics-server. A serie 3.x usa atributos (`kubernetes = { ... }`) em vez de blocos.
    helm = {
      source  = "hashicorp/helm"
      version = "~> 3.3"
    }
    # Senhas e segredo do webhook (ADR-011).
    random = {
      source  = "hashicorp/random"
      version = "~> 3.9"
    }
  }

  # State local FORA do repositorio. O caminho vem na inicializacao (configuracao parcial):
  #   terraform init -backend-config="path=$USERPROFILE/.revenda/terraform.tfstate"
  # O state contem os segredos gerados em texto claro (ADR-011): nunca versionar.
  backend "local" {}
}
