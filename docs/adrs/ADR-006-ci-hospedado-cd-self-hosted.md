# ADR-006: CI no runner hospedado do GitHub e CD em runner self-hosted

**Status:** Aceito
**Data:** 2026-10-03

## Contexto

O time de qualidade exige que toda implantação ou alteração passe por CI/CD e Pull Requests. O cluster roda no PC do autor ([ADR-005](ADR-005-kind-terraform-nodeport.md)), e um runner hospedado do GitHub não alcança esse cluster. Na Fase 2, o "deploy pelo pipeline" não existia de fato no repositório, e os pushes eram feitos direto na `main`.

## Alternativas avaliadas

| Alternativa | Prós | Contras |
|---|---|---|
| **CI hospedado + CD self-hosted** | CI isolado e reproduzível; CD alcança o cluster real; custo zero | O PC precisa estar ligado para o CD; runner self-hosted exige cuidados de segurança |
| Tudo self-hosted | Um runner só | Código de PRs não revisados rodaria na máquina do autor |
| Kind dentro do runner hospedado | Nada local | O ambiente morre no fim do job: valida, mas não implanta |
| Expor a API do cluster para a internet (túnel) | Usa o runner hospedado | Expõe o plano de controle do Kubernetes; inaceitável |

## Decisão

- `ci.yml` roda em `ubuntu-latest` a cada PR para a `main` e a cada push na `main`. Faz lint, tipagem, testes unitários e de integração com PostgreSQL, cobertura mínima de 80%, build da imagem, Trivy, `terraform fmt`/`validate` e kubeconform.
- `cd.yml` roda em `[self-hosted, kind-local]`, **somente** em push na `main` (ou seja, PR mergeado) e em `workflow_dispatch`, com `concurrency` para impedir deploys simultâneos.
- A `main` é protegida: PR obrigatório, CI obrigatório, sem force push, regra aplicada também a administradores.
- Workflows vindos de forks exigem aprovação.

## Consequências

### Positivas
- Toda mudança em código, infraestrutura ou manifestos passa por PR, CI e deploy automático, com rastreabilidade pelo SHA.
- O runner self-hosted só executa código já revisado e mergeado.

### Negativas
- O CD fica pendente se o PC estiver desligado. Ele roda quando o runner volta.
- Num trabalho individual, a aprovação de PR por outra pessoa não é possível.

## Mitigações
- O runner é instalado como serviço com usuário sem privilégios de administrador, e o job registra o resultado no resumo da execução.
- Aprovações exigidas = 0, mas CI verde obrigatório e checklist no template de PR. A decisão fica registrada aqui.
