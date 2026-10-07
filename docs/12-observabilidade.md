# 12. Observabilidade

Este documento descreve o que a `revenda-api` e o API Gateway oferecem para serem observados (logs, probes, métricas Prometheus e métricas de recursos), o monitoramento instalado no cluster (Prometheus e Grafana, com painel e alertas versionados), como os quatro *golden signals* se mapeiam para essas métricas, os SLIs/SLOs, os alertas ativos e como plugar um APM (New Relic ou Datadog) sem mudar o código de negócio. As decisões estão no [ADR-012](adrs/ADR-012-observabilidade-prometheus.md) (métricas na API) e no [ADR-016](adrs/ADR-016-prometheus-grafana.md) (Prometheus e Grafana); o contrato do endpoint `/metrics` está em [05-api.md](05-api.md), seção 4.14.

## 12.1 O que existe

| Sinal | Como | Onde ver |
|---|---|---|
| **Logs** | JSON em stdout, uma linha por evento: `ts`, `nivel`, `logger`, `mensagem`, `request_id` e campos do evento. O middleware registra cada requisição com `metodo`, `rota` (template), `status`, `latencia_ms` e, se autenticada, `sub` (pseudônimo). Eventos de domínio (`CompraIniciada`, `VendaEfetivada`, `VendaCancelada` etc.) também viram linhas de log | `kubectl -n revenda logs deployment/revenda-api`; `docker compose logs api` |
| **Correlação** | Header `X-Request-ID` gerado pelo Kong quando ausente (plugin `correlation-id`) e repassado à API, que o aceita (se bem formado) ou gera; devolvido na resposta, presente no log de acesso do Kong, em todas as linhas de log da requisição na API e no corpo dos erros `problem+json` | Header da resposta e campo `request_id` |
| **Privacidade nos logs** | Nunca são registrados tokens, `Authorization`, `X-Webhook-Secret`, senhas nem dados pessoais; o SQLAlchemy usa `hide_parameters=True` (erros de banco sem valores de parâmetros); respostas 5xx saem em nível `ERROR`, 401 e 403 em `WARNING` (possível abuso) e o restante em `INFO` | [07-seguranca-lgpd.md](07-seguranca-lgpd.md), seção 3.9 |
| **Probes** | `GET /health/live` (processo vivo) e `GET /health/ready` (`SELECT 1` no banco); usadas por `startupProbe`, `livenessProbe` e `readinessProbe` | [08-ci-cd-infra.md](08-ci-cd-infra.md), seção 2.2 |
| **Métricas da aplicação** | `GET /metrics` no formato Prometheus, na porta 8000 do pod, **só dentro do cluster** (o Kong não tem rota para ele: `http://localhost:8080/metrics` responde 404). Pods anotados com `prometheus.io/scrape: "true"`, `prometheus.io/port: "8000"` e `prometheus.io/path: /metrics`, coletados pelo Prometheus | Grafana e Prometheus (seção 12.5) |
| **Métricas do API Gateway** | Plugin `prometheus` do Kong no *status listener* (`:8100/metrics`): `kong_http_requests_total` (por `route` e `code`), histogramas `kong_request_latency_ms`, `kong_upstream_latency_ms` e `kong_kong_latency_ms`, largura de banda e saúde do *upstream* | Grafana (linha "API Gateway (Kong)") e Prometheus |
| **Logs do gateway** | Log de acesso do Kong em stdout, com o `X-Request-ID` | `kubectl -n gateway logs deployment/kong` |
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

### 12.1.1 Monitoramento instalado no cluster

Implantado pelo Terraform deste repositório (`infra/terraform/observabilidade.tf`) no namespace `observabilidade` ([ADR-016](adrs/ADR-016-prometheus-grafana.md)):

