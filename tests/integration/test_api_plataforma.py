"""Saúde, OpenAPI/Swagger (OAuth2 + PKCE), autenticação via JWKS, erros e logs da API."""

from __future__ import annotations

import io
import json
import logging
import time
import uuid
from collections.abc import Iterator
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

import revenda.main
from apoio.api import SEGREDO_WEBHOOK, Api, tipo_problema
from apoio.jwks import ServidorJwks
from apoio.tokens import EmissorTokens
from revenda.main import criar_app
from revenda.shared.config import Settings
from revenda.shared.db import BancoDeDados, criar_engine
from revenda.shared.logging import FormatadorJson

# ---------------------------------------------------------------- saúde


def test_health_live_e_ready(api: Api) -> None:
    assert api.http.get("/health/live").json() == {"status": "ok"}
    pronto = api.http.get("/health/ready")
    assert pronto.status_code == 200
    assert pronto.json() == {"status": "ok", "verificacoes": {"banco": "ok"}}


def test_health_ready_503_sem_banco(settings: Settings) -> None:
    sem_banco = BancoDeDados(criar_engine("postgresql+psycopg://x:y@127.0.0.1:1/nada"))
    with TestClient(criar_app(settings, banco=sem_banco)) as cliente:
        assert cliente.get("/health/live").status_code == 200
        resposta = cliente.get("/health/ready")
    assert resposta.status_code == 503
    assert tipo_problema(resposta) == "indisponivel"
    assert resposta.json()["verificacoes"] == {"banco": "falha"}


def test_app_padrao_monta_o_banco_a_partir_das_settings(settings: Settings) -> None:
    with TestClient(criar_app(settings)) as cliente:
        assert cliente.get("/health/ready").status_code == 200


