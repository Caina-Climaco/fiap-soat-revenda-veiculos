"""Tabela `vendas.vendas` (docs/06-dados.md, seção 3.2). Só este módulo mapeia o schema.

`veiculo_id` é referência lógica a `catalogo.veiculos`, sem FK entre schemas (R4).
"""

from __future__ import annotations

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    text,
)

from revenda.shared.db import CONVENCAO_NOMES

SCHEMA = "vendas"

metadata = MetaData(schema=SCHEMA, naming_convention=CONVENCAO_NOMES)

INDICE_VENDA_ATIVA = "ux_vendas_veiculo_ativa"

vendas = Table(
    "vendas",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("veiculo_id", Uuid(as_uuid=True), nullable=False),
    Column("comprador_id", String(255), nullable=False),
    Column("preco_venda", Numeric(12, 2, asdecimal=True), nullable=False),
    Column("veiculo_marca", String(60), nullable=False),
    Column("veiculo_modelo", String(60), nullable=False),
    Column("veiculo_ano", SmallInteger, nullable=False),
    Column("veiculo_cor", String(30), nullable=False),
    Column("status", String(25), nullable=False),
    Column("codigo_pagamento", CHAR(16), nullable=False),
    Column("expira_em", DateTime(timezone=True), nullable=False),
    Column("criada_em", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("efetivada_em", DateTime(timezone=True), nullable=True),
    Column("cancelada_em", DateTime(timezone=True), nullable=True),
    Column("motivo_cancelamento", String(30), nullable=True),
    UniqueConstraint("codigo_pagamento", name="uq_vendas_codigo_pagamento"),
    CheckConstraint("status IN ('AGUARDANDO_PAGAMENTO', 'EFETIVADA', 'CANCELADA')", name="status"),
    CheckConstraint(
        "motivo_cancelamento IS NULL OR motivo_cancelamento IN ('PAGAMENTO_RECUSADO', "
        "'DESISTENCIA_COMPRADOR', 'CANCELADA_PELA_LOJA', 'RESERVA_EXPIRADA')",
        name="motivo",
    ),
    CheckConstraint("preco_venda > 0", name="preco_positivo"),
    CheckConstraint("codigo_pagamento ~ '^PAG-[0-9a-f]{12}$'", name="codigo_formato"),
    CheckConstraint("expira_em > criada_em", name="expiracao"),
    CheckConstraint(
        "(status = 'EFETIVADA') = (efetivada_em IS NOT NULL)", name="efetivada_coerente"
    ),
    CheckConstraint(
        "(status = 'CANCELADA') = (cancelada_em IS NOT NULL AND motivo_cancelamento IS NOT NULL)",
        name="cancelada_coerente",
    ),
    Index(
        INDICE_VENDA_ATIVA,
        "veiculo_id",
        unique=True,
        postgresql_where=text("status IN ('AGUARDANDO_PAGAMENTO', 'EFETIVADA')"),
    ),
    Index("ix_vendas_comprador_criada", "comprador_id", text("criada_em DESC")),
    Index("ix_vendas_status_criada", "status", text("criada_em DESC")),
    Index("ix_vendas_veiculo", "veiculo_id"),
    Index(
        "ix_vendas_expiracao_pendente",
        "expira_em",
        postgresql_where=text("status = 'AGUARDANDO_PAGAMENTO'"),
    ),
)
