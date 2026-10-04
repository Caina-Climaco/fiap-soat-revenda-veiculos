"""Validação de entrada na API: caracteres de controle, tipos estritos, paginação e
mensagens sempre em português (varredura de payloads inválidos)."""

from __future__ import annotations

import re
from typing import Any

import pytest

from apoio.api import SEGREDO_WEBHOOK, Api, tipo_problema

BASE = {"marca": "Fiat", "modelo": "Argo", "ano": 2022, "cor": "Prata", "preco": "72000.00"}
# Fragmentos típicos das mensagens padrão do pydantic (em inglês).
_INGLES = re.compile(r"\b(should|Input|must|valid|or|Value|parse|exceeded|least|most)\b")


def _post_bruto(api: Api, corpo: str) -> Any:
    return api.http.post(
        "/api/v1/veiculos",
        content=corpo.encode(),
        headers={**api.gestor, "content-type": "application/json"},
    )


def _assert_422_em_portugues(resposta: Any) -> list[dict[str, str]]:
    assert resposta.status_code == 422, resposta.text
    assert tipo_problema(resposta) == "validacao"
    erros: list[dict[str, str]] = resposta.json()["erros"]
    assert erros
    for erro in erros:
        assert not _INGLES.search(erro["mensagem"]), erro
    return erros


# ---------------------------------------------------------------- caracteres de controle


@pytest.mark.parametrize("campo", ["marca", "modelo", "cor"])
@pytest.mark.parametrize("valor", ["a\u0000b", "a\u001fb", "Fiat\n", "\tFiat"])
def test_caracteres_de_controle_viram_422_e_nao_500(api: Api, campo: str, valor: str) -> None:
    resposta = api.http.post("/api/v1/veiculos", json={**BASE, campo: valor}, headers=api.gestor)
    erros = _assert_422_em_portugues(resposta)
    assert erros == [{"campo": campo, "mensagem": "não pode conter caracteres de controle"}]

    veiculo = api.cadastrar()
    edicao = api.http.patch(
        f"/api/v1/veiculos/{veiculo['id']}", json={campo: valor}, headers=api.gestor
    )
    assert _assert_422_em_portugues(edicao)[0]["campo"] == campo


# ---------------------------------------------------------------- tipos estritos


@pytest.mark.parametrize("bruto", ['"2020"', "2020.0", "2020.5", "true", "1e30"])
def test_ano_exige_inteiro_json(api: Api, bruto: str) -> None:
    corpo = '{"marca": "Fiat", "modelo": "Argo", "cor": "Prata", "preco": "1.00", "ano": %s}'
    erros = _assert_422_em_portugues(_post_bruto(api, corpo % bruto))
    assert erros == [{"campo": "ano", "mensagem": "deve ser um número inteiro"}]


@pytest.mark.parametrize(("bruto", "esperado"), [('"79900.00"', "79900.00"), ("79900", "79900.00")])
def test_preco_aceita_string_decimal_e_numero(api: Api, bruto: str, esperado: str) -> None:
    corpo = '{"marca": "Fiat", "modelo": "Argo", "cor": "Prata", "ano": 2022, "preco": %s}'
    resposta = _post_bruto(api, corpo % bruto)
    assert resposta.status_code == 201, resposta.text
    assert resposta.json()["preco"] == esperado


def test_openapi_recomenda_preco_como_string(api: Api) -> None:
    esquemas = api.http.get("/openapi.json").json()["components"]["schemas"]
    for nome in ("VeiculoCriacao", "VeiculoEdicao"):
        preco = esquemas[nome]["properties"]["preco"]
        if "anyOf" in preco and "examples" not in preco:  # VeiculoEdicao: Preco | None
            preco = {**preco, **next(p for p in preco["anyOf"] if "examples" in p)}
        assert preco["examples"] == ["79900.00"]
        assert "string decimal" in preco["description"]
    ano = esquemas["VeiculoCriacao"]["properties"]["ano"]
    assert ano["type"] == "integer"


# ---------------------------------------------------------------- varredura de mensagens

