# 12. Observabilidade

Este documento descreve o que a `revenda-api` oferece hoje para ser observada (logs, probes, métricas Prometheus e métricas de recursos), como os quatro *golden signals* se mapeiam para essas métricas, os SLIs/SLOs e alertas propostos e como plugar um APM (New Relic ou Datadog) sem mudar o código de negócio. A decisão está no [ADR-012](adrs/ADR-012-observabilidade-prometheus.md); o contrato do endpoint `/metrics` está em [05-api.md](05-api.md), seção 4.14.

## 12.1 O que existe

| Sinal | Como | Onde ver |
|---|---|---|
| **Logs** | JSON em stdout, uma linha por evento: `ts`, `nivel`, `logger`, `mensagem`, `request_id` e campos do evento. O middleware registra cada requisição com `metodo`, `rota` (template), `status`, `latencia_ms` e, se autenticada, `sub` (pseudônimo). Eventos de domínio (`CompraIniciada`, `VendaEfetivada`, `VendaCancelada` etc.) também viram linhas de log | `kubectl -n revenda logs deployment/revenda-api`; `docker compose logs api` |
| **Correlação** | Header `X-Request-ID` aceito (se bem formado) ou gerado; devolvido na resposta, presente em todas as linhas de log da requisição e no corpo dos erros `problem+json` | Header da resposta e campo `request_id` |
| **Privacidade nos logs** | Nunca são registrados tokens, `Authorization`, `X-Webhook-Secret`, senhas nem dados pessoais; o SQLAlchemy usa `hide_parameters=True` (erros de banco sem valores de parâmetros); respostas 5xx saem em nível `ERROR`, 401 e 403 em `WARNING` (possível abuso) e o restante em `INFO` | [07-seguranca-lgpd.md](07-seguranca-lgpd.md), seção 3.9 |
| **Probes** | `GET /health/live` (processo vivo) e `GET /health/ready` (`SELECT 1` no banco); usadas por `startupProbe`, `livenessProbe` e `readinessProbe` | [08-ci-cd-infra.md](08-ci-cd-infra.md), seção 2.2 |
| **Métricas da aplicação** | `GET /metrics` no formato Prometheus, na mesma porta da API (8000 no pod, 8080 no host). Pods anotados com `prometheus.io/scrape: "true"`, `prometheus.io/port: "8000"` e `prometheus.io/path: /metrics` | Seção 12.5 |
| **Métricas de recursos** | metrics-server (Helm, via Terraform): CPU e memória por pod, base do HPA (2..5 réplicas, alvo de 60% de CPU) | `kubectl top pods -n revenda`; `kubectl -n revenda get hpa` |

Métricas expostas em `/metrics`:

| Métrica | Tipo | Rótulos |
|---|---|---|
| `revenda_http_requisicoes_total` | contador | `metodo`, `rota`, `status` |
| `revenda_http_requisicao_duracao_segundos` | histograma | `metodo`, `rota`, `status` |
| `revenda_vendas_iniciadas_total` | contador | — |
| `revenda_vendas_efetivadas_total` | contador | — |
| `revenda_vendas_canceladas_total` | contador | `motivo` |
| `revenda_veiculos_cadastrados_total` | contador | — |

O rótulo `rota` é o template da rota (ex.: `/api/v1/vendas/{venda_id}`), nunca o caminho com o UUID; caminhos que não correspondem a nenhuma rota (404) usam o valor fixo `nao_mapeada`. A cardinalidade fica limitada ao número de rotas. Além das séries da aplicação, o endpoint traz as métricas padrão do processo Python (`process_*`, `python_*`: CPU, memória, descritores de arquivo, coleta de lixo). Os contadores de negócio são alimentados pelos eventos de domínio publicados **depois do commit**, então só contam fatos confirmados. Nenhuma métrica carrega `sub`, identificador de venda ou de veículo.

O que **não** existe nesta entrega: Prometheus, Grafana, Alertmanager ou agente de APM no cluster. As consultas e os alertas abaixo são propostas prontas para quando um coletor for instalado.

## 12.2 Golden signals

