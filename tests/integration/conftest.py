"""Infraestrutura dos testes de integração: PostgreSQL real, migrações Alembic e a API.

- O banco vem de `TEST_DATABASE_URL`; sem ela, todos os testes desta pasta são pulados
  (com aviso no cabeçalho e no resumo `-ra`), para que `pytest` continue rodando sem banco.
- No início da sessão os schemas da aplicação são recriados com `alembic upgrade head`
  (valida as migrações a cada execução); antes de cada teste as tabelas são esvaziadas.
- A API é montada pelo caminho de produção (`criar_app`), com o JWKS servido por um
  servidor HTTP local (apoio/jwks.py) e relógio fixo.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from apoio.api import SEGREDO_WEBHOOK, Api
from apoio.banco import recriar_schemas
from apoio.cenario import AS_10H
from apoio.jwks import ServidorJwks
from apoio.tokens import AUDIENCIA, EMISSOR, KID, EmissorTokens
from revenda.main import criar_app
from revenda.shared.clock import RelogioFixo
from revenda.shared.config import Settings
from revenda.shared.db import BancoDeDados, criar_engine

VARIAVEL_URL = "TEST_DATABASE_URL"
_PASTA = Path(__file__).parent
_AVISO = (
    f"{VARIAVEL_URL} ausente: testes de integração PULADOS "
    "(ex.: postgresql+psycopg://revenda:revenda@localhost:5432/revenda_test)"
)


def _url_banco() -> str | None:
    return os.environ.get(VARIAVEL_URL) or None


def pytest_report_header() -> str | None:
    return None if _url_banco() else f"AVISO: {_AVISO}"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if _url_banco():
        return
    pular = pytest.mark.skip(reason=_AVISO)
    for item in items:
        if _PASTA in item.path.parents:
            item.add_marker(pular)


# ---------------------------------------------------------------- banco


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    url = _url_banco()
    assert url, _AVISO  # a coleta já pulou os testes; aqui é só garantia
    # Pool maior que o padrão: o teste de concorrência abre uma conexão por thread.
    engine = criar_engine(url, pool_size=12, max_overflow=4)
    recriar_schemas(engine)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _tabelas_vazias(engine: Engine) -> None:
    with engine.begin() as conexao:
        conexao.execute(text("TRUNCATE catalogo.veiculos, vendas.vendas"))


@pytest.fixture
def banco(engine: Engine) -> BancoDeDados:
    return BancoDeDados(engine)


# ---------------------------------------------------------------- identidade


@pytest.fixture(scope="session")
def emissor() -> EmissorTokens:
    return EmissorTokens()


@pytest.fixture(scope="session")
def servidor_jwks(emissor: EmissorTokens) -> Iterator[ServidorJwks]:
    with ServidorJwks({KID: emissor.chave_publica}).rodando() as servidor:
        yield servidor


# ---------------------------------------------------------------- aplicação


@pytest.fixture
def relogio() -> RelogioFixo:
    return RelogioFixo(AS_10H)


@pytest.fixture
def settings(servidor_jwks: ServidorJwks) -> Settings:
    url = _url_banco()
    assert url
    return Settings(
        database_url=url,
        oidc_issuer=EMISSOR,
        oidc_jwks_url=servidor_jwks.url,
        oidc_audience=AUDIENCIA,
        oidc_swagger_client_id="revenda-swagger",
        webhook_secret=SEGREDO_WEBHOOK,
        reserva_ttl_minutos=30,
        log_level="INFO",
    )


@pytest.fixture
def app(settings: Settings, banco: BancoDeDados, relogio: RelogioFixo) -> FastAPI:
    return criar_app(settings, banco=banco, relogio=relogio)


@pytest.fixture
def cliente_http(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as cliente:
        yield cliente


@pytest.fixture
def api(cliente_http: TestClient, emissor: EmissorTokens) -> Api:
    return Api(cliente_http, emissor)
