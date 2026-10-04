"""Migrações Alembic e o modelo físico de docs/06-dados.md (constraints, índices, R4, LGPD)."""

from __future__ import annotations

import re
from typing import Any

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect, text

from apoio.banco import config_alembic, recriar_schemas
from revenda.catalogo.infrastructure.tabelas import metadata as metadata_catalogo
from revenda.vendas.infrastructure.tabelas import metadata as metadata_vendas


def _consulta(engine: Engine, sql: str, **params: Any) -> list[Any]:
    with engine.connect() as conexao:
        return list(conexao.execute(text(sql), params))


def test_migracao_cria_schemas_tabelas_e_versao(engine: Engine) -> None:
    schemas = {
        r[0]
        for r in _consulta(
            engine,
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name IN ('catalogo', 'vendas')",
        )
    }
    assert schemas == {"catalogo", "vendas"}
    inspetor = inspect(engine)
    assert inspetor.get_table_names(schema="catalogo") == ["veiculos"]
    assert inspetor.get_table_names(schema="vendas") == ["vendas"]
    assert _consulta(engine, "SELECT version_num FROM public.alembic_version") == [("0001",)]


def test_constraints_com_os_nomes_do_documento_de_dados(engine: Engine) -> None:
    nomes = {
        r[0]
        for r in _consulta(
            engine,
            "SELECT conname FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace "
            "WHERE n.nspname IN ('catalogo', 'vendas')",
        )
    }
    assert nomes == {
        "pk_veiculos",
        "ck_veiculos_status",
        "ck_veiculos_preco_positivo",
        "ck_veiculos_ano_faixa",
        "ck_veiculos_textos_nao_vazios",
        "ck_veiculos_versao",
        "pk_vendas",
        "uq_vendas_codigo_pagamento",
        "ck_vendas_status",
        "ck_vendas_motivo",
        "ck_vendas_preco_positivo",
        "ck_vendas_codigo_formato",
        "ck_vendas_expiracao",
        "ck_vendas_efetivada_coerente",
        "ck_vendas_cancelada_coerente",
    }


def test_indices_incluem_o_unico_parcial_de_venda_ativa(engine: Engine) -> None:
    indices = dict(
        _consulta(
            engine,
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname IN ('catalogo','vendas')",
        )
    )
    assert set(indices) == {
        "pk_veiculos",
        "ix_veiculos_status_preco",
        "pk_vendas",
        "uq_vendas_codigo_pagamento",
        "ux_vendas_veiculo_ativa",
        "ix_vendas_comprador_criada",
        "ix_vendas_status_criada",
        "ix_vendas_veiculo",
        "ix_vendas_expiracao_pendente",
    }
    parcial = indices["ux_vendas_veiculo_ativa"]
    assert "UNIQUE" in parcial
    assert "AGUARDANDO_PAGAMENTO" in parcial
    assert "EFETIVADA" in parcial
    assert "WHERE" in indices["ix_vendas_expiracao_pendente"]


def test_sem_chave_estrangeira_entre_schemas(engine: Engine) -> None:
    """R4: vendas.veiculo_id é referência lógica; nenhuma FK cruza a fronteira dos módulos."""
    fks = _consulta(
        engine,
        "SELECT conname FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace "
        "WHERE c.contype = 'f' AND n.nspname IN ('catalogo', 'vendas')",
    )
    assert fks == []


def test_dinheiro_e_numeric_12_2(engine: Engine) -> None:
    colunas = _consulta(
        engine,
        "SELECT table_schema || '.' || column_name, numeric_precision, numeric_scale "
        "FROM information_schema.columns WHERE data_type = 'numeric' "
        "AND table_schema IN ('catalogo', 'vendas') ORDER BY 1",
    )
    assert colunas == [("catalogo.preco", 12, 2), ("vendas.preco_venda", 12, 2)]


_PADRAO_DADO_PESSOAL = re.compile(
    r"nome|name|email|e_mail|cpf|telefone|phone|celular|endereco|address|nascimento|birth"
    r"|sexo|genero|documento|cnh",
    re.IGNORECASE,
)


def test_schema_sem_dados_pessoais(engine: Engine) -> None:
    """RN-11 / LGPD art. 6º, III: o banco da API não tem colunas de dados pessoais.

    O comprador aparece só como `comprador_id` (claim `sub`, pseudônimo).
    """
    colunas = _consulta(
        engine,
        "SELECT table_schema, table_name, column_name FROM information_schema.columns "
        "WHERE table_schema IN ('catalogo', 'vendas', 'public') ORDER BY 1, 2, 3",
    )
    suspeitas = [c for c in colunas if _PADRAO_DADO_PESSOAL.search(c[2])]
    assert suspeitas == []
    pessoas = [c for c in colunas if "comprador" in c[2]]
    assert pessoas == [("vendas", "vendas", "comprador_id")]


def test_modelos_orm_coincidem_com_a_migracao(engine: Engine) -> None:
    """Equivalente a `alembic check`: o autogenerate não encontraria nada a migrar."""
    with engine.connect() as conexao:
        contexto = MigrationContext.configure(
            conexao,
            opts={
                "include_schemas": True,
                "include_name": lambda nome, tipo, _p: (
                    tipo != "schema" or nome in ("catalogo", "vendas")
                ),
                "compare_type": True,
            },
        )
        diferencas = compare_metadata(contexto, [metadata_catalogo, metadata_vendas])
    assert diferencas == []


def test_downgrade_e_upgrade_do_zero(engine: Engine) -> None:
    with engine.begin() as conexao:
        command.downgrade(config_alembic(conexao), "base")
    assert inspect(engine).get_table_names(schema="public") == ["alembic_version"]
    assert "vendas" not in inspect(engine).get_schema_names()
    recriar_schemas(engine)
    assert inspect(engine).get_table_names(schema="vendas") == ["vendas"]