| Sinal | Métrica | Consulta PromQL (janela de 5 min) |
|---|---|---|
| **Latência** | `revenda_http_requisicao_duracao_segundos` | `histogram_quantile(0.95, sum by (le, rota) (rate(revenda_http_requisicao_duracao_segundos_bucket[5m])))` |
| **Tráfego** | `revenda_http_requisicoes_total` | `sum by (rota) (rate(revenda_http_requisicoes_total[5m]))` |
| **Erros** | `revenda_http_requisicoes_total{status=~"5.."}` | `sum(rate(revenda_http_requisicoes_total{status=~"5.."}[5m])) / sum(rate(revenda_http_requisicoes_total[5m]))` |
| **Saturação** | CPU e memória (metrics-server), réplicas do HPA | `kubectl top pods`; réplicas atuais × `maxReplicas` (5); com Prometheus e cAdvisor/kube-state-metrics: `container_cpu_usage_seconds_total`, `kube_horizontalpodautoscaler_status_current_replicas` |

Sinais de negócio, a partir dos contadores de domínio:

| Indicador | Consulta |
|---|---|
| Vendas iniciadas por hora | `sum(increase(revenda_vendas_iniciadas_total[1h]))` |
| Taxa de conversão (efetivadas / iniciadas, 24 h) | `sum(increase(revenda_vendas_efetivadas_total[24h])) / sum(increase(revenda_vendas_iniciadas_total[24h]))` |
| Cancelamentos por motivo | `sum by (motivo) (increase(revenda_vendas_canceladas_total[24h]))` |
| Cadastro de estoque | `sum(increase(revenda_veiculos_cadastrados_total[24h]))` |

Os contadores são por processo: com várias réplicas, as consultas sempre agregam com `sum`. Um reinício de pod zera o contador daquele pod, o que `rate` e `increase` já tratam.

## 12.3 SLIs e SLOs propostos

Janela de avaliação: 28 dias corridos. Requisições a `/health/*` e `/metrics` ficam fora dos SLIs.

| SLI | Definição | SLO | Orçamento de erro (28 dias) |
|---|---|---|---|
| Latência das listagens | Proporção de requisições `GET /api/v1/veiculos/a-venda` e `/vendidos` com status 2xx respondidas em menos de 300 ms (bucket `le="0.3"` do histograma) | **99%** | 1% das requisições acima de 300 ms |
| Latência da compra | Proporção de `POST /api/v1/vendas` respondidas em menos de 500 ms | 99% | 1% |
| Disponibilidade | Proporção de requisições à API sem resposta 5xx | **99,5%** | 0,5% das requisições (no ambiente local, também cerca de 3,4 h de indisponibilidade total por janela) |
| Taxa de erro 5xx | `5xx / total` em janelas de 5 min | **< 1%** em toda janela | Base do alerta de erros |

Os números partem do RNF-10 ([03-requisitos.md](03-requisitos.md)), verificado com o k6 (`tests/carga/listagens.js`: p95 < 300 ms e erro < 1% com 20 usuários virtuais). Num ambiente de um nó no PC do autor, o SLO de disponibilidade é uma meta de referência para produção, não um compromisso do ambiente local.

## 12.4 Alertas propostos

Regras no formato do Prometheus/Alertmanager (ou monitores equivalentes no APM):

| Alerta | Expressão | Por | Severidade | Ação |
|---|---|---|---|---|
| `RevendaApiFora` | `up{job="revenda-api"} == 0` (alvo sem scrape) | 2 min | crítica | Ver pods, eventos e `rollout status` |
| `RevendaErros5xxAltos` | Taxa de 5xx da seção 12.2 `> 0.01` | 5 min | crítica | Logs `nivel=ERROR` por `request_id`; rollback se coincidir com deploy |
| `RevendaListagensLentas` | p95 das listagens `> 0.3` s | 10 min | alerta | Ver saturação (CPU, HPA no máximo) e o banco |
| `RevendaOrcamentoQueimandoRapido` | Consumo do orçamento de erro de disponibilidade 14 vezes acima do sustentável em 1 h e em 5 min (*burn rate* multijanela) | — | crítica | Tratar como incidente |
| `RevendaHpaNoMaximo` | Réplicas atuais = 5 | 15 min | alerta | Avaliar `maxReplicas`, *requests* e consultas lentas |
| `RevendaWebhookRecusado` | `sum(rate(revenda_http_requisicoes_total{rota="/api/v1/pagamentos/webhook",status="401"}[5m])) > 0.1` | 5 min | alerta | Possível tentativa de forjar pagamento; conferir origem e rotacionar o segredo |
| `RevendaRecusasDePagamentoAltas` | `increase(revenda_vendas_canceladas_total{motivo="PAGAMENTO_RECUSADO"}[1h]) / increase(revenda_vendas_iniciadas_total[1h]) > 0.3` | 30 min | informativa | Falar com o gateway de pagamento |
| `RevendaReservasExpirandoMuito` | Mesma razão com `motivo="RESERVA_EXPIRADA"` `> 0.5` | 1 h | informativa | Avaliar TTL da reserva e o fluxo de pagamento |