| Componente | Configuração | Acesso |
|---|---|---|
| **Prometheus** 3.14.0 | `infra/observabilidade/prometheus.yml`: *scrape* a cada 15 s; jobs `prometheus`, `revenda-api` (descoberta de pods no ns `revenda`, uma série por réplica, pelas anotações `prometheus.io/*`) e `kong` (pods do ns `gateway`, porta 8100). Permissão: Roles de leitura de pods só em `revenda` e `gateway`. Regras em `alertas.yml`. Retenção de 2 dias em `emptyDir` (os dados somem quando o pod reinicia) | http://localhost:9090 (NodePort 30900); alertas em http://localhost:9090/alerts |
| **Grafana** 13.2.3 | Fonte de dados `Prometheus` (uid `prometheus`) e painel provisionados por arquivo (`infra/observabilidade/grafana/`), pasta "Revenda"; o painel é a página inicial e não pode ser alterado pela interface. Acesso anônimo como Viewer; admin `admin` com senha aleatória no Secret `observabilidade/grafana-admin` | http://localhost:3000 (NodePort 30300) |
| **Alertmanager** | Não instalado: os alertas não notificam ninguém, aparecem no Prometheus e no painel | — |
| **APM** | Não instalado (evolução, seção 12.6) | — |

**Painel "Revenda de Veículos — visão geral"** (uid `revenda-visao-geral`, `infra/observabilidade/grafana/painel-revenda.json`):

| Linha | Painéis |
|---|---|
| Negócio (contadores de domínio da API) | Vendas iniciadas, Vendas efetivadas, Vendas canceladas, Veículos cadastrados, Réplicas da API, Alertas disparando |
| API (golden signals) | Tráfego por rota (req/s), Latência p95 por rota, Respostas por status |
| API Gateway (Kong) | Requisições por rota do Kong, Barradas na borda (401, 403, 429), Latência no Kong (p95: total, *upstream* e do próprio Kong) |

O CD confere, a cada deploy, que o Prometheus tem alvos `up` dos jobs `revenda-api` e `kong`, que os 3 grupos de regras foram carregados e que o Grafana responde com o painel ([08-ci-cd-infra.md](08-ci-cd-infra.md), seção 3.3). No docker compose de desenvolvimento não há Prometheus nem Grafana: lá, `/metrics` é lido direto em `http://localhost:8080/metrics`.

## 12.2 Golden signals

| Sinal | Métrica | Consulta PromQL (janela de 5 min) |
|---|---|---|
| **Latência** | `revenda_http_requisicao_duracao_segundos` | `histogram_quantile(0.95, sum by (le, rota) (rate(revenda_http_requisicao_duracao_segundos_bucket[5m])))` |
| **Tráfego** | `revenda_http_requisicoes_total` | `sum by (rota) (rate(revenda_http_requisicoes_total[5m]))` |
| **Erros** | `revenda_http_requisicoes_total{status=~"5.."}` | `sum(rate(revenda_http_requisicoes_total{status=~"5.."}[5m])) / sum(rate(revenda_http_requisicoes_total[5m]))` |
| **Saturação** | CPU e memória (metrics-server), réplicas do HPA | `count(up{job="revenda-api"} == 1)` (réplicas coletadas, × `maxReplicas` 5); `kubectl top pods`. Sem cAdvisor/kube-state-metrics no Prometheus local, `container_cpu_usage_seconds_total` e `kube_horizontalpodautoscaler_status_current_replicas` ficam como evolução |

No API Gateway:

| Sinal | Consulta PromQL |
|---|---|
| Tráfego por rota do Kong | `sum by (route) (rate(kong_http_requests_total[5m]))` |
| Barradas na borda | `sum by (code) (rate(kong_http_requests_total{code=~"401|403|429"}[5m]))` |
| Latência p95 total e do *upstream* | `histogram_quantile(0.95, sum by (le) (rate(kong_request_latency_ms_bucket[5m])))` e o mesmo com `kong_upstream_latency_ms_bucket` |

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

## 12.4 Alertas

