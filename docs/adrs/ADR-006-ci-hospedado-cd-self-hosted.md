# ADR-006: CI no runner hospedado do GitHub e CD em runner self-hosted

**Status:** Aceito
**Atualizado por:** [ADR-014](ADR-014-identidade-em-repositorio-proprio.md)
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
- `cd.yml` roda em `[self-hosted, Linux, kind-local]`, **somente** em push na `main` (ou seja, PR mergeado) e em `workflow_dispatch` (com a `ref` informada validada como ancestral de `origin/main`), com `concurrency` para impedir deploys simultâneos.
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
- O repositório é público, e a documentação do GitHub desaconselha runners self-hosted em repositórios públicos: um fork poderia abrir um PR com um workflow que executa código arbitrário na máquina do runner.

## Mitigações
- Runner self-hosted em repositório público:
  - o `cd.yml` é o único workflow com `runs-on: [self-hosted, ...]` e só dispara em `push` na `main` (PR já mergeado) ou em `workflow_dispatch`; no disparo manual, o primeiro passo recusa qualquer `ref` que não seja ancestral de `origin/main` (rollback só para commits que já passaram pela `main`);
  - o CI de PR (`ci.yml`) roda **somente** no runner hospedado (`ubuntu-latest`); nenhum workflow self-hosted reage a `pull_request`;
  - workflows de PRs vindos de forks exigem aprovação do dono do repositório para rodar.

  Juntas, essas regras limitam o risco do socket do Docker a código revisado.
- Dentro do container o runner roda como o usuário `runner` (UID 1001), não como root; o acesso ao socket vem do grupo do socket, ajustado pelo entrypoint. O token de registro é de uso único, só trafega por variável de ambiente e não fica disponível para os jobs.
- O job registra o resultado no resumo da execução.
- Aprovações exigidas = 0, mas CI verde obrigatório e checklist no template de PR. A decisão fica registrada aqui.

## Risco: runner self-hosted em repositório público

Esta seção detalha o risco listado nas consequências negativas, o que o contém hoje e o que mudaria em produção. Ela existe porque o GitHub desaconselha runners self-hosted em repositórios públicos e este repositório é público (`scripts/windows/02-criar-repositorio.ps1`, linha 25: `gh repo create ... --public`).

### O que está em jogo

Quem consegue executar um job no runner controla o Docker Desktop do PC do autor:

- o container do runner recebe o socket do Docker do host (`scripts/windows/03-instalar-runner.ps1`, linha 180: `-v /var/run/docker.sock:/var/run/docker.sock`). Com o socket, qualquer processo do job pode criar containers privilegiados, montar o sistema de arquivos da VM do Docker Desktop, ler ou parar o nó do kind (`revenda-control-plane`), o runner do repositório de identidade e qualquer outro container do PC;
- o usuário `runner` (UID 1001) tem `sudo` sem senha dentro do container (`infra/runner/Dockerfile`, linhas 3 e 70; `infra/runner/entrypoint.sh`, linhas 39 a 44, usa `sudo groupadd`, `sudo usermod` e `sudo -E -H -u runner`). Não rodar como root limita acidentes, não um atacante: o `sudo` e o socket dão, na prática, controle total do container e do Docker do host;
- o container também monta `%USERPROFILE%\.revenda` em `/revenda-state` (`03-instalar-runner.ps1`, linha 182), onde ficam os states do Terraform dos dois repositórios, com os segredos em texto claro ([ADR-011](ADR-011-segredos-terraform.md)); está na rede docker `kind` (linha 179) e alcança o cluster pelo nome do nó.

O vetor clássico é um PR de fork com um workflow modificado: se um workflow com `runs-on: self-hosted` reagisse a `pull_request`, o código do PR rodaria no runner antes de qualquer revisão.

### O que já contém o risco