Alertas de negócio não acordam ninguém: viram aviso em canal da equipe.

## 12.5 Como consultar `/metrics` localmente

```bash
# Pelo Service (cada chamada pode cair numa réplica diferente)
curl -s http://localhost:8080/metrics | grep '^revenda_'

# Um pod específico, sem passar pelo Service
kubectl -n revenda get pods -l app=revenda-api
kubectl -n revenda port-forward pod/<nome-do-pod> 18000:8000
curl -s http://localhost:18000/metrics | grep revenda_vendas

# Gerar tráfego e ver o histograma andar
k6 run tests/carga/listagens.js
curl -s http://localhost:8080/metrics | grep 'revenda_http_requisicao_duracao_segundos_bucket{.*a-venda'
```

No docker compose o endereço é o mesmo (`http://localhost:8080/metrics`), com uma única réplica.

Para experimentar consultas PromQL sem instalar nada no cluster, um Prometheus temporário em container pode raspar a API pelo host (no Docker Desktop, `host.docker.internal`):

```bash
cat > prometheus.yml <<'YAML'
scrape_configs:
  - job_name: revenda-api
    scrape_interval: 5s
    static_configs:
      - targets: ["host.docker.internal:8080"]
YAML
docker run --rm -p 9090:9090 -v "$PWD/prometheus.yml:/etc/prometheus/prometheus.yml" prom/prometheus
# http://localhost:9090 -> consultas da seção 12.2
```

Nesse modo o Prometheus enxerga só a réplica que o Service escolher a cada scrape; a coleta por pod (via anotações `prometheus.io/*` e descoberta de serviços do Kubernetes) é o modo de produção.

## 12.6 Como plugar um APM (evolução)

A Fase 3 apresentou APMs como New Relic e Datadog. Nenhum deles foi implementado aqui (sem conta e sem custo, ver [ADR-012](adrs/ADR-012-observabilidade-prometheus.md)), mas a aplicação já está preparada para os três caminhos abaixo. Em todos, a chave do APM entra como Secret gerado ou importado pelo Terraform, nunca versionada, e a `versao` do serviço é o SHA da imagem, o que liga cada traço ao deploy.

| Caminho | Como | O que ganha |
|---|---|---|
| **Agente New Relic** | Dependência `newrelic`; o comando do container passa a ser `newrelic-admin run-program uvicorn revenda.main:app ...`; `NEW_RELIC_LICENSE_KEY` (Secret) e `NEW_RELIC_APP_NAME=revenda-api` | Traços por requisição com tempo de banco (SQLAlchemy), erros com stack trace, mapa de dependências |
| **Agente Datadog** | Datadog Agent no cluster (Helm, DaemonSet) e dependência `ddtrace`; comando `ddtrace-run uvicorn ...`; `DD_SERVICE=revenda-api`, `DD_ENV=local`, `DD_VERSION=<sha>`, `DD_AGENT_HOST` pelo IP do nó | Traços, perfis e correlação log ↔ traço; o Agent também pode raspar o `/metrics` existente (integração OpenMetrics) |
| **OpenTelemetry** (neutro) | `opentelemetry-instrumentation-fastapi` e `-sqlalchemy`, exportando OTLP para um OpenTelemetry Collector; o Collector envia para New Relic, Datadog ou um Jaeger/Tempo local | Troca de fornecedor sem mexer na aplicação; padrão aberto |

Cuidados que valem para qualquer APM, por causa da LGPD: desligar a captura de corpo de requisição, *query string* e headers (o `Authorization` e o `X-Webhook-Secret` não podem sair do cluster); propagar o `X-Request-ID` como atributo do traço; manter os eventos de domínio sem dados pessoais, como já são. O `readOnlyRootFilesystem` continua possível: os agentes escrevem só em `/tmp` (já montado como `emptyDir`).
