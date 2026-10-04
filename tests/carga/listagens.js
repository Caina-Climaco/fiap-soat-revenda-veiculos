// Teste de carga minimo das vitrines publicas (k6): 20 usuarios virtuais por 1 minuto.
// Uso: k6 run -e API_URL=http://localhost:8080 tests/carga/listagens.js
// Sem autenticacao: as listagens sao publicas. Nao entra no pytest nem no CI.
import http from "k6/http";
import { check, sleep } from "k6";

const API_URL = (__ENV.API_URL || "http://localhost:8080").replace(/\/+$/, "");

export const options = {
  vus: 20,
  duration: "1m",
  thresholds: {
    http_req_duration: ["p(95)<300"], // 95% das requisicoes em menos de 300 ms
    http_req_failed: ["rate<0.01"], // menos de 1% de falhas
  },
};

const ROTAS = ["/api/v1/veiculos/a-venda", "/api/v1/veiculos/vendidos"];

export default function () {
  for (const rota of ROTAS) {
    const resposta = http.get(`${API_URL}${rota}?limite=20&deslocamento=0`, {
      tags: { name: rota }, // agrupa as metricas pela rota, sem a query string
    });
    check(resposta, {
      "status 200": (r) => r.status === 200,
      "pagina com itens": (r) => Array.isArray(r.json("itens")),
    });
  }
  sleep(0.5);
}