_INVALIDOS_VEICULO: list[str] = [
    '"marca": 1',
    '"marca": null',
    '"marca": ["a"]',
    '"marca": ""',
    '"cor": "%s"' % ("x" * 31),
    '"ano": "abc"',
    '"ano": 1900',
    '"preco": "abc"',
    '"preco": 1e400',
    '"preco": NaN',
    '"preco": "Infinity"',
    '"preco": true',
    '"preco": [1]',
    '"preco": {"a": 1}',
    '"preco": "1.234"',
    '"preco": "-1"',
    '"preco": "99999999999.00"',
    '"status": "A_VENDA"',
]


@pytest.mark.parametrize("campo", _INVALIDOS_VEICULO)
def test_varredura_veiculo_sem_mensagens_em_ingles(api: Api, campo: str) -> None:
    corpo = '{"marca": "Fiat", "modelo": "Argo", "cor": "Prata", "ano": 2022, "preco": "1.00"'
    _assert_422_em_portugues(_post_bruto(api, corpo + ", " + campo + "}"))


@pytest.mark.parametrize(
    "corpo",
    [[], "x", {}, {"veiculo_id": 1}, {"veiculo_id": "abc"}, {"veiculo_id": None}, {"x": 1}],
)
def test_varredura_venda_sem_mensagens_em_ingles(api: Api, corpo: Any) -> None:
    _assert_422_em_portugues(
        api.http.post("/api/v1/vendas", json=corpo, headers=api.novo_cliente())
    )


@pytest.mark.parametrize(
    "corpo",
    [
        {"codigo_pagamento": "x", "status": "APROVADO"},
        {"codigo_pagamento": 1, "status": "X"},
        {"codigo_pagamento": "PAG-000000000000", "status": None},
        {"codigo_pagamento": "PAG-000000000000", "status": "APROVADO", "extra": 1},
        [],
        {},
    ],
)
def test_varredura_webhook_sem_mensagens_em_ingles(api: Api, corpo: Any) -> None:
    resposta = api.http.post(
        "/api/v1/pagamentos/webhook", json=corpo, headers={"X-Webhook-Secret": SEGREDO_WEBHOOK}
    )
    _assert_422_em_portugues(resposta)


def test_enumeracoes_listam_opcoes_com_ou(api: Api) -> None:
    resposta = api.http.post(
        "/api/v1/pagamentos/webhook",
        json={"codigo_pagamento": "PAG-000000000000", "status": "TALVEZ"},
        headers={"X-Webhook-Secret": SEGREDO_WEBHOOK},
    )
    assert _assert_422_em_portugues(resposta) == [
        {"campo": "status", "mensagem": "deve ser um de: 'APROVADO' ou 'RECUSADO'"}
    ]
    filtro = api.http.get("/api/v1/vendas", params={"status": "X"}, headers=api.gestor)
    assert "' ou '" in _assert_422_em_portugues(filtro)[0]["mensagem"]


# ---------------------------------------------------------------- paginação


@pytest.mark.parametrize(
    "rota",
    [
        "/api/v1/veiculos/a-venda",
        "/api/v1/veiculos/vendidos",
        "/api/v1/vendas/minhas",
        "/api/v1/vendas",
    ],
)
def test_deslocamento_tem_teto_de_um_milhao(api: Api, rota: str) -> None:
    cabecalho = api.gestor if rota == "/api/v1/vendas" else api.novo_cliente()
    for valor in ("99999999999999999999", "1000001"):
        resposta = api.http.get(rota, params={"deslocamento": valor}, headers=cabecalho)
        erros = _assert_422_em_portugues(resposta)
        assert erros == [{"campo": "deslocamento", "mensagem": "deve ser menor ou igual a 1000000"}]
    no_teto = api.http.get(rota, params={"deslocamento": 1_000_000}, headers=cabecalho)
    assert no_teto.status_code == 200, no_teto.text
    assert no_teto.json()["itens"] == []
    assert no_teto.json()["deslocamento"] == 1_000_000