def test_app_do_uvicorn_e_criado_sob_demanda_a_partir_do_ambiente(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert settings.database_url
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("WEBHOOK_SECRET", SEGREDO_WEBHOOK)
    monkeypatch.setattr(revenda.main, "_app", None)
    app = revenda.main.app
    assert isinstance(app, FastAPI)
    assert revenda.main.app is app
    with pytest.raises(AttributeError):
        _ = revenda.main.nao_existe


# ---------------------------------------------------------------- OpenAPI / Swagger


def test_openapi_documenta_oauth2_pkce_e_problem_json(api: Api) -> None:
    esquema = api.http.get("/openapi.json").json()
    keycloak = esquema["components"]["securitySchemes"]["keycloak"]
    fluxo = keycloak["flows"]["authorizationCode"]
    assert fluxo["authorizationUrl"] == (
        "http://localhost:8180/realms/revenda/protocol/openid-connect/auth"
    )
    assert fluxo["tokenUrl"] == "http://localhost:8180/realms/revenda/protocol/openid-connect/token"
    assert esquema["components"]["securitySchemes"]["webhook"]["name"] == "X-Webhook-Secret"
    assert "Problema" in esquema["components"]["schemas"]

    rotas = esquema["paths"]
    assert set(rotas) >= {
        "/api/v1/veiculos",
        "/api/v1/veiculos/{veiculo_id}",
        "/api/v1/veiculos/a-venda",
        "/api/v1/veiculos/vendidos",
        "/api/v1/vendas",
        "/api/v1/vendas/minhas",
        "/api/v1/vendas/{venda_id}",
        "/api/v1/vendas/{venda_id}/cancelar",
        "/api/v1/pagamentos/webhook",
        "/health/live",
        "/health/ready",
    }
    compra = rotas["/api/v1/vendas"]["post"]
    assert set(compra["responses"]) >= {"201", "401", "403", "404", "409", "422"}
    assert "application/problem+json" in compra["responses"]["409"]["content"]
    preco = esquema["components"]["schemas"]["VeiculoResposta"]["properties"]["preco"]
    assert preco["type"] == "string"


def test_swagger_ui_usa_client_publico_com_pkce(api: Api) -> None:
    html = api.http.get("/docs").text
    assert '"clientId": "revenda-swagger"' in html
    assert '"usePkceWithAuthorizationCodeGrant": true' in html
    assert api.http.get("/docs/oauth2-redirect").status_code == 200


# ---------------------------------------------------------------- autenticação (JWKS)


def _decodificado(token: str) -> dict[str, Any]:
    return dict(jwt.decode(token, options={"verify_signature": False}))


@pytest.mark.parametrize(
    "ajuste",
    [
        {"expira_em_segundos": -60},  # expirado além da tolerância de 30 s
        {"iss": "http://outro-emissor/realms/revenda"},
        {"aud": ["account"]},
        {"azp": "client-desconhecido"},
        {"sub": "   "},
        {"kid": "kid-desconhecido"},
        {"chave": rsa.generate_private_key(public_exponent=65537, key_size=2048)},
        {"nbf": int(time.time()) + 3600},
    ],
    ids=["expirado", "iss", "aud", "azp", "sub-vazio", "kid", "assinatura", "nbf"],
)
def test_tokens_invalidos_recebem_401(
    api: Api, emissor: EmissorTokens, ajuste: dict[str, Any]
) -> None:
    resposta = api.http.get("/api/v1/vendas/minhas", headers=emissor.cabecalho(**ajuste))
    assert resposta.status_code == 401, resposta.text
    assert tipo_problema(resposta) == "nao-autenticado"


@pytest.mark.parametrize("cabecalho", ["Bearer abc.def", "Bearer ", "Basic dXN1YXJpbzpzZW5oYQ=="])
def test_cabecalhos_malformados_recebem_401(api: Api, cabecalho: str) -> None:
    resposta = api.http.get("/api/v1/vendas/minhas", headers={"Authorization": cabecalho})
    assert resposta.status_code == 401


def test_algoritmos_none_e_hs256_sao_recusados(api: Api, emissor: EmissorTokens) -> None:
    claims = _decodificado(emissor.emitir())
    sem_assinatura = jwt.encode(claims, None, algorithm="none", headers={"kid": "chave-de-teste"})
    simetrico = jwt.encode(
        claims,
        "segredo-simetrico-de-teste" * 2,
        algorithm="HS256",
        headers={"kid": "chave-de-teste"},
    )
    for token in (sem_assinatura, simetrico):
        resposta = api.http.get(
            "/api/v1/vendas/minhas", headers={"Authorization": f"Bearer {token}"}
        )
        assert resposta.status_code == 401


def test_jwks_e_buscado_uma_vez_e_mantido_em_cache(api: Api, servidor_jwks: ServidorJwks) -> None:
    antes = servidor_jwks.buscas
    for _ in range(3):
        assert api.http.get("/api/v1/vendas/minhas", headers=api.novo_cliente()).status_code == 200
    assert servidor_jwks.buscas - antes == 1


# ---------------------------------------------------------------- erros genéricos


@pytest.fixture
def app_com_falha(app: FastAPI) -> FastAPI:
    def explodir() -> None:
        raise RuntimeError("SELECT * FROM segredo -- detalhe interno")

    app.add_api_route("/falha", explodir)
    return app


def test_erro_inesperado_vira_500_sem_detalhes_internos(app_com_falha: FastAPI) -> None:
    with TestClient(app_com_falha, raise_server_exceptions=False) as cliente:
        resposta = cliente.get("/falha", headers={"X-Request-ID": "req-123"})
    assert resposta.status_code == 500
    assert tipo_problema(resposta) == "erro-interno"
    corpo = resposta.json()
    assert corpo["request_id"] == "req-123"
    assert "SELECT" not in resposta.text
    assert "Traceback" not in resposta.text


def test_rota_inexistente_e_metodo_nao_permitido_em_problem_json(api: Api) -> None:
    nao_existe = api.http.get("/api/v1/nao-existe")
    assert nao_existe.status_code == 404
    assert nao_existe.headers["content-type"].startswith("application/problem+json")
    assert nao_existe.json()["type"] == "about:blank"
    metodo = api.http.delete("/api/v1/veiculos/a-venda")
    assert metodo.status_code == 405
    assert metodo.json()["title"] == "Método não permitido"


# ---------------------------------------------------------------- correlação e logs


def test_x_request_id_e_propagado_ou_gerado(api: Api) -> None:
    assert (
        api.http.get("/health/live", headers={"X-Request-ID": "abc-1"}).headers["x-request-id"]
        == "abc-1"
    )
    gerado = api.http.get("/health/live").headers["x-request-id"]
    assert uuid.UUID(gerado)
    # Valores fora do padrão (ex.: tentativa de injeção em log) são descartados.
    injetado = api.http.get("/health/live", headers={"X-Request-ID": "a\tb"}).headers[
        "x-request-id"
    ]
    assert injetado != "a\tb"
    assert uuid.UUID(injetado)


@pytest.fixture
def logs(app: FastAPI) -> Iterator[io.StringIO]:
    """Captura o log JSON da aplicação (o handler é instalado depois de criar_app)."""
    saida = io.StringIO()
    handler = logging.StreamHandler(saida)
    handler.setFormatter(FormatadorJson())
    raiz = logging.getLogger()
    raiz.addHandler(handler)
    yield saida
    raiz.removeHandler(handler)


def test_logs_json_sem_token_sem_segredo_e_com_request_id(
    api: Api, logs: io.StringIO, emissor: EmissorTokens
) -> None:
    token = emissor.emitir(sub="sub-pseudonimo", papeis=["cliente"])
    veiculo = api.cadastrar()
    resposta = api.http.post(
        "/api/v1/vendas",
        json={"veiculo_id": veiculo["id"]},
        headers={"Authorization": f"Bearer {token}", "X-Request-ID": "req-log-1"},
    )
    codigo = resposta.json()["codigo_pagamento"]
    api.webhook(codigo, "APROVADO")

    texto = logs.getvalue()
    assert token not in texto
    assert token.split(".")[2] not in texto  # nem a assinatura isolada
    assert SEGREDO_WEBHOOK not in texto
    assert "Bearer" not in texto

    registros = [json.loads(linha) for linha in texto.splitlines() if linha.strip()]
    acesso = [r for r in registros if r.get("request_id") == "req-log-1" and "rota" in r]
    assert acesso == [
        {
            **acesso[0],
            "logger": "revenda.acesso",
            "metodo": "POST",
            "rota": "/api/v1/vendas",
            "status": 201,
            "sub": "sub-pseudonimo",
        }
    ]
    eventos = {r.get("evento") for r in registros if r.get("logger") == "revenda.eventos"}
    assert {"CompraIniciada", "VeiculoReservado", "VendaEfetivada", "VeiculoVendido"} <= eventos
    rotas = {r.get("rota") for r in registros if r.get("logger") == "revenda.acesso"}
    assert "/api/v1/veiculos/{veiculo_id}" in rotas or "/api/v1/pagamentos/webhook" in rotas


def test_erro_500_registra_um_unico_stack_trace_sem_parametros_do_banco(
    app: FastAPI, logs: io.StringIO
) -> None:
    banco: BancoDeDados = app.state.banco

    def consulta_quebrada() -> None:
        with banco.nova_sessao() as sessao:
            # Divisão por zero no PostgreSQL com um parâmetro "sensível".
            sessao.execute(
                text("SELECT CAST(:valor AS integer) / 0"), {"valor": "987654321"}
            ).scalar()

    app.add_api_route("/falha-banco", consulta_quebrada)
    # raise_server_exceptions=True: se a exceção escapasse do app (e chegasse ao uvicorn,
    # que registraria um segundo stack trace em uvicorn.error), o TestClient a relançaria.
    with TestClient(app, raise_server_exceptions=True) as cliente:
        resposta = cliente.get("/falha-banco", headers={"X-Request-ID": "req-500"})
    assert resposta.status_code == 500
    assert tipo_problema(resposta) == "erro-interno"

    registros = [json.loads(linha) for linha in logs.getvalue().splitlines() if linha.strip()]
    com_stack = [r for r in registros if "excecao" in r]
    assert len(com_stack) == 1
    erro = com_stack[0]
    assert (erro["logger"], erro["nivel"], erro["request_id"]) == (
        "revenda.erros",
        "ERROR",
        "req-500",
    )
    assert "DivisionByZero" in erro["excecao"]
    assert "987654321" not in logs.getvalue()  # hide_parameters=True
    assert not [r for r in registros if r["logger"].startswith("uvicorn")]
    acesso = [r for r in registros if r["logger"] == "revenda.acesso"]
    assert [(r["nivel"], r["status"], r["rota"]) for r in acesso] == [
        ("ERROR", 500, "/falha-banco")
    ]


def test_nivel_do_log_de_acesso_por_status(api: Api, logs: io.StringIO) -> None:
    api.http.get("/health/live")
    api.http.get("/api/v1/vendas/minhas")  # sem token: 401
    api.http.post("/api/v1/veiculos", json={}, headers=api.novo_cliente())  # cliente: 403
    registros = [json.loads(linha) for linha in logs.getvalue().splitlines() if linha.strip()]
    niveis = {r["status"]: r["nivel"] for r in registros if r["logger"] == "revenda.acesso"}
    assert niveis == {200: "INFO", 401: "WARNING", 403: "WARNING"}
