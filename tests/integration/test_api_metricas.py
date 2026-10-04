"""GET /metrics (Prometheus): métricas HTTP por rota template e contadores de negócio."""

from __future__ import annotations

from datetime import timedelta

from prometheus_client.parser import text_string_to_metric_families

from apoio.api import Api
from revenda.shared.clock import RelogioFixo


def _metricas(api: Api) -> dict[tuple[str, tuple[tuple[str, str], ...]], float]:
    resposta = api.http.get("/metrics")
    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/plain")
    return {
        (a.name, tuple(sorted(a.labels.items()))): a.value
        for familia in text_string_to_metric_families(resposta.text)
        for a in familia.samples
    }


def _cancelada(motivo: str) -> tuple[str, tuple[tuple[str, str], ...]]:
    return ("revenda_vendas_canceladas_total", (("motivo", motivo),))


def test_metrics_publico_e_fora_do_openapi(api: Api) -> None:
    amostras = _metricas(api)
    assert amostras[("revenda_veiculos_cadastrados_total", ())] == 0
    for motivo in ("PAGAMENTO_RECUSADO", "DESISTENCIA_COMPRADOR", "CANCELADA_PELA_LOJA"):
        assert amostras[_cancelada(motivo)] == 0  # séries iniciadas em zero
    assert any(nome.startswith("process_") for nome, _ in amostras)
    assert "/metrics" not in api.http.get("/openapi.json").json()["paths"]


def test_contadores_de_negocio_acompanham_o_fluxo(api: Api, relogio: RelogioFixo) -> None:
    carros = [api.cadastrar(preco=f"{50000 + i}.00") for i in range(4)]
    cliente = api.novo_cliente("cliente-metricas")

    efetivada = api.compra_ok(carros[0]["id"], cliente)
    assert api.webhook(efetivada["codigo_pagamento"], "APROVADO").status_code == 200
    assert api.webhook(efetivada["codigo_pagamento"], "APROVADO").status_code == 200  # repetido
    recusada = api.compra_ok(carros[1]["id"], cliente)
    assert api.webhook(recusada["codigo_pagamento"], "RECUSADO").status_code == 200
    desistencia = api.compra_ok(carros[2]["id"], cliente)
    assert (
        api.http.post(f"/api/v1/vendas/{desistencia['id']}/cancelar", headers=cliente).status_code
        == 200
    )
    api.compra_ok(carros[3]["id"], cliente)
    relogio.avancar(timedelta(minutes=31))
    api.a_venda()  # expiração preguiçosa
    # Compra recusada (409) não conta: o evento só sai após o commit.
    assert api.comprar(carros[0]["id"], cliente).status_code == 409

    amostras = _metricas(api)
    assert amostras[("revenda_veiculos_cadastrados_total", ())] == 4
    assert amostras[("revenda_vendas_iniciadas_total", ())] == 4
    assert amostras[("revenda_vendas_efetivadas_total", ())] == 1
    assert amostras[_cancelada("PAGAMENTO_RECUSADO")] == 1
    assert amostras[_cancelada("DESISTENCIA_COMPRADOR")] == 1
    assert amostras[_cancelada("RESERVA_EXPIRADA")] == 1
    assert amostras[_cancelada("CANCELADA_PELA_LOJA")] == 0


def test_metricas_http_sem_ids_nem_dados_pessoais(api: Api) -> None:
    veiculo = api.cadastrar()
    api.veiculo(veiculo["id"])
    api.http.get("/api/v1/rota-que-nao-existe/123")
    texto = api.http.get("/metrics").text
    assert veiculo["id"] not in texto
    assert "rota-que-nao-existe" not in texto  # o caminho de um 404 vira "nao_mapeada"
    amostras = _metricas(api)
    obter = (("metodo", "GET"), ("rota", "/api/v1/veiculos/{veiculo_id}"), ("status", "200"))
    assert amostras[("revenda_http_requisicoes_total", obter)] == 1
    assert amostras[("revenda_http_requisicao_duracao_segundos_count", obter)] == 1
    cadastro = (("metodo", "POST"), ("rota", "/api/v1/veiculos"), ("status", "201"))
    assert amostras[("revenda_http_requisicoes_total", cadastro)] == 1
    nao_mapeada = (("metodo", "GET"), ("rota", "nao_mapeada"), ("status", "404"))
    assert amostras[("revenda_http_requisicoes_total", nao_mapeada)] == 1
    rotulos = {
        chave for nome, rotulos in amostras if nome.startswith("revenda_") for chave, _ in rotulos
    }
    assert rotulos <= {"metodo", "rota", "status", "motivo", "le"}
