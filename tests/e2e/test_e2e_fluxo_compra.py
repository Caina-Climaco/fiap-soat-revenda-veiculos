"""Fluxo inicio-a-fim (DESIGN_BRIEF secao 6, roteiro do video) e BDD-01/BDD-02.

Cada teste cria seus proprios veiculos (precos distintivos) e clientes, entao nao
depende de dados pre-existentes no ambiente.
"""

from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal

import pytest

pytestmark = pytest.mark.e2e

CODIGO_PAGAMENTO = re.compile(r"^PAG-[0-9a-f]{12}$")
V1 = "/api/v1"


def test_e2e_bdd01_fluxo_inicio_a_fim(api, gestor, cliente_a, cliente_b, preco, execucao):
    """Roteiro completo: cadastro, edicao, vitrine, 401/403, compra, 409, webhook, efetivacao."""
    # 1. Gestor cadastra 3 veiculos e edita o preco de um deles.
    caro = api.cadastrar_veiculo(
        gestor, preco(150000), marca="Jeep", modelo=f"Compass [e2e {execucao}]", cor="Preto"
    )
    barato = api.cadastrar_veiculo(
        gestor, preco(45000), marca="Fiat", modelo=f"Mobi [e2e {execucao}]", cor="Branco"
    )
    medio = api.cadastrar_veiculo(
        gestor, preco(80000), marca="Fiat", modelo=f"Argo [e2e {execucao}]", cor="Prata"
    )
    novo_preco = preco(72000)
    editado = api.assert_status(
        api.patch(f"{V1}/veiculos/{medio['id']}", gestor, {"preco": novo_preco}), 200
    )
    assert editado["preco"] == novo_preco
    assert editado["versao"] == medio["versao"] + 1

    # 2. Cliente cadastrado no Keycloak (fixture cliente_a, via Admin REST API).
    # 3. Anonimo lista os veiculos a venda: ordem por preco ascendente.
    vitrine = api.a_venda()
    api.assert_ordenado_por_preco(vitrine)
    p_barato, p_medio, p_caro = api.posicoes(vitrine, [barato["id"], medio["id"], caro["id"]])
    assert p_barato < p_medio < p_caro

    # 4. Anonimo tenta comprar -> 401; gestor tenta comprar -> 403.
    api.assert_problema(api.comprar(None, medio["id"]), 401)
    api.assert_problema(api.comprar(gestor, medio["id"]), 403)
    assert api.veiculo(medio["id"])["status"] == "A_VENDA", "401/403 nao podem reservar o veiculo"

    # 5. Cliente compra -> 201 AGUARDANDO_PAGAMENTO; veiculo sai da vitrine.
    resposta = api.comprar(cliente_a, medio["id"])
    venda = api.assert_status(resposta, 201)
    assert resposta.headers.get("location", "").endswith(f"/vendas/{venda['id']}")
    assert venda["status"] == "AGUARDANDO_PAGAMENTO"
    assert venda["veiculo_id"] == medio["id"]
    assert Decimal(venda["preco_venda"]) == Decimal(novo_preco)
    assert isinstance(venda["preco_venda"], str)
    assert CODIGO_PAGAMENTO.match(venda["codigo_pagamento"]), venda["codigo_pagamento"]
    assert venda["veiculo"] == {
        "marca": medio["marca"],
        "modelo": medio["modelo"],
        "ano": medio["ano"],
        "cor": medio["cor"],
    }
    ttl = api.iso(venda["expira_em"]) - api.iso(venda["criada_em"])
    esperado = timedelta(minutes=api.cfg.reserva_ttl_minutos)
    assert abs(ttl - esperado) <= timedelta(seconds=5), ttl
    assert venda["efetivada_em"] is None
    assert venda["cancelada_em"] is None
    assert "comprador_id" not in venda, "cliente nao deve receber comprador_id"
    assert api.veiculo(medio["id"])["status"] == "RESERVADO"
    assert medio["id"] not in {v["id"] for v in api.a_venda()}

    # 6. Segundo cliente tenta comprar o mesmo veiculo -> 409.
    api.assert_problema(api.comprar(cliente_b, medio["id"]), 409, "veiculo-indisponivel")

    # 7. Gateway aprova o pagamento -> venda EFETIVADA, veiculo VENDIDO.
    efetivada = api.assert_status(api.webhook(venda["codigo_pagamento"], "APROVADO"), 200)
    assert efetivada["id"] == venda["id"]
    assert efetivada["status"] == "EFETIVADA"
    assert efetivada["efetivada_em"] is not None
    assert api.veiculo(medio["id"])["status"] == "VENDIDO"

    # 8. Vendidos ordenados por preco; "minhas compras" mostra EFETIVADA.
    vendidos = api.vendidos()
    api.assert_ordenado_por_preco(vendidos)
    api.posicoes(vendidos, [medio["id"]])
    minhas = {v["id"]: v for v in api.minhas(cliente_a)}
    assert minhas[venda["id"]]["status"] == "EFETIVADA"

    # BDD-01, cenario 2: notificacao repetida e idempotente.
    repetida = api.assert_status(api.webhook(venda["codigo_pagamento"], "APROVADO"), 200)
    assert repetida["status"] == "EFETIVADA"
    assert repetida["efetivada_em"] == efetivada["efetivada_em"]

    # Gestor ve a venda com o comprador (pseudonimo), cliente nao.
    visao_gestor = api.assert_status(api.venda(gestor, venda["id"]), 200)
    assert visao_gestor.get("comprador_id"), visao_gestor


