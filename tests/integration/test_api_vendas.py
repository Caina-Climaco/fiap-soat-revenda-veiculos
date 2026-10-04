"""API de Vendas e webhook com TestClient (docs/05-api.md, 4.8 a 4.13; docs/09-testes.md, BDD).

Tokens RS256 assinados pela chave de teste e validados pelo JWKS servido localmente; o
relógio da aplicação é fixo (10:00 UTC) e avançado manualmente nos cenários de expiração.
"""

from __future__ import annotations

import re
import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, text

from apoio.api import Api, tipo_problema
from revenda.shared.clock import RelogioFixo

CODIGO = re.compile(r"^PAG-[0-9a-f]{12}$")


def _contar_vendas(engine: Engine) -> int:
    with engine.connect() as conexao:
        return int(conexao.execute(text("SELECT count(*) FROM vendas.vendas")).scalar_one())


@pytest.fixture
def veiculo(api: Api) -> dict[str, Any]:
    return api.cadastrar(marca="Fiat", modelo="Argo", ano=2022, cor="Prata", preco="72000.00")


# ---------------------------------------------------------------- BDD-01


def test_bdd_01_compra_com_sucesso_e_efetivacao(api: Api, veiculo: dict[str, Any]) -> None:
    cliente = api.novo_cliente()
    resposta = api.comprar(veiculo["id"], cliente)
    assert resposta.status_code == 201
    venda = resposta.json()
    assert resposta.headers["location"] == f"/api/v1/vendas/{venda['id']}"
    assert venda["status"] == "AGUARDANDO_PAGAMENTO"
    assert venda["preco_venda"] == "72000.00"
    assert CODIGO.match(venda["codigo_pagamento"])
    assert (venda["criada_em"], venda["expira_em"]) == (
        "2026-10-03T10:00:00Z",
        "2026-10-03T10:30:00Z",
    )
    assert venda["veiculo"] == {"marca": "Fiat", "modelo": "Argo", "ano": 2022, "cor": "Prata"}
    assert (venda["efetivada_em"], venda["cancelada_em"], venda["motivo_cancelamento"]) == (
        None,
        None,
        None,
    )
    assert "comprador_id" not in venda
    assert api.a_venda()["total"] == 0
    assert api.veiculo(veiculo["id"])["status"] == "RESERVADO"

    resposta = api.webhook(venda["codigo_pagamento"], "APROVADO")
    assert resposta.status_code == 200
    efetivada = resposta.json()
    assert efetivada["status"] == "EFETIVADA"
    assert efetivada["efetivada_em"] == "2026-10-03T10:00:00Z"
    assert "comprador_id" not in efetivada
    assert api.veiculo(veiculo["id"])["status"] == "VENDIDO"
    assert [v["id"] for v in api.vendidos()["itens"]] == [veiculo["id"]]

    minhas = api.http.get("/api/v1/vendas/minhas", headers=cliente)
    assert minhas.status_code == 200
    assert [(v["id"], v["status"]) for v in minhas.json()["itens"]] == [(venda["id"], "EFETIVADA")]


def test_bdd_01_aprovacao_repetida_nao_tem_efeito(
    api: Api, veiculo: dict[str, Any], relogio: RelogioFixo
) -> None:
    venda = api.compra_ok(veiculo["id"], api.novo_cliente())
    primeira = api.webhook(venda["codigo_pagamento"], "APROVADO").json()
    relogio.avancar(timedelta(minutes=5))
    repetida = api.webhook(venda["codigo_pagamento"], "APROVADO")
    assert repetida.status_code == 200
    assert repetida.json() == primeira  # mesma data de efetivação
    assert api.veiculo(veiculo["id"])["versao"] == 3  # cadastro, reserva, venda


# ---------------------------------------------------------------- BDD-02


