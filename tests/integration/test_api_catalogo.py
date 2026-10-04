"""API do Catálogo com TestClient (docs/05-api.md, seções 1 e 4.3 a 4.7); BDD-06 e BDD-09."""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest

from apoio.api import Api, tipo_problema

DATA_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def test_cadastro_201_com_location_e_convencoes_de_formato(api: Api) -> None:
    resposta = api.http.post(
        "/api/v1/veiculos",
        json={
            "marca": "  Volkswagen ",
            "modelo": "Gol 1.0",
            "ano": 2021,
            "cor": "Branco",
            "preco": "54900",
        },
        headers=api.gestor,
    )
    assert resposta.status_code == 201
    corpo = resposta.json()
    assert resposta.headers["location"] == f"/api/v1/veiculos/{corpo['id']}"
    assert resposta.headers["content-type"].startswith("application/json")
    assert corpo["marca"] == "Volkswagen"
    assert corpo["preco"] == "54900.00"  # string decimal com 2 casas, nunca float
    assert (corpo["status"], corpo["versao"]) == ("A_VENDA", 1)
    assert corpo["criado_em"] == "2026-10-03T10:00:00Z"
    assert DATA_UTC.match(corpo["atualizado_em"])
    assert api.veiculo(corpo["id"]) == corpo


@pytest.mark.parametrize(
    ("campos", "campo_com_erro"),
    [
        ({"ano": 1949}, "ano"),
        ({"ano": 2028}, "ano"),  # ano corrente (2026, relógio fixo) + 2
        ({"preco": "0.00"}, "preco"),
        ({"preco": 1.234}, "preco"),
        ({"preco": "abc"}, "preco"),
        ({"marca": ""}, "marca"),
        ({"marca": "   "}, "marca"),
        ({"cor": "x" * 31}, "cor"),
        ({"status": "VENDIDO"}, "status"),
    ],
)
def test_cadastro_invalido_422_com_lista_de_erros(
    api: Api, campos: dict[str, Any], campo_com_erro: str
) -> None:
    payload = {"marca": "Fiat", "modelo": "Uno", "ano": 2020, "cor": "Azul", "preco": "100.00"}
    resposta = api.http.post("/api/v1/veiculos", json=payload | campos, headers=api.gestor)
    assert resposta.status_code == 422
    assert tipo_problema(resposta) == "validacao"
    corpo = resposta.json()
    assert corpo["instance"] == "/api/v1/veiculos"
    assert campo_com_erro in {e["campo"] for e in corpo["erros"]}


def test_cadastro_sem_campos_e_json_malformado(api: Api) -> None:
    resposta = api.http.post("/api/v1/veiculos", json={}, headers=api.gestor)
    assert resposta.status_code == 422
    assert {e["campo"] for e in resposta.json()["erros"]} == {
        "marca",
        "modelo",
        "ano",
        "cor",
        "preco",
    }

    resposta = api.http.post(
        "/api/v1/veiculos",
        content=b'{"marca": "Fiat",',
        headers={**api.gestor, "Content-Type": "application/json"},
    )
    assert resposta.status_code == 400
    assert tipo_problema(resposta) == "requisicao-malformada"


def test_cadastro_exige_gestor(api: Api) -> None:
    payload = {"marca": "Fiat", "modelo": "Uno", "ano": 2020, "cor": "Azul", "preco": "1.00"}
    sem_token = api.http.post("/api/v1/veiculos", json=payload)
    assert sem_token.status_code == 401
    assert tipo_problema(sem_token) == "nao-autenticado"
    assert sem_token.headers["www-authenticate"] == "Bearer"
    cliente = api.http.post("/api/v1/veiculos", json=payload, headers=api.novo_cliente())
    assert cliente.status_code == 403
    assert tipo_problema(cliente) == "acesso-negado"
    assert api.a_venda()["total"] == 0


