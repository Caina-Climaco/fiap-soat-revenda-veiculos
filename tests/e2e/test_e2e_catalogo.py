"""Catalogo: cadastro e edicao pelo gestor, listagens publicas (BDD-06 e BDD-09)."""

from __future__ import annotations

from decimal import Decimal

import pytest

pytestmark = pytest.mark.e2e

V1 = "/api/v1"


def test_e2e_cadastro_de_veiculo_pelo_gestor(api, gestor, preco, execucao):
    valor = preco(54900)
    veiculo = api.cadastrar_veiculo(
        gestor, valor, marca="Volkswagen", modelo=f"Gol [e2e {execucao}]", ano=2021, cor="Branco"
    )
    assert veiculo["status"] == "A_VENDA"
    assert veiculo["versao"] == 1
    assert veiculo["preco"] == valor
    assert isinstance(veiculo["preco"], str)
    assert veiculo["criado_em"].endswith("Z")
    assert veiculo["atualizado_em"].endswith("Z")

    consultado = api.veiculo(veiculo["id"])
    assert consultado == veiculo


def test_e2e_cadastro_exige_papel_gestor(api, cliente_a, preco, execucao):
    corpo = {
        "marca": "Fiat",
        "modelo": f"Uno [e2e {execucao}]",
        "ano": 2020,
        "cor": "Azul",
        "preco": preco(30000),
    }
    api.assert_problema(api.post(f"{V1}/veiculos", None, json=corpo), 401)
    api.assert_problema(api.post(f"{V1}/veiculos", cliente_a, json=corpo), 403)


def test_e2e_cadastro_invalido_retorna_422(api, gestor, execucao):
    corpo = {
        "marca": "Fiat",
        "modelo": f"Uno [e2e {execucao}]",
        "ano": 1949,
        "cor": "Azul",
        "preco": "0.00",
    }
    api.assert_problema(api.post(f"{V1}/veiculos", gestor, json=corpo), 422, "validacao")


def test_e2e_bdd06_edicao_de_veiculo_a_venda(api, gestor, preco, execucao):
    veiculo = api.cadastrar_veiculo(
        gestor, preco(95000), marca="Toyota", modelo=f"Corolla [e2e {execucao}]", ano=2019
    )
    novo = preco(90000)
    editado = api.assert_status(
        api.patch(f"{V1}/veiculos/{veiculo['id']}", gestor, {"preco": novo, "cor": "Prata"}), 200
    )
    assert editado["preco"] == novo
    assert editado["cor"] == "Prata"
    assert editado["versao"] == veiculo["versao"] + 1
    assert api.veiculo(veiculo["id"])["preco"] == novo


def test_e2e_bdd06_edicao_de_veiculo_reservado_retorna_409(api, gestor, cliente_a, preco, execucao):
    original = preco(95000)
    veiculo = api.cadastrar_veiculo(
        gestor, original, marca="Toyota", modelo=f"Corolla [e2e {execucao}]", ano=2019
    )
    venda = api.comprar_ok(cliente_a, veiculo["id"])

    resposta = api.patch(f"{V1}/veiculos/{veiculo['id']}", gestor, {"preco": preco(90000)})
    api.assert_problema(resposta, 409, "veiculo-nao-editavel")
    assert api.veiculo(veiculo["id"])["preco"] == original
    consultada = api.assert_status(api.venda(cliente_a, venda["id"]), 200)
    assert Decimal(consultada["preco_venda"]) == Decimal(original)

    # Limpeza: o comprador desiste e o veiculo volta a vitrine.
    cancelada = api.assert_status(api.post(f"{V1}/vendas/{venda['id']}/cancelar", cliente_a), 200)
    assert cancelada["status"] == "CANCELADA"
    assert cancelada["motivo_cancelamento"] == "DESISTENCIA_COMPRADOR"
    assert api.veiculo(veiculo["id"])["status"] == "A_VENDA"


def test_e2e_bdd09_listagem_a_venda_ordenada_por_preco(api, gestor, preco, execucao):
    """Cadastrados fora de ordem; a vitrine publica devolve por preco ascendente."""
    jeep = api.cadastrar_veiculo(
        gestor, preco(150000), marca="Jeep", modelo=f"Compass [e2e {execucao}]"
    )
    mobi = api.cadastrar_veiculo(
        gestor, preco(45000), marca="Fiat", modelo=f"Mobi [e2e {execucao}]"
    )
    argo = api.cadastrar_veiculo(
        gestor, preco(72000), marca="Fiat", modelo=f"Argo [e2e {execucao}]"
    )

    vitrine = api.a_venda()
    api.assert_ordenado_por_preco(vitrine)
    assert all(v["status"] == "A_VENDA" for v in vitrine)
    p_mobi, p_argo, p_jeep = api.posicoes(vitrine, [mobi["id"], argo["id"], jeep["id"]])
    assert p_mobi < p_argo < p_jeep

    # Paginacao mantem a ordem: a pagina que comeca no Mobi o traz primeiro.
    pagina = api.assert_status(
        api.get(f"{V1}/veiculos/a-venda", params={"limite": 2, "deslocamento": p_mobi}), 200
    )
    assert pagina["limite"] == 2
    assert pagina["deslocamento"] == p_mobi
    assert pagina["itens"][0]["id"] == mobi["id"]
    assert pagina["total"] >= 3
    assert len(pagina["itens"]) <= 2


def test_e2e_listagens_publicas_validam_paginacao(api):
    for caminho in (f"{V1}/veiculos/a-venda", f"{V1}/veiculos/vendidos"):
        api.assert_problema(api.get(caminho, params={"limite": 0}), 422)
        api.assert_problema(api.get(caminho, params={"limite": 101}), 422)
        api.assert_problema(api.get(caminho, params={"deslocamento": -1}), 422)