def test_bdd_02_pagamento_recusado(api: Api, veiculo: dict[str, Any]) -> None:
    venda = api.compra_ok(veiculo["id"], api.novo_cliente())
    resposta = api.webhook(venda["codigo_pagamento"], "RECUSADO")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert (corpo["status"], corpo["motivo_cancelamento"]) == ("CANCELADA", "PAGAMENTO_RECUSADO")
    assert corpo["cancelada_em"] == "2026-10-03T10:00:00Z"
    assert api.veiculo(veiculo["id"])["status"] == "A_VENDA"
    assert [v["id"] for v in api.a_venda()["itens"]] == [veiculo["id"]]
    # O veículo pode ser comprado de novo (nova venda, a cancelada não ocupa o veículo).
    assert api.comprar(veiculo["id"], api.novo_cliente()).status_code == 201


# ---------------------------------------------------------------- BDD-04 / BDD-05


def test_bdd_04_compra_sem_cadastro(api: Api, veiculo: dict[str, Any], engine: Engine) -> None:
    resposta = api.comprar(veiculo["id"], None)
    assert resposta.status_code == 401
    assert tipo_problema(resposta) == "nao-autenticado"
    assert api.veiculo(veiculo["id"])["status"] == "A_VENDA"
    assert _contar_vendas(engine) == 0


@pytest.mark.parametrize("papeis", [["gestor"], ["gestor", "cliente"]])
def test_bdd_05_gestor_tentando_comprar(
    api: Api, veiculo: dict[str, Any], engine: Engine, papeis: list[str]
) -> None:
    """RN-05: gestor não compra, mesmo que o token também tenha o papel cliente."""
    resposta = api.comprar(veiculo["id"], api.emissor.cabecalho(papeis=papeis))
    assert resposta.status_code == 403
    assert tipo_problema(resposta) == "acesso-negado"
    assert api.veiculo(veiculo["id"])["status"] == "A_VENDA"
    assert _contar_vendas(engine) == 0


def test_token_sem_papel_e_403(api: Api, veiculo: dict[str, Any]) -> None:
    resposta = api.comprar(veiculo["id"], api.emissor.cabecalho(papeis=[]))
    assert resposta.status_code == 403


# ---------------------------------------------------------------- erros da compra


def test_compra_de_veiculo_inexistente_indisponivel_e_payload_invalido(
    api: Api, veiculo: dict[str, Any]
) -> None:
    cliente = api.novo_cliente()
    resposta = api.comprar(str(uuid.uuid4()), cliente)
    assert resposta.status_code == 404
    assert tipo_problema(resposta) == "veiculo-nao-encontrado"

    api.compra_ok(veiculo["id"], cliente)
    segundo = api.comprar(veiculo["id"], api.novo_cliente())
    assert segundo.status_code == 409
    assert tipo_problema(segundo) == "veiculo-indisponivel"
    assert "RESERVADO" in segundo.json()["detail"]

    for corpo in ({}, {"veiculo_id": "abc"}, {"veiculo_id": veiculo["id"], "comprador": "x"}):
        invalido = api.http.post("/api/v1/vendas", json=corpo, headers=cliente)
        assert invalido.status_code == 422, corpo


# ---------------------------------------------------------------- BDD-07


@pytest.mark.parametrize(
    "segredo", [None, "", "segredo-errado"], ids=["ausente", "vazio", "errado"]
)
def test_bdd_07_webhook_com_segredo_invalido(
    api: Api, veiculo: dict[str, Any], segredo: str | None
) -> None:
    venda = api.compra_ok(veiculo["id"], api.novo_cliente())
    resposta = api.webhook(venda["codigo_pagamento"], "APROVADO", segredo=segredo)
    assert resposta.status_code == 401
    assert tipo_problema(resposta) == "webhook-nao-autorizado"
    assert api.vendas_do_gestor()["itens"][0]["status"] == "AGUARDANDO_PAGAMENTO"
    assert api.veiculo(veiculo["id"])["status"] == "RESERVADO"


# ---------------------------------------------------------------- BDD-08


@pytest.fixture
def compra_do_cliente_a(api: Api, veiculo: dict[str, Any]) -> dict[str, Any]:
    """Contexto do BDD-08: cliente A iniciou a compra às 10:00; TTL de 30 minutos."""
    return api.compra_ok(veiculo["id"], api.novo_cliente("cliente-a"))