def test_e2e_bdd02_pagamento_recusado_devolve_veiculo(api, gestor, cliente_a, preco, execucao):
    veiculo = api.cadastrar_veiculo(
        gestor, preco(68000), marca="Volkswagen", modelo=f"Polo [e2e {execucao}]", cor="Branco"
    )
    venda = api.comprar_ok(cliente_a, veiculo["id"])
    assert venda["status"] == "AGUARDANDO_PAGAMENTO"

    cancelada = api.assert_status(api.webhook(venda["codigo_pagamento"], "RECUSADO"), 200)
    assert cancelada["status"] == "CANCELADA"
    assert cancelada["motivo_cancelamento"] == "PAGAMENTO_RECUSADO"
    assert cancelada["cancelada_em"] is not None

    assert api.veiculo(veiculo["id"])["status"] == "A_VENDA"
    api.posicoes(api.a_venda(), [veiculo["id"]])
    minhas = {v["id"]: v for v in api.minhas(cliente_a)}
    assert minhas[venda["id"]]["status"] == "CANCELADA"

    # Recusa repetida e idempotente; aprovacao apos cancelamento e conflito.
    assert api.webhook(venda["codigo_pagamento"], "RECUSADO").status_code == 200
    api.assert_problema(
        api.webhook(venda["codigo_pagamento"], "APROVADO"), 409, "transicao-invalida"
    )


def test_e2e_webhook_aprovado_lista_vendidos_ordenados(
    api, gestor, cliente_a, cliente_b, preco, execucao
):
    """Dois veiculos vendidos (cadastrados fora de ordem) aparecem em vendidos por preco asc."""
    caro = api.cadastrar_veiculo(
        gestor, preco(120000), marca="Honda", modelo=f"HR-V [e2e {execucao}]", cor="Cinza"
    )
    barato = api.cadastrar_veiculo(
        gestor, preco(55000), marca="Renault", modelo=f"Sandero [e2e {execucao}]", cor="Azul"
    )
    for cliente, veiculo in ((cliente_a, caro), (cliente_b, barato)):
        venda = api.comprar_ok(cliente, veiculo["id"])
        efetivada = api.assert_status(api.webhook(venda["codigo_pagamento"], "APROVADO"), 200)
        assert efetivada["status"] == "EFETIVADA"

    vendidos = api.vendidos()
    api.assert_ordenado_por_preco(vendidos)
    p_barato, p_caro = api.posicoes(vendidos, [barato["id"], caro["id"]])
    assert p_barato < p_caro
    assert all(v["status"] == "VENDIDO" for v in vendidos)
    vitrine = {v["id"] for v in api.a_venda()}
    assert caro["id"] not in vitrine
    assert barato["id"] not in vitrine
