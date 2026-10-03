# ADR-010: Imagem carregada no kind sem registry, com tag igual ao SHA

**Status:** Aceito
**Data:** 2026-10-03

## Contexto

O CD roda na mesma máquina do cluster kind ([ADR-006](ADR-006-ci-hospedado-cd-self-hosted.md)). As imagens precisam chegar aos nós do cluster de forma rastreável. Na Fase 2 havia uma imagem no Docker Hub com tag manual (`v2`).

## Alternativas avaliadas

| Alternativa | Prós | Contras |
|---|---|---|
| **`kind load docker-image`**, tag = SHA do commit | Sem registry nem credenciais; rápido; rastreável | A imagem não fica publicada fora da máquina |
| GHCR ou Docker Hub | Imagem publicada e reutilizável | Credenciais no runner e nos nós; pull pela internet |
| Registry local no cluster | Fiel a produção | Mais um componente |

## Decisão

- O CD constrói `revenda-api:<sha>` no runner, carrega com `kind load docker-image --name revenda` e aplica os manifestos com a tag via kustomize (`images[].newTag`).
- `imagePullPolicy: IfNotPresent`. A tag `latest` nunca é usada.
- O CI também constrói a imagem e roda o Trivy, garantindo que o Dockerfile funciona antes do merge.

## Consequências

### Positivas
- Cada pod em execução aponta para o commit exato que o gerou. Rollback = reaplicar o SHA anterior.

### Negativas
- A imagem do CI e a do CD são builds distintos do mesmo commit.

## Mitigações
- Build determinístico: versões fixadas no `pyproject.toml`/lockfile e imagem base com tag fixa. A evolução documentada é publicar no GHCR a imagem do CI e fazer o CD consumi-la.
