"""Tabela `catalogo.veiculos` (docs/06-dados.md, seção 3.1). Só este módulo mapeia o schema."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Table,
    Uuid,
    text,
)

from revenda.shared.db import CONVENCAO_NOMES

SCHEMA = "catalogo"

metadata = MetaData(schema=SCHEMA, naming_convention=CONVENCAO_NOMES)

veiculos = Table(
    "veiculos",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("marca", String(60), nullable=False),
    Column("modelo", String(60), nullable=False),
    Column("ano", SmallInteger, nullable=False),
    Column("cor", String(30), nullable=False),
    Column("preco", Numeric(12, 2, asdecimal=True), nullable=False),
    Column("status", String(12), nullable=False, server_default=text("'A_VENDA'")),
    Column("versao", Integer, nullable=False, server_default=text("1")),
    Column("criado_em", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("atualizado_em", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    CheckConstraint("status IN ('A_VENDA', 'RESERVADO', 'VENDIDO')", name="status"),
    CheckConstraint("preco > 0", name="preco_positivo"),
    CheckConstraint("ano BETWEEN 1950 AND 2100", name="ano_faixa"),
    CheckConstraint(
        "length(trim(marca)) > 0 AND length(trim(modelo)) > 0 AND length(trim(cor)) > 0",
        name="textos_nao_vazios",
    ),
    CheckConstraint("versao >= 1", name="versao"),
    Index("ix_veiculos_status_preco", "status", "preco"),
)