def test_bdd_08_outro_cliente_compra_apos_expiracao(
    api: Api, veiculo: dict[str, Any], compra_do_cliente_a: dict[str, Any], relogio: RelogioFixo
) -> None:
    relogio.avancar(timedelta(minutes=31))
    cliente_b = api.novo_cliente("cliente-b")
    resposta = api.comprar(veiculo["id"], cliente_b)
    assert resposta.status_code == 201
    vendas = {v["comprador_id"]: v for v in api.vendas_do_gestor()["itens"]}
    assert vendas["cliente-a"]["status"] == "CANCELADA"
    assert vendas["cliente-a"]["motivo_cancelamento"] == "RESERVA_EXPIRADA"
    ativas = [v for v in vendas.values() if v["status"] != "CANCELADA"]
    assert [v["comprador_id"] for v in ativas] == ["cliente-b"]


def test_bdd_08_pagamento_aprovado_apos_expiracao(
    api: Api, veiculo: dict[str, Any], compra_do_cliente_a: dict[str, Any], relogio: RelogioFixo
) -> None:
    relogio.avancar(timedelta(minutes=31))
    resposta = api.webhook(compra_do_cliente_a["codigo_pagamento"], "APROVADO")
    assert resposta.status_code == 409
    assert tipo_problema(resposta) == "reserva-expirada"
    venda = api.venda(compra_do_cliente_a["id"], api.gestor).json()
    assert (venda["status"], venda["motivo_cancelamento"]) == ("CANCELADA", "RESERVA_EXPIRADA")
    assert api.veiculo(veiculo["id"])["status"] == "A_VENDA"


def test_bdd_08_veiculo_com_reserva_vencida_volta_a_vitrine(
    api: Api, veiculo: dict[str, Any], compra_do_cliente_a: dict[str, Any], relogio: RelogioFixo
) -> None:
    relogio.avancar(timedelta(minutes=29))
    assert api.a_venda()["total"] == 0  # ainda dentro do prazo
    relogio.avancar(timedelta(minutes=2))
    assert [v["id"] for v in api.a_venda()["itens"]] == [veiculo["id"]]


def test_recusa_apos_expiracao_cancela_por_expiracao(
    api: Api, compra_do_cliente_a: dict[str, Any], relogio: RelogioFixo
) -> None:
    relogio.avancar(timedelta(minutes=30))  # expira_em é exclusivo: às 10:30 já venceu
    resposta = api.webhook(compra_do_cliente_a["codigo_pagamento"], "RECUSADO")
    assert resposta.status_code == 200
    assert resposta.json()["motivo_cancelamento"] == "RESERVA_EXPIRADA"


# ---------------------------------------------------------------- webhook (R2)


def test_webhook_tabela_de_estados(api: Api, veiculo: dict[str, Any]) -> None:
    venda = api.compra_ok(veiculo["id"], api.novo_cliente())
    codigo = venda["codigo_pagamento"]
    api.webhook(codigo, "APROVADO")
    recusa_de_efetivada = api.webhook(codigo, "RECUSADO")
    assert recusa_de_efetivada.status_code == 409
    assert tipo_problema(recusa_de_efetivada) == "transicao-invalida"

    outro = api.cadastrar(modelo="Mobi", preco="45000.00")
    cancelada = api.compra_ok(outro["id"], api.novo_cliente())
    assert api.webhook(cancelada["codigo_pagamento"], "RECUSADO").status_code == 200
    repetida = api.webhook(cancelada["codigo_pagamento"], "RECUSADO")
    assert repetida.status_code == 200
    assert repetida.json()["motivo_cancelamento"] == "PAGAMENTO_RECUSADO"
    aprovacao_de_cancelada = api.webhook(cancelada["codigo_pagamento"], "APROVADO")
    assert aprovacao_de_cancelada.status_code == 409
    assert tipo_problema(aprovacao_de_cancelada) == "transicao-invalida"


def test_webhook_codigo_desconhecido_e_payload_invalido(api: Api) -> None:
    resposta = api.webhook("PAG-0123456789ab", "APROVADO")
    assert resposta.status_code == 404
    assert tipo_problema(resposta) == "pagamento-nao-encontrado"
    for codigo, status in [("PAG-XYZ", "APROVADO"), ("PAG-0123456789ab", "PAGO")]:
        invalido = api.webhook(codigo, status)
        assert invalido.status_code == 422
        assert tipo_problema(invalido) == "validacao"


