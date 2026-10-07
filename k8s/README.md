# k8s — manifestos da revenda-api (kustomize)

```text
k8s/
├── base/        # ConfigMap revenda-api-config, Deployment revenda-api, Service ClusterIP 80, HPA 2..5
├── migracao/    # Job revenda-migracao (python -m revenda.migracao)
└── saneamento/  # CronJob revenda-saneamento (python -m revenda.expirar, a cada 10 min)
```

Tudo no namespace `revenda`. A plataforma da API (namespace, Secrets, `revenda-db`, metrics-server, NetworkPolicies, o API Gateway Kong e Prometheus/Grafana) vem do Terraform em `infra/terraform`; estes manifestos só **referenciam** os Secrets `revenda-db-credentials` (`DB_USER`, `DB_PASSWORD`, `DB_NAME`) e `revenda-webhook-secret` (`WEBHOOK_SECRET`).

O Keycloak não é implantado aqui nem pelo Terraform deste repositório: ele vem do repositório [fiap-soat-revenda-identidade](https://github.com/Caina-Climaco/fiap-soat-revenda-identidade) ([ADR-014](../docs/adrs/ADR-014-identidade-em-repositorio-proprio.md)). O `base/configmap.yaml` é o único lugar com o contrato consumido: `OIDC_ISSUER` (`http://localhost:8180/realms/revenda`), `OIDC_JWKS_URL` (`http://keycloak.identidade.svc.cluster.local:8080/realms/revenda/protocol/openid-connect/certs`), `OIDC_AUDIENCE` (`revenda-api`) e `OIDC_SWAGGER_CLIENT_ID` (`revenda-swagger`).

## Contrato com o CD (`.github/workflows/cd.yml`)

| Item | Valor |
|---|---|
| Imagem no repositório | `revenda-api:dev` (tag neutra), `imagePullPolicy: IfNotPresent` |
| Troca da tag | CD substitui `revenda-api:dev` por `revenda-api:<sha>` no YAML renderizado (`kubectl kustomize`), ou `kustomize edit set image revenda-api=revenda-api:<sha>` — os dois funcionam |
| Ordem | 1) `kubectl -n revenda delete job revenda-migracao --ignore-not-found`; 2) aplicar `k8s/migracao` e esperar `Complete` (`activeDeadlineSeconds: 300`); 3) aplicar `k8s/base`; 4) `kubectl -n revenda rollout status deployment/revenda-api`; 5) aplicar `k8s/saneamento` (CronJob: `apply` atualiza no lugar, sem `delete`) e disparar uma execução de fumaça com `kubectl -n revenda create job revenda-saneamento-cd-<sha> --from=cronjob/revenda-saneamento` |
| Container | `api` no Deployment (`kubectl -n revenda set image deployment/revenda-api api=revenda-api:<sha>`); `migracao` no Job; `saneamento` no CronJob |
| Rótulos | pods da API `app=revenda-api`; pod da migração `app=revenda-migracao`; pod do CronJob de saneamento `app=revenda-saneamento` (os três valores que a NetworkPolicy do `revenda-db` aceita). `app=revenda-api` também é o alvo da NetworkPolicy `revenda-api-somente-gateway` (Terraform) |
| Réplicas | sem `replicas` no Deployment: quem manda é o HPA (mín. 2) |
| Exposição | Service `revenda-api` **ClusterIP** (porta 80 → `http` 8000), só dentro do cluster. A entrada pelo host é o API Gateway: `http://localhost:8080` → NodePort 30080 → Kong (namespace `gateway`, Terraform) → `revenda-api.revenda.svc.cluster.local:80` ([ADR-015](../docs/adrs/ADR-015-api-gateway-kong.md)). A NetworkPolicy `revenda-api-somente-gateway` só aceita o Kong, o Prometheus e o nó |
| Métricas | Anotações `prometheus.io/scrape`, `prometheus.io/port: "8000"` e `prometheus.io/path: /metrics` no pod: o Prometheus do namespace `observabilidade` coleta cada réplica por elas ([ADR-016](../docs/adrs/ADR-016-prometheus-grafana.md)). `/metrics` não tem rota no Kong |

O Job de migração é autossuficiente (define `DB_HOST`/`DB_PORT` no próprio Job): no primeiro deploy ele roda antes de o ConfigMap da base existir. O CronJob de saneamento segue o mesmo padrão (`DB_HOST`/`DB_PORT`, Secret `revenda-db-credentials`, `SANEAMENTO_LOTE`, `SANEAMENTO_TETO`), com `schedule: */10 * * * *`, `concurrencyPolicy: Forbid`, `successfulJobsHistoryLimit: 1` e o mesmo `securityContext` do Job; ele é a segunda linha de defesa da expiração preguiçosa ([ADR-009](../docs/adrs/ADR-009-expiracao-preguicosa.md)), não parte do caminho crítico da API.

## Validação local

```bash
kubectl kustomize k8s/base | kubeconform -strict -ignore-missing-schemas -summary -output text
kubectl kustomize k8s/migracao | kubeconform -strict -ignore-missing-schemas -summary -output text
kubectl kustomize k8s/saneamento | kubeconform -strict -ignore-missing-schemas -summary -output text
```
