# ADR-012: Métricas Prometheus nativas na API, com APM como evolução

**Status:** Aceito
**Data:** 2026-10-03

## Contexto

A Fase 3 trata de observabilidade e apresenta APMs como New Relic e Datadog. A API já tinha logs JSON com `X-Request-ID`, probes de vida e prontidão e o metrics-server para o HPA, mas nenhuma métrica de aplicação: não havia como medir latência por rota, taxa de erro ou o andamento do negócio (vendas iniciadas, efetivadas, canceladas) sem ler logs. O ambiente é local, sem conta de nuvem e com custo zero ([ADR-005](ADR-005-kind-terraform-nodeport.md)); o PC do autor já roda o cluster, o Keycloak e o runner.

## Alternativas avaliadas

| Alternativa | Prós | Contras |
|---|---|---|
| **Métricas Prometheus nativas** (`/metrics` com `prometheus-client`) | Padrão aberto, aceito por Prometheus, Grafana, New Relic e Datadog; sem conta nem custo; sem processo extra no pod; testável em teste de integração | Sem traços distribuídos; sem painel nem alerta enquanto ninguém coleta |
| APM SaaS direto (agente New Relic ou Datadog) | Traços, painéis e alertas prontos | Exige conta e chave; plano gratuito limitado; envia telemetria para fora do ambiente (cuidado com LGPD); acopla o código ao fornecedor; não demonstrável sem conta ativa |
| OpenTelemetry completo (SDK + Collector + backend de traços) | Neutro em relação a fornecedor; métricas, traços e logs | Mais componentes no cluster (Collector, Jaeger/Tempo, Prometheus) e mais memória num PC já carregado; esforço desproporcional ao prazo |
| Só logs | Já existe | Latência e taxa de erro só por agregação de logs; sem alerta simples; sem sinal de negócio |

## Decisão

- A API expõe `GET /metrics` no formato Prometheus, fora do prefixo `/api/v1` e do OpenAPI:
  - histograma de latência e contador de requisições por método, **rota template** e status;
  - contadores de negócio `revenda_vendas_iniciadas_total`, `revenda_vendas_efetivadas_total`, `revenda_vendas_canceladas_total{motivo}` e `revenda_veiculos_cadastrados_total`.
- O pod do Deployment recebe as anotações `prometheus.io/scrape`, `prometheus.io/port` e `prometheus.io/path`, para descoberta automática por um Prometheus que venha a ser instalado.
- As métricas não carregam dados pessoais nem identificadores (`sub`, ids de venda ou veículo).
- Golden signals, SLIs/SLOs e alertas ficam documentados como proposta em [12-observabilidade.md](../12-observabilidade.md).
- APM (New Relic, Datadog ou OpenTelemetry) é **evolução**: o caminho de integração está descrito, sem implementação.

## Consequências

### Positivas
- Os quatro golden signals e os indicadores de negócio ficam mensuráveis com um `curl`, sem custo e sem dependência de fornecedor.
- Qualquer APM consegue consumir o mesmo endpoint (integrações OpenMetrics/Prometheus), então a escolha do fornecedor fica para depois.
- Rótulo de rota por template mantém a cardinalidade baixa.

### Negativas
- Não há coletor, painel nem alerta ativo no ambiente local: as métricas só são lidas sob demanda.
- Contadores por processo: com várias réplicas, a visão total exige agregação no Prometheus; pelo Service, cada `curl` mostra uma réplica.
- Sem traços distribuídos: a correlação entre requisição, banco e Keycloak continua pelo `request_id` nos logs.
- `/metrics` é público no NodePort local, como as listagens.

## Mitigações
- Seção 12.5 de [12-observabilidade.md](../12-observabilidade.md) mostra como consultar por pod (`port-forward`) e como subir um Prometheus temporário para testar as consultas.
- Em produção, `/metrics` fica restrito à rede interna do cluster (Service ClusterIP ou NetworkPolicy liberando só o Prometheus).
- Ao adotar um APM, desligar a captura de corpo, *query string* e headers sensíveis ([07-seguranca-lgpd.md](../07-seguranca-lgpd.md)).