As regras **ativas** estão em `infra/observabilidade/alertas.yml`, em três grupos (`revenda-api`, `negocio`, `gateway`), são avaliadas pelo Prometheus do cluster a cada 15 s e todas as oito têm testes de unidade com um caso que dispara e um que não dispara (`infra/observabilidade/alertas.test.yml`, `promtool test rules` no CI; ver [09-testes.md](09-testes.md), seção 9.5.11). As marcadas como *proposta* ainda não foram implementadas.

| Alerta | Expressão | Por | Severidade | Ação |
|---|---|---|---|---|
| `RevendaApiFora` | `up{job="revenda-api"} == 0 or absent(up{job="revenda-api"})` (alvo sem scrape) | 2 min | crítica | Ver pods, eventos e `rollout status` |
| `RevendaErros5xxAltos` | Taxa de 5xx da seção 12.2 `> 0.01` | 5 min | crítica | Logs `nivel=ERROR` por `request_id`; rollback se coincidir com deploy |
| `RevendaListagensLentas` | p95 das listagens `> 0.3` s | 10 min | alerta | Ver saturação (CPU, HPA no máximo) e o banco |
| `RevendaOrcamentoQueimandoRapido` (*proposta*) | Consumo do orçamento de erro de disponibilidade 14 vezes acima do sustentável em 1 h e em 5 min (*burn rate* multijanela) | — | crítica | Tratar como incidente |
| `RevendaHpaNoMaximo` | `count(up{job="revenda-api"} == 1) >= 5` (réplicas coletadas no máximo do HPA) | 15 min | alerta | Avaliar `maxReplicas`, *requests* e consultas lentas |
| `RevendaWebhookRecusado` | `sum(rate(revenda_http_requisicoes_total{rota="/api/v1/pagamentos/webhook",status="401"}[5m])) > 0.1` | 5 min | alerta | Possível tentativa de forjar pagamento; conferir origem e rotacionar o segredo |
| `RevendaRecusasDePagamentoAltas` | `sum(increase(revenda_vendas_canceladas_total{motivo="PAGAMENTO_RECUSADO"}[1h])) / clamp_min(sum(increase(revenda_vendas_iniciadas_total[1h])), 1) > 0.3` | 30 min | informativa | Falar com o gateway de pagamento |
| `RevendaReservasExpirandoMuito` (*proposta*) | Mesma razão com `motivo="RESERVA_EXPIRADA"` `> 0.5` | 1 h | informativa | Avaliar TTL da reserva e o fluxo de pagamento |
| `KongFora` | `up{job="kong"} == 0 or absent(up{job="kong"})` | 2 min | crítica | `kubectl -n gateway get pods`; `kubectl -n gateway logs deployment/kong` |
| `KongRejeicoesNaBorda` | `sum(rate(kong_http_requests_total{code=~"401|403|429"}[5m])) > 0.5` | 5 min | alerta | Conferir a origem no log do Kong; possível abuso (credencial inválida no webhook ou excesso de requisições) |

Com o gateway, um webhook com credencial errada é barrado no Kong e conta em `KongRejeicoesNaBorda`; `RevendaWebhookRecusado` passa a indicar o caso raro em que a credencial passou pelo Kong mas não conferiu na API (por exemplo, Secrets fora de sincronia).

Sem Alertmanager, os alertas ativos aparecem em http://localhost:9090/alerts e no painel "Alertas disparando" do Grafana. Em produção, o Alertmanager enviaria os críticos para o plantão e os de negócio para um canal da equipe: alertas de negócio não acordam ninguém.

## 12.5 Como acessar o monitoramento localmente

No ambiente kind (opção B do README):

| O quê | Onde |
|---|---|
| Painel | http://localhost:3000 (abre direto em "Revenda de Veículos — visão geral"; leitura anônima) |
| Consultas PromQL | http://localhost:9090/query, com as consultas da seção 12.2 |
| Alvos coletados | http://localhost:9090/targets (jobs `revenda-api`, uma linha por réplica, e `kong`) |
| Alertas | http://localhost:9090/alerts |
| Admin do Grafana | usuário `admin`; senha: `kubectl -n observabilidade get secret grafana-admin -o jsonpath='{.data.GF_SECURITY_ADMIN_PASSWORD}' \| base64 -d` |

