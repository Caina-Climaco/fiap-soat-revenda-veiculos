# ADR-014: Serviço de identidade em repositório próprio

**Status:** Aceito
**Data:** 2026-10-04
**Atualiza:** [ADR-001](ADR-001-keycloak-identidade.md), [ADR-004](ADR-004-postgresql-schemas.md), [ADR-005](ADR-005-kind-terraform-nodeport.md), [ADR-006](ADR-006-ci-hospedado-cd-self-hosted.md), [ADR-011](ADR-011-segredos-terraform.md)

## Contexto

O enunciado do Trabalho Substitutivo da Fase 3 exige que o registro e a autorização dos compradores sejam feitos "de forma separada" e que "esse serviço deve estar totalmente apartado do resto da solução"; os entregáveis falam em "cada um dos repositórios". O [ADR-001](ADR-001-keycloak-identidade.md) já separava a identidade em processo, banco e namespace próprios, mas tudo morava **neste** repositório:

- o realm `revenda` (`keycloak/realm-revenda.json`);
- o Terraform do Keycloak, do banco dele, dos segredos e da NetworkPolicy, no **mesmo state** da API (`%USERPROFILE%\.revenda\terraform.tfstate`);
- o mesmo CI (o job `infra` validava o contrato do realm) e o mesmo CD (um único `terraform apply` subia API e Keycloak);
- o mesmo `docker-compose.yml`.

Com isso, uma mudança na API podia reimplantar o Keycloak, quem tinha acesso ao state da API tinha também as senhas do admin do Keycloak e do banco com os dados pessoais, e os testes e2e da API usavam o admin do realm `master` para criar compradores. A separação era de execução, não de entrega.

## Decisão