# ---------------------------------------------------------------- consulta e listagens (R3)


def test_consulta_de_venda_dono_gestor_e_nao_dono(api: Api, veiculo: dict[str, Any]) -> None:
    dono = api.novo_cliente("dono")
    venda = api.compra_ok(veiculo["id"], dono)

    do_dono = api.venda(venda["id"], dono)
    assert do_dono.status_code == 200
    assert "comprador_id" not in do_dono.json()

    do_gestor = api.venda(venda["id"], api.gestor)
    assert do_gestor.status_code == 200
    assert do_gestor.json()["comprador_id"] == "dono"

    # R3: para quem não é dono, a venda "não existe" (não vaza existência).
    de_outro = api.venda(venda["id"], api.novo_cliente())
    assert de_outro.status_code == 404
    assert tipo_problema(de_outro) == "venda-nao-encontrada"
    inexistente = api.venda(str(uuid.uuid4()), dono)
    assert inexistente.status_code == 404
    # Mesma resposta (exceto o id) para venda de outro e venda inexistente.
    assert de_outro.json()["title"] == inexistente.json()["title"]
    assert de_outro.json()["detail"] == f"A venda {venda['id']} não existe."

    assert api.http.get(f"/api/v1/vendas/{venda['id']}").status_code == 401
    sem_papel = api.venda(venda["id"], api.emissor.cabecalho(papeis=["outro"]))
    assert sem_papel.status_code == 403


def test_listagens_de_vendas(api: Api, veiculo: dict[str, Any], relogio: RelogioFixo) -> None:
    cliente = api.novo_cliente("comprador-1")
    primeira = api.compra_ok(veiculo["id"], cliente)
    api.webhook(primeira["codigo_pagamento"], "RECUSADO")
    relogio.avancar(timedelta(minutes=1))
    segunda = api.compra_ok(veiculo["id"], cliente)
    api.compra_ok(api.cadastrar(modelo="Mobi")["id"], api.novo_cliente("comprador-2"))

    minhas = api.http.get("/api/v1/vendas/minhas", headers=cliente).json()
    assert [v["id"] for v in minhas["itens"]] == [segunda["id"], primeira["id"]]  # mais recente
    assert minhas["total"] == 2
    assert all("comprador_id" not in v for v in minhas["itens"])
    pagina = api.http.get(
        "/api/v1/vendas/minhas", params={"limite": 1, "deslocamento": 1}, headers=cliente
    ).json()
    assert ([v["id"] for v in pagina["itens"]], pagina["total"]) == ([primeira["id"]], 2)

    todas = api.vendas_do_gestor()
    assert todas["total"] == 3
    assert all("comprador_id" in v for v in todas["itens"])
    canceladas = api.vendas_do_gestor(status="CANCELADA")
    assert [v["id"] for v in canceladas["itens"]] == [primeira["id"]]
    invalida = api.http.get("/api/v1/vendas", params={"status": "PAGA"}, headers=api.gestor)
    assert invalida.status_code == 422

    assert api.http.get("/api/v1/vendas", headers=cliente).status_code == 403
    assert api.http.get("/api/v1/vendas").status_code == 401
    assert api.http.get("/api/v1/vendas/minhas").status_code == 401
    assert api.http.get("/api/v1/vendas/minhas", headers=api.gestor).status_code == 403


# ---------------------------------------------------------------- cancelamento (R5)


