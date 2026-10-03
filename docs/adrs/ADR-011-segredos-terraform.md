# ADR-011: Segredos gerados pelo Terraform, nada sensível versionado

**Status:** Aceito
**Data:** 2026-10-03

## Contexto

Na fase anterior, foram commitados no repositório um `k8s/secret.yaml` com credenciais do banco e a chave JWT, o kubeconfig do cluster (com certificado e chave do cliente) e arquivos `terraform.tfstate`. Este projeto precisa de senhas para dois bancos, do usuário admin do Keycloak e do segredo do webhook.

## Alternativas avaliadas

| Alternativa | Prós | Contras |
|---|---|---|
| **`random_password` do Terraform → `kubernetes_secret`** | Nada no Git; recriável; cada ambiente tem os seus segredos | Os valores ficam no state local |
| Secrets versionados em YAML | Simples | Vazamento garantido em repositório público |
| Sealed Secrets ou External Secrets | Padrão de mercado | Mais componentes; exige controller ou cofre externo |
| GitHub Secrets injetados no CD | Centralizado | Os segredos ainda precisariam ser criados e rotacionados à mão |

## Decisão

- O Terraform gera as senhas e cria os Secrets:
  - `revenda-db-credentials`
  - `keycloak-db-credentials`
  - `keycloak-admin`
  - `revenda-webhook-secret` (chave `WEBHOOK_SECRET`)
- Os manifestos da aplicação referenciam os Secrets por nome.
- O `.gitignore` bloqueia desde o primeiro commit: `*.tfstate*`, `.terraform/`, kubeconfig, `.env`.
- O `.env.example` traz apenas placeholders.
- O CI roda varredura de segredos (Trivy com o scanner `secret`) em cada PR.
- Para obter os valores no ambiente local (ex.: o segredo do webhook para a demonstração), os comandos `kubectl get secret` estão documentados no README.

## Consequências

### Positivas
- O repositório público não contém nenhuma credencial utilizável.

### Negativas
- O state local contém os segredos em texto claro.

## Mitigações
- O state fica fora do repositório, num diretório do usuário do runner. Para produção, o caminho documentado é backend remoto criptografado e cofre de segredos.
