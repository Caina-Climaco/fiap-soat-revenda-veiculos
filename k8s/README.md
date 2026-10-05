# k8s — manifestos da revenda-api (kustomize)

```text
k8s/
├── base/        # ConfigMap revenda-api-config, Deployment revenda-api, Service NodePort 30080, HPA 2..5
└── migracao/    # Job revenda-migracao (alembic upgrade head)
```

Tudo no namespace `revenda`. A plataforma da API (namespace, Secrets, `revenda-db`, metrics-server) vem do Terraform em `infra/terraform`; estes manifestos só **referenciam** os Secrets `revenda-db-credentials` (`DB_USER`, `DB_PASSWORD`, `DB_NAME`) e `revenda-webhook-secret` (`WEBHOOK_SECRET`).

O Keycloak não é implantado aqui nem pelo Terraform deste repositório: ele vem do repositório [fiap-soat-revenda-identidade](https://github.com/Caina-Climaco/fiap-soat-revenda-identidade) ([ADR-014](../docs/adrs/ADR-014-identidade-em-repositorio-proprio.md)). O `base/configmap.yaml` é o único lugar com o contrato consumido: `OIDC_ISSUER` (`http://localhost:8180/realms/revenda`), `OIDC_JWKS_URL` (`http://keycloak.identidade.svc.cluster.local:8080/realms/revenda/protocol/openid-connect/certs`), `OIDC_AUDIENCE` (`revenda-api`) e `OIDC_SWAGGER_CLIENT_ID` (`revenda-swagger`).

## Contrato com o CD (`.github/workflows/cd.yml`)

| Item | Valor |
|---|---|
| Imagem no repositório | `revenda-api:dev` (tag neutra), `imagePullPolicy: IfNotPresent` |
| Troca da tag | CD substitui `revenda-api:dev` por `revenda-api:<sha>` no YAML renderizado (`kubectl kustomize`), ou `kustomize edit set image revenda-api=revenda-api:<sha>` — os dois funcionam |
| Ordem | 1) `kubectl -n revenda delete job revenda-migracao --ignore-not-found`; 2) aplicar `k8s/migracao` e esperar `Complete` (`activeDeadlineSeconds: 300`); 3) aplicar `k8s/base`; 4) `kubectl -n revenda rollout status deployment/revenda-api` |
| Container | `api` no Deployment (`kubectl -n revenda set image deployment/revenda-api api=revenda-api:<sha>`); `migracao` no Job |
| Rótulos | pods da API `app=revenda-api`; pod da migração `app=revenda-migracao` (são os que a NetworkPolicy do `revenda-db` aceita) |
| Réplicas | sem `replicas` no Deployment: quem manda é o HPA (mín. 2) |
| Exposição | Service `revenda-api` NodePort 30080 → `http://localhost:8080` |

O Job de migração é autossuficiente (define `DB_HOST`/`DB_PORT` no próprio Job): no primeiro deploy ele roda antes de o ConfigMap da base existir.

## Validação local

```bash
kubectl kustomize k8s/base | kubeconform -strict -summary -kubernetes-version 1.34.0
kubectl kustomize k8s/migracao | kubeconform -strict -summary -kubernetes-version 1.34.0
```
