"""API Gateway (Kong, ADR-015): rotas, plugins e consumer, contra o ambiente implantado."""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.e2e

V1 = "/api/v1"


@pytest.fixture(autouse=True)
def _exige_gateway(via_gateway):
    if not via_gateway:
        pytest.skip("API acessada sem o API Gateway (ex.: docker compose de desenvolvimento)")


def test_e2e_gateway_encaminha_a_vitrine_com_rate_limiting(api):
    resposta = api.get(f"{V1}/veiculos/a-venda")
    assert resposta.status_code == 200
    assert "kong" in resposta.headers.get("via", "").lower()
    # rate-limiting na rota api (por IP): cabecalhos de limite e de saldo
    assert int(resposta.headers["ratelimit-limit"]) > 0
    assert int(resposta.headers["ratelimit-remaining"]) >= 0


def test_e2e_gateway_propaga_o_id_de_correlacao(api, http):
    meu_id = f"e2e-{uuid.uuid4()}"
    resposta = http.get(api.url(f"{V1}/veiculos/a-venda"), headers={"X-Request-ID": meu_id})
    assert resposta.status_code == 200
    assert resposta.headers["x-request-id"] == meu_id
    # sem o cabecalho, o Kong gera um (plugin correlation-id) e a API usa o mesmo nos logs
    gerado = http.get(api.url(f"{V1}/veiculos/a-venda")).headers.get("x-request-id", "")
    assert len(gerado) >= 32


def test_e2e_gateway_compra_tem_limite_proprio(api, cliente_a):
    # POST /api/v1/vendas cai na rota "compra", com limite menor que a rota geral
    geral = int(api.get(f"{V1}/veiculos/a-venda").headers["ratelimit-limit"])
    compra = api.comprar(cliente_a, str(uuid.uuid4()))
    assert compra.status_code in (404, 409, 422), compra.text[:200]
    assert int(compra.headers["ratelimit-limit"]) < geral


def test_e2e_gateway_metrics_da_api_nao_e_exposto(api, http):
    # /metrics so e lido dentro do cluster pelo Prometheus: nao ha rota no gateway
    api.barrado_no_gateway(http.get(api.url("/metrics")), 404)


def test_e2e_gateway_webhook_com_credencial_do_consumer_chega_a_api(api):
    # Credencial correta do consumer gateway-pagamento: o Kong deixa passar e a API responde
    # (404: codigo de pagamento inexistente, mas a resposta e da API, nao do gateway)
    resposta = api.webhook("PAG-000000000000", "APROVADO")
    assert resposta.status_code == 404
    assert "x-kong-upstream-latency" in resposta.headers
