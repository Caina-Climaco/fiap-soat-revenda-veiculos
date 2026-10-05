# Teste de carga (k6)

`listagens.js` exercita as duas vitrines públicas, `GET /api/v1/veiculos/a-venda` e `GET /api/v1/veiculos/vendidos`, com **20 usuários virtuais por 1 minuto**. O teste falha se o p95 da latência passar de 300 ms (`http_req_duration p(95)<300`) ou se mais de 1% das requisições falhar (`http_req_failed rate<0.01`).

Com o ambiente no ar (API em `localhost:8080`) e o [k6](https://grafana.com/docs/k6/latest/set-up/install-k6/) instalado:

```bash
k6 run -e API_URL=http://localhost:8080 tests/carga/listagens.js
```

**API Gateway.** No ambiente kind, `localhost:8080` é o Kong ([ADR-015](../../docs/adrs/ADR-015-api-gateway-kong.md)), com *rate limiting* de 600 requisições por minuto por IP na rota `/api/v1`. Os 20 usuários virtuais passam desse limite em poucos segundos, e o Kong responde 429 ao excedente, o que derruba o *threshold* de erro. Para medir a API, eleve o limite durante o teste (no PowerShell, `$env:TF_VAR_kong_limite_geral_minuto = "100000"` e rode de novo `scripts\windows\04-subir-ambiente.ps1`; o próximo CD, ou o 04 sem a variável, volta ao padrão de 600), ou rode contra o docker compose, que não tem gateway.

Durante a execução, `kubectl -n revenda get hpa revenda-api -w` mostra o HPA reagindo à CPU, e o painel do Grafana (http://localhost:3000) mostra tráfego, p95 por rota e réplicas; o histograma `revenda_http_requisicao_duracao_segundos` também pode ser consultado no Prometheus (http://localhost:9090). No docker compose, `GET http://localhost:8080/metrics` mostra as métricas brutas. Não faz parte do pytest nem do CI.
