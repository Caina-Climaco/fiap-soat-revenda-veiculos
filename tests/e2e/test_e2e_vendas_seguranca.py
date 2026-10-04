"""Vendas: autenticacao do gateway (BDD-07), isolamento entre compradores e BDD-04/05."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e

V1 = "/api/v1"


def test_e2e_bdd04_compra_anonima_retorna_401(api, gestor, preco, execucao):
    veiculo = api.cadastrar_veiculo(
        gestor,
        preco(61000),
        marca="Renault",
        modelo=f"Kwid [e2e {execucao}]",
        ano=2023,
        cor="Vermelho",
    )
    api.assert_problema(api.comprar(None, veiculo["id"]), 401)
    api.assert_problema(
        api.http.post(
            api.url(f"{V1}/vendas"),
            headers={"Authorization": "Bearer token.invalido.e2e"},
            json={"veiculo_id": veiculo["id"]},
        ),
        401,
    )
    assert api.veiculo(veiculo["id"])["status"] == "A_VENDA"


def test_e2e_bdd05_gestor_nao_compra(api, gestor, preco, execucao):
    veiculo = api.cadastrar_veiculo(
        gestor, preco(83000), marca="Chevrolet", modelo=f"Onix [e2e {execucao}]", cor="Cinza"
    )
    api.assert_problema(api.comprar(gestor, veiculo["id"]), 403, "acesso-negado")
    assert api.veiculo(veiculo["id"])["status"] == "A_VENDA"


@pytest.mark.parametrize(
    ("rotulo", "headers"),
    [
        ("ausente", {}),
        ("vazio", {"X-Webhook-Secret": ""}),
        ("errado", {"X-Webhook-Secret": "segredo-errado"}),
    ],
)
def test_e2e_bdd07_webhook_com_segredo_invalido_retorna_401(
    api, gestor, cliente_a, preco, execucao, rotulo, headers
):
    veiculo = api.cadastrar_veiculo(
        gestor, preco(47000), marca="Hyundai", modelo=f"HB20 [e2e {execucao} {rotulo}]", cor="Azul"
    )
    venda = api.comprar_ok(cliente_a, veiculo["id"])

    resposta = api.webhook(venda["codigo_pagamento"], "APROVADO", headers=headers)
    api.assert_problema(resposta, 401, "webhook-nao-autorizado")

    consultada = api.assert_status(api.venda(cliente_a, venda["id"]), 200)
    assert consultada["status"] == "AGUARDANDO_PAGAMENTO"
    assert api.veiculo(veiculo["id"])["status"] == "RESERVADO"

    # Limpeza: o gateway (com o segredo correto) recusa e o veiculo volta a vitrine.
    api.assert_status(api.webhook(venda["codigo_pagamento"], "RECUSADO"), 200)
    assert api.veiculo(veiculo["id"])["status"] == "A_VENDA"


def test_e2e_webhook_codigo_desconhecido_retorna_404(api):
    resposta = api.webhook("PAG-000000000000", "APROVADO")
    api.assert_problema(resposta, 404, "pagamento-nao-encontrado")


def test_e2e_venda_de_outro_cliente_retorna_404(api, gestor, cliente_a, cliente_b, preco, execucao):
    """BOLA/IDOR: cliente que nao e dono recebe 404 (nao 403) e nao pode cancelar."""
    veiculo = api.cadastrar_veiculo(
        gestor, preco(77000), marca="Nissan", modelo=f"Kicks [e2e {execucao}]", cor="Branco"
    )
    venda = api.comprar_ok(cliente_a, veiculo["id"])

    api.assert_problema(api.venda(cliente_b, venda["id"]), 404, "venda-nao-encontrada")
    api.assert_problema(
        api.post(f"{V1}/vendas/{venda['id']}/cancelar", cliente_b), 404, "venda-nao-encontrada"
    )
    assert venda["id"] not in {v["id"] for v in api.minhas(cliente_b)}

    # Dono e gestor enxergam a venda; somente o gestor recebe comprador_id.
    dono = api.assert_status(api.venda(cliente_a, venda["id"]), 200)
    assert dono["status"] == "AGUARDANDO_PAGAMENTO"
    assert "comprador_id" not in dono
    pelo_gestor = api.assert_status(api.venda(gestor, venda["id"]), 200)
    assert pelo_gestor.get("comprador_id")

    # Limpeza: o gestor cancela (motivo CANCELADA_PELA_LOJA) e o veiculo e liberado.
    cancelada = api.assert_status(api.post(f"{V1}/vendas/{venda['id']}/cancelar", gestor), 200)
    assert cancelada["motivo_cancelamento"] == "CANCELADA_PELA_LOJA"
    assert api.veiculo(veiculo["id"])["status"] == "A_VENDA"


def test_e2e_minhas_compras_exige_cliente(api, gestor):
    api.assert_problema(api.get(f"{V1}/vendas/minhas"), 401)
    api.assert_problema(api.get(f"{V1}/vendas/minhas", gestor), 403)