def test_edicao_parcial_merge(api: Api) -> None:
    veiculo = api.cadastrar(preco="54900.00")
    resposta = api.http.patch(
        f"/api/v1/veiculos/{veiculo['id']}", json={"preco": "52900.00"}, headers=api.gestor
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert (corpo["preco"], corpo["versao"], corpo["marca"]) == ("52900.00", 2, "Fiat")


@pytest.mark.parametrize(
    "corpo",
    [{}, {"status": "VENDIDO"}, {"versao": 9}, {"preco": None}, {"criado_em": "2020-01-01"}],
)
def test_edicao_invalida_422(api: Api, corpo: dict[str, Any]) -> None:
    veiculo = api.cadastrar()
    resposta = api.http.patch(f"/api/v1/veiculos/{veiculo['id']}", json=corpo, headers=api.gestor)
    assert resposta.status_code == 422, resposta.text
    assert tipo_problema(resposta) == "validacao"


def test_edicao_de_veiculo_inexistente_e_permissoes(api: Api) -> None:
    inexistente = f"/api/v1/veiculos/{uuid.uuid4()}"
    resposta = api.http.patch(inexistente, json={"cor": "Azul"}, headers=api.gestor)
    assert resposta.status_code == 404
    assert tipo_problema(resposta) == "veiculo-nao-encontrado"
    assert api.http.patch(inexistente, json={"cor": "Azul"}).status_code == 401
    cliente = api.http.patch(inexistente, json={"cor": "Azul"}, headers=api.novo_cliente())
    assert cliente.status_code == 403


def test_bdd_06_edicao_de_veiculo_reservado(api: Api) -> None:
    """BDD-06: gestor não altera preço de veículo reservado; o preço de venda fica congelado."""
    veiculo = api.cadastrar(marca="Toyota", modelo="Corolla", ano=2019, preco="95000.00")
    venda = api.compra_ok(veiculo["id"], api.novo_cliente())

    resposta = api.http.patch(
        f"/api/v1/veiculos/{veiculo['id']}", json={"preco": "90000.00"}, headers=api.gestor
    )
    assert resposta.status_code == 409
    assert tipo_problema(resposta) == "veiculo-nao-editavel"
    assert api.veiculo(veiculo["id"])["preco"] == "95000.00"
    assert api.vendas_do_gestor()["itens"][0]["preco_venda"] == "95000.00"
    assert venda["preco_venda"] == "95000.00"


def test_bdd_06_edicao_de_veiculo_a_venda(api: Api) -> None:
    veiculo = api.cadastrar(marca="Toyota", modelo="Corolla", ano=2019, preco="95000.00")
    resposta = api.http.patch(
        f"/api/v1/veiculos/{veiculo['id']}", json={"preco": "90000.00"}, headers=api.gestor
    )
    assert resposta.status_code == 200
    assert api.veiculo(veiculo["id"])["preco"] == "90000.00"


def test_consulta_de_veiculo(api: Api) -> None:
    resposta = api.http.get(f"/api/v1/veiculos/{uuid.uuid4()}")
    assert resposta.status_code == 404
    assert tipo_problema(resposta) == "veiculo-nao-encontrado"
    resposta = api.http.get("/api/v1/veiculos/nao-e-uuid")
    assert resposta.status_code == 422
    assert resposta.json()["erros"] == [
        {"campo": "veiculo_id", "mensagem": "deve ser um UUID válido"}
    ]


@pytest.fixture
def estoque_bdd_09(api: Api) -> dict[str, str]:
    ids: dict[str, str] = {}
    for nome, preco in [
        ("Fiat Mobi 2020", "45000.00"),
        ("Jeep Compass 2022", "150000.00"),
        ("Fiat Argo 2022", "72000.00"),
        ("Honda HR-V 2021", "120000.00"),
        ("Renault Sandero 2019", "55000.00"),
    ]:
        marca, modelo, ano = nome.split(" ")
        ids[nome] = api.cadastrar(marca=marca, modelo=modelo, ano=int(ano), preco=preco)["id"]
    for vendido in ("Honda HR-V 2021", "Renault Sandero 2019"):
        venda = api.compra_ok(ids[vendido], api.novo_cliente())
        assert api.webhook(venda["codigo_pagamento"], "APROVADO").status_code == 200
    return {v: k for k, v in ids.items()}


def _nomes(pagina: dict[str, Any], nomes_por_id: dict[str, str]) -> list[str]:
    return [nomes_por_id[item["id"]] for item in pagina["itens"]]


def test_bdd_09_a_venda_do_mais_barato_ao_mais_caro(
    api: Api, estoque_bdd_09: dict[str, str]
) -> None:
    pagina = api.a_venda()
    assert _nomes(pagina, estoque_bdd_09) == [
        "Fiat Mobi 2020",
        "Fiat Argo 2022",
        "Jeep Compass 2022",
    ]
    assert (pagina["total"], pagina["limite"], pagina["deslocamento"]) == (3, 20, 0)


def test_bdd_09_vendidos_do_mais_barato_ao_mais_caro(
    api: Api, estoque_bdd_09: dict[str, str]
) -> None:
    pagina = api.vendidos()
    assert _nomes(pagina, estoque_bdd_09) == ["Renault Sandero 2019", "Honda HR-V 2021"]
    assert pagina["total"] == 2
    assert all(item["status"] == "VENDIDO" for item in pagina["itens"])


def test_bdd_09_paginacao_mantem_a_ordem(api: Api, estoque_bdd_09: dict[str, str]) -> None:
    pagina = api.a_venda(limite=2, deslocamento=2)
    assert _nomes(pagina, estoque_bdd_09) == ["Jeep Compass 2022"]
    assert (pagina["total"], pagina["limite"], pagina["deslocamento"]) == (3, 2, 2)


@pytest.mark.parametrize(
    "params",
    [{"limite": 0}, {"limite": 101}, {"deslocamento": -1}, {"limite": "dez"}],
)
@pytest.mark.parametrize("rota", ["/api/v1/veiculos/a-venda", "/api/v1/veiculos/vendidos"])
def test_paginacao_invalida_422(api: Api, rota: str, params: dict[str, Any]) -> None:
    resposta = api.http.get(rota, params=params)
    assert resposta.status_code == 422
    assert tipo_problema(resposta) == "validacao"
