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
- `cd.yml` roda em `[self-hosted, Linux, kind-local]`, **somente** em push na `main` (ou seja, PR mergeado) e em `workflow_dispatch`, com `concurrency` para impedir deploys simultâneos.
- O runner self-hosted roda num **container Linux no Docker Desktop do PC** (`infra/runner/Dockerfile`, imagem oficial `ghcr.io/actions/actions-runner` com kind, kubectl, Terraform e Python), instalado por `scripts/windows/03-instalar-runner.ps1`:
  - o container está na rede docker `kind` e alcança o cluster pelo nome do nó (`revenda-control-plane`);
  - usa o Docker do host pelo socket montado (`docker build`, `kind load`);
  - grava o state do Terraform no mesmo arquivo usado no Windows, por bind mount de `%USERPROFILE%\.revenda` em `/revenda-state`.

  **Motivo:** o runner nativo para Windows foi bloqueado pelo **Smart App Control** do Windows 11 ("Uma política de Controle de Aplicativo bloqueou este arquivo", em `Runner.Common.dll`), que barra binários sem assinatura de reputação reconhecida. Desligar o Smart App Control foi descartado. Dentro do container, os binários rodam na VM Linux do Docker Desktop, fora do alcance dessa política.
- A `main` é protegida: PR obrigatório, CI obrigatório, sem force push, regra aplicada também a administradores.
- Workflows vindos de forks exigem aprovação.

## Consequências

### Positivas
- Toda mudança em código, infraestrutura ou manifestos passa por PR, CI e deploy automático, com rastreabilidade pelo SHA.
- O runner self-hosted só executa código já revisado e mergeado.

- Runner em container: isolado do sistema de arquivos do Windows (só o diretório do state é montado), reiniciado automaticamente (`--restart unless-stopped`, inclusive quando o Docker Desktop sobe) e com Linux nativo (bash, sem as conversões de caminho do Git Bash).

### Negativas
- O CD fica pendente se o PC estiver desligado. Ele roda quando o runner volta.
- O socket do Docker montado no container equivale, na prática, a privilégio de administrador sobre o Docker do host. Quem controla um job controla os containers do PC, inclusive o cluster.
- O state do Terraform é compartilhado entre o Terraform do Windows (script 04) e o do container. Os dois precisam usar a mesma versão (1.16.4), e o arquivo trafega pelo compartilhamento de arquivos do Docker Desktop.
- Num trabalho individual, a aprovação de PR por outra pessoa não é possível.

## Mitigações
- Só código já revisado e mergeado na `main` (ou disparado manualmente pelo dono) roda no runner; nenhum workflow self-hosted reage a `pull_request`, e PRs de fork exigem aprovação. Isso limita o risco do socket do Docker.
- Dentro do container o runner roda como o usuário `runner` (UID 1001), não como root; o acesso ao socket vem do grupo do socket, ajustado pelo entrypoint. O token de registro é de uso único, só trafega por variável de ambiente e não fica disponível para os jobs.
- O job registra o resultado no resumo da execução.
- Aprovações exigidas = 0, mas CI verde obrigatório e checklist no template de PR. A decisão fica registrada aqui.
