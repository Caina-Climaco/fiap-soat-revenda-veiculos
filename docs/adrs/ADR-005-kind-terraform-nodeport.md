# ADR-005: Kubernetes local (kind) provisionado por Terraform, com NodePort e sem Ingress

**Status:** Aceito
**Data:** 2026-10-03

## Contexto

É preciso um ambiente de execução que suporte deploy automatizado e seja demonstrável em vídeo, sem acesso a cloud. A Fase 2 já usou kind e Terraform, mas o Terraform só criava o cluster: o banco foi instalado à mão.

## Alternativas avaliadas

| Alternativa | Prós | Contras |
|---|---|---|
| **kind via Terraform** | Kubernetes real em Docker; custo zero; reproduzível; experiência prévia | Depende do PC ligado; sem URL pública |
| Docker Compose apenas | Simples | Não exercita orquestração, probes, HPA e rollout, que são temas do curso |
| Minikube ou k3d | Equivalentes | Sem vantagem sobre o kind, que já é conhecido |
| PaaS gratuito (Render etc.) | URL pública | Limites de memória incompatíveis com o Keycloak; hibernação; banco gratuito expira |
| Ingress (ingress-nginx) para expor os serviços | Roteamento por host e path | O projeto ingress-nginx foi descontinuado pela comunidade Kubernetes em 2026; é mais um componente sem necessidade real num ambiente local |

## Decisão

O Terraform (`infra/terraform`) provisiona **tudo o que é plataforma**:
- cluster kind `revenda`, com `extraPortMappings` (host 8080 → NodePort 30080 da API; host 8180 → NodePort 30180 do Keycloak);
- namespaces `revenda` e `identidade`;
- metrics-server (via Helm);
- as duas instâncias PostgreSQL e o Keycloak;
- os Secrets gerados.

A aplicação é implantada pelos manifestos em `k8s/` (kustomize) no pipeline de CD. Os serviços são expostos por **NodePort**.

## Consequências

### Positivas
- Ambiente recriável do zero com `terraform apply`. Corrige a lacuna da Fase 2.
- Sem port-forward manual: a API fica em `http://localhost:8080` e o Keycloak em `http://localhost:8180`.

### Negativas
- O state do Terraform fica local, na máquina do runner.
- NodePort não oferece TLS nem roteamento por host.

## Mitigações
- O state fica num diretório fixo fora do repositório (`.gitignore`). O procedimento de recriação está documentado em [08-ci-cd-infra.md](../08-ci-cd-infra.md).
- Para produção, o caminho documentado é Gateway API com TLS num cluster gerenciado.
