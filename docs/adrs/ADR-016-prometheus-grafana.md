# ADR-016: Prometheus e Grafana no cluster, com alertas versionados e testados

**Status:** Aceito
**Data:** 2026-10-05
**Complementa:** [ADR-012](ADR-012-observabilidade-prometheus.md)

## Contexto

O [ADR-012](ADR-012-observabilidade-prometheus.md) colocou métricas Prometheus na API (`/metrics`, latência por rota, contadores de negócio) e deixou painel e alertas como proposta: ninguém coletava, e o risco R-13 de [10-plano-execucao.md](../10-plano-execucao.md) registrava que uma degradação podia passar despercebida. Com o API Gateway ([ADR-015](ADR-015-api-gateway-kong.md)) há uma segunda fonte de métricas (Kong) e `/metrics` deixa de ser alcançável pelo host, então a consulta "sob demanda com `curl`" também deixa de servir.

Restrições:

- ambiente local, sem conta de nuvem e com custo zero ([ADR-005](ADR-005-kind-terraform-nodeport.md));
- o PC do autor já roda cluster, Keycloak, Kong e dois runners: o monitoramento precisa caber em poucas centenas de MB;
- o Terraform deste repositório só administra os próprios namespaces; o cluster é compartilhado com o serviço de identidade ([ADR-014](ADR-014-identidade-em-repositorio-proprio.md)), então permissões de cluster inteiro (ClusterRole) e CRDs devem ser evitadas;
- alerta que não é testado tende a nunca disparar (ou a disparar sempre).

## Alternativas avaliadas

| Alternativa | Prós | Contras |
|---|---|---|
| **Prometheus + Grafana oficiais, implantados pelo Terraform, configuração em arquivos do repositório** (escolhida) | Consome o `/metrics` que já existe e o *plugin* prometheus do Kong sem mudar código; leve (dois pods); regras de alerta com testes de unidade (`promtool test rules`); painel como JSON versionado; permissões só de leitura de pods em dois namespaces | Sem Alertmanager (alerta não notifica ninguém); sem armazenamento persistente; painel e regras mantidos à mão |
| kube-prometheus-stack via Helm | Pacote completo (Operator, Alertmanager, node-exporter, kube-state-metrics, dezenas de painéis e regras) | Pesado para o PC (vários pods, GBs de memória); exige ClusterRole e CRDs (`ServiceMonitor`, `PrometheusRule`) num cluster compartilhado com a identidade; a maior parte do pacote não é usada |
| Zabbix | Maduro em monitoramento de infraestrutura, alertas e mapas | Modelo centrado em hosts e agentes, não em métricas rotuladas de pods efêmeros; servidor, banco e frontend a mais; não lê o formato Prometheus sem configuração extra por item |
| APM SaaS (New Relic ou Datadog) | Traços, painéis e alertas prontos; notificação por e-mail/Slack | Exige conta e chave; plano gratuito limitado; telemetria sai do ambiente (cuidado com LGPD); não demonstrável sem conta ativa; já tratado como evolução no [ADR-012](ADR-012-observabilidade-prometheus.md) |
| OpenTelemetry (SDK + Collector + backend) | Métricas, traços e logs neutros em relação a fornecedor | Exige instrumentar o código de novo e operar Collector e backend de traços; ainda precisaria de Prometheus/Grafana (ou similar) para ver as métricas; esforço desproporcional ao prazo |

## Decisão

- **Prometheus v3.14.0** no namespace `observabilidade`, implantado por `infra/terraform/observabilidade.tf`, NodePort 30900 → `http://localhost:9090`.
  - Descoberta de pods (`kubernetes_sd_configs`, `role: pod`) restrita aos namespaces `revenda` e `gateway`, com **Roles** (não ClusterRole) de leitura de pods em cada um.
  - Jobs: `prometheus` (o próprio), `revenda-api` (uma série por réplica, pelas anotações `prometheus.io/*` do pod) e `kong` (status listener `:8100`).
  - Retenção de 2 dias em `emptyDir`, sem volume persistente: é um ambiente de demonstração.
  - Configuração em `infra/observabilidade/prometheus.yml`, entregue num ConfigMap.