def test_cancelamento_pelo_dono_e_pela_loja(api: Api) -> None:
    dono = api.novo_cliente()
    primeiro = api.cadastrar(modelo="Argo")
    venda = api.compra_ok(primeiro["id"], dono)
    resposta = api.http.post(f"/api/v1/vendas/{venda['id']}/cancelar", headers=dono)
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert (corpo["status"], corpo["motivo_cancelamento"]) == ("CANCELADA", "DESISTENCIA_COMPRADOR")
    assert "comprador_id" not in corpo
    assert api.veiculo(primeiro["id"])["status"] == "A_VENDA"

    segundo = api.cadastrar(modelo="Mobi")
    venda = api.compra_ok(segundo["id"], dono)
    resposta = api.http.post(f"/api/v1/vendas/{venda['id']}/cancelar", headers=api.gestor)
    assert resposta.status_code == 200
    assert resposta.json()["motivo_cancelamento"] == "CANCELADA_PELA_LOJA"
    assert "comprador_id" in resposta.json()

    repetido = api.http.post(f"/api/v1/vendas/{venda['id']}/cancelar", headers=dono)
    assert repetido.status_code == 409
    assert tipo_problema(repetido) == "transicao-invalida"


def test_cancelamento_negado(api: Api, veiculo: dict[str, Any], relogio: RelogioFixo) -> None:
    dono = api.novo_cliente()
    venda = api.compra_ok(veiculo["id"], dono)
    url = f"/api/v1/vendas/{venda['id']}/cancelar"
    assert api.http.post(url).status_code == 401
    nao_dono = api.http.post(url, headers=api.novo_cliente())
    assert nao_dono.status_code == 404
    assert tipo_problema(nao_dono) == "venda-nao-encontrada"
    assert api.http.post(f"/api/v1/vendas/{uuid.uuid4()}/cancelar", headers=dono).status_code == 404

    api.webhook(venda["codigo_pagamento"], "APROVADO")
    efetivada = api.http.post(url, headers=dono)
    assert efetivada.status_code == 409
    assert tipo_problema(efetivada) == "transicao-invalida"

    outro = api.cadastrar(modelo="Mobi")
    vencida = api.compra_ok(outro["id"], dono)
    relogio.avancar(timedelta(hours=1))
    resposta = api.http.post(f"/api/v1/vendas/{vencida['id']}/cancelar", headers=dono)
    assert resposta.status_code == 200
    assert resposta.json()["motivo_cancelamento"] == "RESERVA_EXPIRADA"


def test_leituras_aplicam_a_expiracao_antes_de_consultar(
    api: Api, veiculo: dict[str, Any], relogio: RelogioFixo
) -> None:
    """Nenhuma leitura mostra reserva vencida como ativa (relógio fixo, TTL de 30 min)."""
    cliente = api.novo_cliente("cliente-leitura")
    compra = api.compra_ok(veiculo["id"], cliente)
    relogio.avancar(timedelta(minutes=29))
    assert api.veiculo(veiculo["id"])["status"] == "RESERVADO"
    relogio.avancar(timedelta(minutes=1))  # 10:30: venceu

    # 1) consulta do veículo: a reserva vencida é cancelada antes da leitura
    assert api.veiculo(veiculo["id"])["status"] == "A_VENDA"
    venda = api.venda(compra["id"], cliente).json()
    assert (venda["status"], venda["motivo_cancelamento"]) == ("CANCELADA", "RESERVA_EXPIRADA")


@pytest.mark.parametrize("leitura", ["venda", "minhas", "gestor"])
def test_cada_leitura_de_vendas_expira_sozinha(
    api: Api, veiculo: dict[str, Any], relogio: RelogioFixo, leitura: str
) -> None:
    cliente = api.novo_cliente("cliente-leitura")
    compra = api.compra_ok(veiculo["id"], cliente)
    relogio.avancar(timedelta(minutes=31))
    if leitura == "venda":
        vista = api.venda(compra["id"], cliente).json()
    elif leitura == "minhas":
        vista = api.http.get("/api/v1/vendas/minhas", headers=cliente).json()["itens"][0]
    else:
        vista = api.vendas_do_gestor(status="AGUARDANDO_PAGAMENTO")
        assert vista["total"] == 0
        vista = api.vendas_do_gestor()["itens"][0]
    assert (vista["status"], vista["motivo_cancelamento"]) == ("CANCELADA", "RESERVA_EXPIRADA")
    assert vista["cancelada_em"] == "2026-10-03T10:31:00Z"
    # o veículo foi liberado na mesma transação da leitura
    assert api.a_venda()["itens"][0]["id"] == veiculo["id"]