```bash
# Gerar tráfego e acompanhar no painel (tráfego, p95, réplicas); veja o aviso sobre o
# rate limiting do Kong em 09-testes.md, seção 9.6
k6 run tests/carga/listagens.js

# Consulta pela API HTTP do Prometheus (a mesma que o CD usa)
curl -s --get http://localhost:9090/api/v1/query \
  --data-urlencode 'query=sum by (rota) (rate(revenda_http_requisicoes_total[5m]))' | jq '.data.result'

# Texto bruto de /metrics de uma réplica (o endpoint não passa pelo gateway)
kubectl -n revenda port-forward deploy/revenda-api 8000:8000
curl -s http://localhost:8000/metrics | grep '^revenda_'

# Métricas do Kong
kubectl -n gateway port-forward deploy/kong 8100:8100
curl -s http://localhost:8100/metrics | grep '^kong_http_requests_total'
```

`http://localhost:8080/metrics` responde **404 do Kong**: as métricas da API não são publicadas fora do cluster ([07-seguranca-lgpd.md](07-seguranca-lgpd.md), seção 3.9).

No docker compose (opção A) não há gateway, Prometheus nem Grafana: `curl -s http://localhost:8080/metrics | grep '^revenda_'` lê direto da única réplica.

## 12.6 Como plugar um APM (evolução)

A Fase 3 apresentou APMs como New Relic e Datadog. Nenhum deles foi implementado aqui (sem conta e sem custo, ver [ADR-012](adrs/ADR-012-observabilidade-prometheus.md) e [ADR-016](adrs/ADR-016-prometheus-grafana.md)), mas a aplicação já está preparada para os três caminhos abaixo, e o Prometheus do cluster pode continuar como fonte das métricas (os APMs leem o formato Prometheus/OpenMetrics, e o Prometheus pode enviar por *remote write*). Outra evolução, independente do APM, é acrescentar o **Alertmanager** às regras que já existem, para notificar o plantão. Em todos, a chave do APM entra como Secret gerado ou importado pelo Terraform, nunca versionada, e a `versao` do serviço é o SHA da imagem, o que liga cada traço ao deploy.

| Caminho | Como | O que ganha |
|---|---|---|
| **Agente New Relic** | Dependência `newrelic`; o comando do container passa a ser `newrelic-admin run-program uvicorn revenda.main:app ...`; `NEW_RELIC_LICENSE_KEY` (Secret) e `NEW_RELIC_APP_NAME=revenda-api` | Traços por requisição com tempo de banco (SQLAlchemy), erros com stack trace, mapa de dependências |
| **Agente Datadog** | Datadog Agent no cluster (Helm, DaemonSet) e dependência `ddtrace`; comando `ddtrace-run uvicorn ...`; `DD_SERVICE=revenda-api`, `DD_ENV=local`, `DD_VERSION=<sha>`, `DD_AGENT_HOST` pelo IP do nó | Traços, perfis e correlação log ↔ traço; o Agent também pode raspar o `/metrics` existente (integração OpenMetrics) |
| **OpenTelemetry** (neutro) | `opentelemetry-instrumentation-fastapi` e `-sqlalchemy`, exportando OTLP para um OpenTelemetry Collector; o Collector envia para New Relic, Datadog ou um Jaeger/Tempo local | Troca de fornecedor sem mexer na aplicação; padrão aberto |

Cuidados que valem para qualquer APM, por causa da LGPD: desligar a captura de corpo de requisição, *query string* e headers (o `Authorization` e o `X-Webhook-Secret` não podem sair do cluster); propagar o `X-Request-ID` como atributo do traço; manter os eventos de domínio sem dados pessoais, como já são. O `readOnlyRootFilesystem` continua possível: os agentes escrevem só em `/tmp` (já montado como `emptyDir`).