O serviço de identidade passa a ser **outro repositório**: [fiap-soat-revenda-identidade](https://github.com/Caina-Climaco/fiap-soat-revenda-identidade). Lá ficam o realm, o Terraform do namespace `identidade` (Keycloak 26.7.1, `keycloak-db`, segredos, NetworkPolicy do `keycloak-db`, Job `keycloak-reconciliar`), o state próprio (`%USERPROFILE%\.revenda\identidade.tfstate`), o CI próprio (checks `qualidade`, `realm`, que sobe um Keycloak real via docker compose e testa o contrato, e `infra`), o CD próprio num runner self-hosted próprio (container `revenda-runner-identidade`), os scripts e o docker compose do Keycloak.

Neste repositório fica só a API: código, migrações, manifestos `k8s/`, Terraform do namespace `revenda` (`revenda-db`, Secrets `revenda-db-credentials` e `revenda-webhook-secret`, NetworkPolicy do `revenda-db`, metrics-server) com state `%USERPROFILE%\.revenda\revenda-api.tfstate`, CI (`qualidade`, `testes`, `imagem`, `infra`) e CD.

Os dois lados se ligam só por um **contrato** publicado pelo repositório de identidade (documentado em `docs/contrato-identidade.md` daquele repositório), que não mudou com a separação:

| Item | Valor |
|---|---|
| Issuer | `http://localhost:8180/realms/revenda` |
| JWKS interno (cluster) | `http://keycloak.identidade.svc.cluster.local:8080/realms/revenda/protocol/openid-connect/certs` |
| Audiência | `revenda-api` |
| Papéis | `cliente`, `gestor` |
| Client do Swagger | `revenda-swagger` |
| Secrets de contrato (namespace `identidade`, só ambiente local) | `keycloak-gestor` (`GESTOR_PASSWORD`) e `keycloak-e2e` (`E2E_ADMIN_CLIENT_ID`, `E2E_ADMIN_CLIENT_SECRET`) |

Regras que decorrem disso:

- O **cluster kind `revenda` é a plataforma local compartilhada**. O `infra/kind/cluster.yaml` é idêntico nos dois repositórios, e o CD de cada um cria o cluster se ele faltar; cada repositório só aplica o próprio namespace, com Terraform e state próprios.
- O CD da API **verifica, antes de aplicar qualquer recurso da API,** se o realm `revenda` responde em `http://revenda-control-plane:30180/realms/revenda/.well-known/openid-configuration` e falha cedo, pedindo para implantar a identidade. O script `04-subir-ambiente.ps1` faz o mesmo em `http://localhost:8180`.
- Os testes e2e da API **não usam mais o admin do realm `master`**: criam e removem compradores com o client técnico `revenda-e2e-admin` (client credentials, apenas `manage-users`, `view-users` e `query-users` do realm `revenda`), cujo segredo vem do Secret de contrato `keycloak-e2e`. O admin do `master` nunca sai do repositório de identidade.
- O `docker-compose.yml` da API não tem Keycloak; o desenvolvedor sobe antes o compose do repositório de identidade, e a API busca o JWKS em `http://host.docker.internal:8180`.
- Ordem para subir tudo do zero: identidade (script 04 ou CD de lá) → infraestrutura da API (script 04 daqui) → CD da API.

## Consequências

### Positivas
- A separação exigida fica visível também na entrega: repositório, histórico, revisão, pipeline, state, segredos, namespace e banco separados. Um PR da API não consegue alterar o realm nem o Keycloak, e vice-versa.
- O state da API não contém mais nenhum segredo da identidade (senha do admin do Keycloak, do banco com dados pessoais, do gestor).
- Menor privilégio no e2e: o client técnico só gerencia usuários do realm `revenda`, em vez de ser administrador de todo o Keycloak.
- O contrato do realm passa a ser testado contra um Keycloak real no CI da identidade, não só por inspeção do JSON.
- Cada serviço é implantado e versionado no próprio ritmo.

### Negativas
- Dois repositórios, dois runners e dois pipelines para manter; a ordem de implantação passa a importar (a API depende da identidade no ar).
- O cluster continua compartilhado: apagá-lo (`05-destruir-ambiente.ps1 -ApagarCluster` de qualquer um dos lados) derruba os dois serviços.
- Ambientes criados antes da mudança precisam ser recriados: o state antigo (`terraform.tfstate`) descreve recursos que agora têm outro dono.
- Uma mudança no contrato (por exemplo, renomear um papel) exige coordenar dois PRs, um em cada repositório.

## Mitigações
- O contrato é documentado e testado no repositório de identidade; a API mantém os valores consumidos num só lugar (`k8s/base/configmap.yaml`).
- O CD e o script 04 da API falham cedo, com mensagem explícita, se a identidade não estiver publicada.
- O script 04 da API avisa quando ainda existe o state antigo; o procedimento de migração está no README, seção "Migração para dois repositórios".

## Alternativas consideradas

| Alternativa | Prós | Contras |
|---|---|---|
| **Repositório próprio para a identidade, cluster local compartilhado** (escolhida) | Atende literalmente ao "totalmente apartado" e a "cada um dos repositórios"; pipelines e states independentes; custo zero | Dois pipelines e dois runners; ordem de implantação |
| Manter tudo num repositório, só com namespaces e bancos separados (situação anterior) | Um pipeline; implantação única | Mesmo state e mesmos segredos para API e identidade; uma mudança na API reimplanta o Keycloak; não atende à leitura de "repositórios" separados |
| Monorrepositório com dois diretórios e workflows filtrados por caminho | Um só clone | Mesma governança e mesmo histórico; separação apenas por convenção; o runner do CD ainda teria acesso aos dois states |
| Um cluster kind por repositório | Isolamento total de plataforma | Dobra memória e portas no mesmo PC; a API precisaria alcançar o Keycloak fora do cluster, mudando o JWKS interno do contrato |
| Provedor gerenciado (Cognito, Auth0) | Nada para operar | Já descartado no [ADR-001](ADR-001-keycloak-identidade.md) (sem conta AWS; dados com operador externo) |
