# Teste de carga (k6)

`listagens.js` exercita as duas vitrines públicas, `GET /api/v1/veiculos/a-venda` e `GET /api/v1/veiculos/vendidos`, com **20 usuários virtuais por 1 minuto**. O teste falha se o p95 da latência passar de 300 ms (`http_req_duration p(95)<300`) ou se mais de 1% das requisições falhar (`http_req_failed rate<0.01`).

Com o ambiente no ar (API em `localhost:8080`) e o [k6](https://grafana.com/docs/k6/latest/set-up/install-k6/) instalado:

```bash
k6 run -e API_URL=http://localhost:8080 tests/carga/listagens.js
```

Durante a execução, `kubectl -n revenda get hpa revenda-api -w` mostra o HPA reagindo à CPU, e `GET /metrics` mostra o histograma `revenda_http_requisicao_duracao_segundos` por rota. Não faz parte do pytest nem do CI.