| Controle | Onde está |
|---|---|
| O CD só dispara em `push` na `main` (PR já mergeado) e em `workflow_dispatch`; nenhum workflow self-hosted reage a `pull_request` | `.github/workflows/cd.yml`, linhas 15 a 24 (`on:`) e 40 (`runs-on: [self-hosted, Linux, kind-local]`); `ci.yml` usa apenas `ubuntu-latest` (linhas 34, 70, 127, 210 e 344) |
| No disparo manual, o primeiro passo recusa qualquer `ref` que não seja ancestral de `origin/main`; vale também quando o disparo é feito "a partir de" outra branch | `cd.yml`, linhas 72 a 84 (`git merge-base --is-ancestor "$SHA" origin/main`) |
| Workflows de PRs de forks só rodam com aprovação do dono do repositório | `02-criar-repositorio.ps1`, linha 54: `fork-pr-contributor-approval` com `approval_policy=all_external_contributors` |
| `main` protegida: PR obrigatório, checks `qualidade`, `testes`, `imagem` e `infra` obrigatórios com a branch atualizada, histórico linear, sem force push nem exclusão, regra aplicada também a administradores | `02-criar-repositorio.ps1`, linhas 35 a 49 (`required_status_checks`, `enforce_admins: true`) |
| O CI de PR roda só no runner hospedado: código não revisado nunca toca o PC | `ci.yml` (todos os jobs em `ubuntu-latest`) |
| O job não recebe segredos do GitHub: o `GITHUB_TOKEN` tem só `contents: read` e o checkout não persiste a credencial; os segredos do e2e são lidos do cluster na hora e mascarados no log | `cd.yml`, linhas 26 e 27 (`permissions`), 65 (`persist-credentials: false`) e 357 a 372 (`kubectl get secret` + `::add-mask::`) |
| Runner registrado só neste repositório, com a label `kind-local`; o repositório de identidade tem o próprio runner | `03-instalar-runner.ps1`, linhas 22, 25 e 167 (token de registro do repositório) |

Juntas, essas regras fazem com que só código já revisado por PR, aprovado pelo CI e mergeado na `main` chegue ao runner. O que permanece é o risco residual de um merge malicioso ou de uma ação do GitHub comprometida usada pelo `cd.yml` (hoje só `actions/checkout`, fixada pelo SHA do commit da v7.0.1, como todas as `uses:` dos workflows; [08-ci-cd-infra.md](../08-ci-cd-infra.md), "Actions fixadas por SHA"), e a dependência da configuração do repositório, que não é versionada (é aplicada pelo script 02 e pode ser alterada pela interface do GitHub).

### O que seria feito em produção

- **Runner efêmero, um por job** (`--ephemeral`), em VM ou container descartado ao fim de cada execução, para que nada sobreviva de um job para o próximo; hoje o container é persistente (`--restart unless-stopped`) e reaproveita o registro no volume `revenda-runner-persist`.
- **Sem socket do Docker no runner**: a imagem seria construída e publicada num registry pelo CI hospedado, e o CD só faria `kubectl`/`terraform` com uma credencial restrita ao namespace (o `kind load` deixa de existir, [ADR-010](ADR-010-kind-load-sem-registry.md)); o usuário do runner não teria `sudo`.
- **Repositório privado**, ou `environment` `local` com *required reviewers* e restrição a branches protegidas (o environment já existe, `02-criar-repositorio.ps1`, linha 58, mas sem regras de proteção), para que um deploy exija uma aprovação explícita além do merge.
- Configuração do repositório como código (por exemplo, *rulesets* versionados). O *pinning* das ações por SHA já está feito nos dois workflows.

No ambiente desta entrega, esses pontos foram trocados pelas restrições acima, com o PC do autor como única máquina afetada; a escolha está registrada como consequência negativa aceita.

## Atualização (ADR-014, 2026-10-04)

Atualizado por [ADR-014](ADR-014-identidade-em-repositorio-proprio.md). O modelo (CI hospedado, CD self-hosted em container) continua o mesmo, agora replicado em dois repositórios:

- **Este repositório**: CI com os checks `qualidade`, `testes`, `imagem` e `infra` (a validação do realm saiu do job `infra`); CD no runner `revenda-runner`, que grava o state em `/revenda-state/revenda-api.tfstate` e roda `terraform init -reconfigure`. Antes do `terraform apply`, o CD verifica se o realm `revenda` responde em `http://revenda-control-plane:30180` e falha cedo se a identidade não estiver implantada. No e2e, lê do namespace `identidade` apenas os Secrets de contrato `keycloak-gestor` e `keycloak-e2e`; não usa mais o admin do realm `master`.
- **Repositório [fiap-soat-revenda-identidade](https://github.com/Caina-Climaco/fiap-soat-revenda-identidade)**: CI com os checks `qualidade`, `realm` (sobe um Keycloak real via docker compose e testa o contrato) e `infra`; CD num runner self-hosted próprio (container `revenda-runner-identidade`), com state `identidade.tfstate`.
- Os dois runners compartilham o mesmo Docker Desktop, a rede `kind` e o diretório `%USERPROFILE%\.revenda`, mas cada CD só lê e grava o próprio arquivo de state.
