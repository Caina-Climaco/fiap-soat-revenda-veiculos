"""Cria os schemas catalogo e vendas, as tabelas, constraints e índices (docs/06-dados.md).

Revision ID: 0001
Revises:
Create Date: 2026-10-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS catalogo")
    op.execute("CREATE SCHEMA IF NOT EXISTS vendas")

    op.create_table(
        "veiculos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("marca", sa.String(60), nullable=False),
        sa.Column("modelo", sa.String(60), nullable=False),
        sa.Column("ano", sa.SmallInteger(), nullable=False),
        sa.Column("cor", sa.String(30), nullable=False),
        sa.Column("preco", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default=sa.text("'A_VENDA'")),
        sa.Column("versao", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "atualizado_em",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_veiculos"),
        sa.CheckConstraint(
            "status IN ('A_VENDA', 'RESERVADO', 'VENDIDO')", name="ck_veiculos_status"
        ),
        sa.CheckConstraint("preco > 0", name="ck_veiculos_preco_positivo"),
        sa.CheckConstraint("ano BETWEEN 1950 AND 2100", name="ck_veiculos_ano_faixa"),
        sa.CheckConstraint(
            "length(trim(marca)) > 0 AND length(trim(modelo)) > 0 AND length(trim(cor)) > 0",
            name="ck_veiculos_textos_nao_vazios",
        ),
        sa.CheckConstraint("versao >= 1", name="ck_veiculos_versao"),
        schema="catalogo",
    )
    op.create_index("ix_veiculos_status_preco", "veiculos", ["status", "preco"], schema="catalogo")

    # Sem FK para catalogo.veiculos: referência lógica entre módulos (R4, ADR-004).
    op.create_table(
        "vendas",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("veiculo_id", sa.Uuid(), nullable=False),
        sa.Column("comprador_id", sa.String(255), nullable=False),
        sa.Column("preco_venda", sa.Numeric(12, 2), nullable=False),
        sa.Column("veiculo_marca", sa.String(60), nullable=False),
        sa.Column("veiculo_modelo", sa.String(60), nullable=False),
        sa.Column("veiculo_ano", sa.SmallInteger(), nullable=False),
        sa.Column("veiculo_cor", sa.String(30), nullable=False),
        sa.Column("status", sa.String(25), nullable=False),
        sa.Column("codigo_pagamento", sa.CHAR(16), nullable=False),
        sa.Column("expira_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "criada_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("efetivada_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelada_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("motivo_cancelamento", sa.String(30), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_vendas"),
        sa.UniqueConstraint("codigo_pagamento", name="uq_vendas_codigo_pagamento"),
        sa.CheckConstraint(
            "status IN ('AGUARDANDO_PAGAMENTO', 'EFETIVADA', 'CANCELADA')",
            name="ck_vendas_status",
        ),
        sa.CheckConstraint(
            "motivo_cancelamento IS NULL OR motivo_cancelamento IN ('PAGAMENTO_RECUSADO', "
            "'DESISTENCIA_COMPRADOR', 'CANCELADA_PELA_LOJA', 'RESERVA_EXPIRADA')",
            name="ck_vendas_motivo",
        ),
        sa.CheckConstraint("preco_venda > 0", name="ck_vendas_preco_positivo"),
        sa.CheckConstraint(
            "codigo_pagamento ~ '^PAG-[0-9a-f]{12}$'", name="ck_vendas_codigo_formato"
        ),
        sa.CheckConstraint("expira_em > criada_em", name="ck_vendas_expiracao"),
        sa.CheckConstraint(
            "(status = 'EFETIVADA') = (efetivada_em IS NOT NULL)",
            name="ck_vendas_efetivada_coerente",
        ),
        sa.CheckConstraint(
            "(status = 'CANCELADA') = "
            "(cancelada_em IS NOT NULL AND motivo_cancelamento IS NOT NULL)",
            name="ck_vendas_cancelada_coerente",
        ),
        schema="vendas",
    )
    op.create_index(
        "ux_vendas_veiculo_ativa",
        "vendas",
        ["veiculo_id"],
        unique=True,
        schema="vendas",
        postgresql_where=sa.text("status IN ('AGUARDANDO_PAGAMENTO', 'EFETIVADA')"),
    )
    op.create_index(
        "ix_vendas_comprador_criada",
        "vendas",
        ["comprador_id", sa.text("criada_em DESC")],
        schema="vendas",
    )
    op.create_index(
        "ix_vendas_status_criada", "vendas", ["status", sa.text("criada_em DESC")], schema="vendas"
    )
    op.create_index("ix_vendas_veiculo", "vendas", ["veiculo_id"], schema="vendas")
    op.create_index(
        "ix_vendas_expiracao_pendente",
        "vendas",
        ["expira_em"],
        schema="vendas",
        postgresql_where=sa.text("status = 'AGUARDANDO_PAGAMENTO'"),
    )


def downgrade() -> None:
    # Só para desenvolvimento: em produção o rollback é forward fix (docs/06-dados.md, 5.3).
    op.drop_table("vendas", schema="vendas")
    op.drop_table("veiculos", schema="catalogo")
    op.execute("DROP SCHEMA IF EXISTS vendas")
    op.execute("DROP SCHEMA IF EXISTS catalogo")