- **Regras de alerta versionadas** em `infra/observabilidade/alertas.yml`, em três grupos: `revenda-api` (`RevendaApiFora`, `RevendaErros5xxAltos`, `RevendaListagensLentas`, `RevendaHpaNoMaximo`, `RevendaWebhookRecusado`), `negocio` (`RevendaRecusasDePagamentoAltas`) e `gateway` (`KongFora`, `KongRejeicoesNaBorda`). Testes de unidade em `infra/observabilidade/alertas.test.yml`.
- **Sem Alertmanager**: os alertas aparecem em `http://localhost:9090/alerts` e no painel ("Alertas disparando"). Em produção, o Alertmanager enviaria para o canal da equipe.
- **Grafana 13.2.3**, NodePort 30300 → `http://localhost:3000`.
  - Fonte de dados (`uid: prometheus`) e painel provisionados por arquivo (`infra/observabilidade/grafana/`); o painel `revenda-visao-geral` ("Revenda de Veículos: visão geral") é a página inicial e não pode ser alterado pela interface.
  - Acesso anônimo como **Viewer**; o admin tem senha aleatória gerada pelo Terraform no Secret `observabilidade/grafana-admin`.
- **CI** (job `infra`): `promtool check config`, `promtool check rules`, `promtool test rules` e validação do JSON do painel com `jq` (uid e fonte de dados).
- **CD**: etapa "Monitoramento" que espera ao menos um alvo `up` dos jobs `revenda-api` e `kong`, confere que os três grupos de regras foram carregados e que o Grafana responde com o painel provisionado.
- APM (New Relic, Datadog ou OpenTelemetry) continua **evolução**, como no [ADR-012](ADR-012-observabilidade-prometheus.md).

## Consequências

### Positivas
- Golden signals da API, sinais de negócio e métricas do gateway visíveis num painel, sem conta nem custo.
- Alertas ativos e avaliados continuamente; o comportamento de cada regra é coberto por teste no CI.
- Painel, regras e configuração revisados por PR, como o restante da infraestrutura.
- Menor privilégio: o Prometheus só lista pods de `revenda` e `gateway`; não vê o namespace `identidade`.
- O CD prova, a cada implantação, que a coleta funciona (alvos `up`) e que o painel está provisionado.

### Negativas
- Sem notificação: alguém precisa olhar o painel ou a página de alertas.
- Dados de métricas se perdem quando o pod do Prometheus reinicia; sem histórico além de 2 dias.
- Mais ~400 MB de memória reservada no PC (requests de Prometheus e Grafana) e duas portas do host (3000 e 9090) que precisam estar livres.
- Quem já tinha o cluster precisa recriá-lo para as novas portas.
- Sem métricas de nó e de objetos do Kubernetes (node-exporter, kube-state-metrics): o alerta de HPA no máximo é aproximado pelo número de réplicas coletadas.

## Mitigações
- Seção 12.6 de [12-observabilidade.md](../12-observabilidade.md) descreve como acrescentar Alertmanager ou plugar um APM; as regras são reaproveitáveis.
- `kubectl top` (metrics-server) continua disponível para CPU e memória dos pods.
- Procedimento de migração (recriar o cluster) no README, seção "Migração para o API Gateway e o monitoramento".

## Referências
- [12-observabilidade.md](../12-observabilidade.md) (painel, alertas, consultas)
- [08-ci-cd-infra.md](../08-ci-cd-infra.md) (recursos Terraform e etapas do CI/CD)
- [Prometheus: Kubernetes service discovery](https://prometheus.io/docs/prometheus/latest/configuration/configuration/#kubernetes_sd_config)
- [Prometheus: Unit testing for rules](https://prometheus.io/docs/prometheus/latest/configuration/unit_testing_rules/)
- [Grafana: Provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/)
