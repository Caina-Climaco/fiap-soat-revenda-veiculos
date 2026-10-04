"""Preparação do banco dos testes de integração com as migrações Alembic do projeto."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, text

RAIZ_PROJETO = Path(__file__).resolve().parents[2]


def config_alembic(conexao: Connection) -> Config:
    """Config do alembic.ini da raiz, reaproveitando uma conexão aberta (ver migrations/env.py)."""
    config = Config(str(RAIZ_PROJETO / "alembic.ini"))
    config.attributes["connection"] = conexao
    return config


def recriar_schemas(engine: Engine) -> None:
    """Apaga os schemas da aplicação e aplica `alembic upgrade head` do zero."""
    with engine.begin() as conexao:
        conexao.execute(text("DROP SCHEMA IF EXISTS vendas CASCADE"))
        conexao.execute(text("DROP SCHEMA IF EXISTS catalogo CASCADE"))
        conexao.execute(text("DROP TABLE IF EXISTS public.alembic_version"))
        command.upgrade(config_alembic(conexao), "head")
