"""Saneamento das reservas vencidas (python -m revenda.expirar) contra PostgreSQL real.

As vendas são criadas pela API com o relógio fixo de 2026-10-03 (apoio/cenario.py); o
comando usa o relógio do sistema, então essas reservas já venceram para ele. Uma reserva
"viva" é criada com o relógio fixo ajustado para o instante atual, para provar que o
saneamento não a toca.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, text

from apoio.api import Api
from apoio.banco import RAIZ_PROJETO
from revenda import expirar
from revenda.shared.clock import RelogioFixo
from revenda.shared.db import BancoDeDados


@pytest.fixture
def logging_preservado() -> Iterator[None]:
    """main() reconfigura o logger raiz (JSON em stdout); devolve o logging como estava."""
    raiz = logging.getLogger()
    handlers, nivel = list(raiz.handlers), raiz.level
    yield
    raiz.handlers[:] = handlers
    raiz.setLevel(nivel)


def _status(engine: Engine) -> dict[str, tuple[str, str | None]]:
    """veiculo_id -> (status do veículo, motivo de cancelamento da venda)."""
    with engine.connect() as conexao:
        linhas = conexao.execute(
            text(
                "SELECT v.id::text, v.status, s.motivo_cancelamento "
                "FROM catalogo.veiculos v JOIN vendas.vendas s ON s.veiculo_id = v.id"
            )
        ).all()
    return {linha[0]: (linha[1], linha[2]) for linha in linhas}


def _reservas(api: Api, relogio: RelogioFixo) -> tuple[list[str], str]:
    """Três reservas vencidas (relógio de 2026) e uma viva (relógio = agora)."""
    cliente = api.novo_cliente()
    vencidos = [api.compra_ok(api.cadastrar()["id"], cliente)["veiculo_id"] for _ in range(3)]
    relogio.definir(datetime.now(UTC))
    vivo = api.compra_ok(api.cadastrar(modelo="Pulse")["id"], cliente)["veiculo_id"]
    return vencidos, vivo


def test_executar_cancela_as_vencidas_e_libera_os_veiculos(
    api: Api, relogio: RelogioFixo, banco: BancoDeDados, engine: Engine
) -> None:
    vencidos, vivo = _reservas(api, relogio)
    expirador, sessao = expirar.expirador_sql(banco)
    try:
        resultado = expirar.executar(expirador, lote=2, teto=expirar.TETO_PADRAO)
    finally:
        sessao.close()
    assert resultado == expirar.Resultado(canceladas=3, lotes=2, teto_atingido=False)
    status = _status(engine)
    assert all(status[v] == ("A_VENDA", "RESERVA_EXPIRADA") for v in vencidos)
    assert status[vivo] == ("RESERVADO", None)
    # Repetir não cancela de novo (idempotente).
    expirador, sessao = expirar.expirador_sql(banco)
    try:
        assert expirar.executar(expirador, lote=2, teto=10).canceladas == 0
    finally:
        sessao.close()


def test_teto_deixa_sobras_para_a_proxima_execucao(
    api: Api, relogio: RelogioFixo, banco: BancoDeDados, engine: Engine
) -> None:
    vencidos, _ = _reservas(api, relogio)
    expirador, sessao = expirar.expirador_sql(banco)
    try:
        resultado = expirar.executar(expirador, lote=10, teto=2)
    finally:
        sessao.close()
    assert resultado == expirar.Resultado(canceladas=2, lotes=1, teto_atingido=True)
    status = _status(engine)
    assert sorted(status[v][0] for v in vencidos) == ["A_VENDA", "A_VENDA", "RESERVADO"]


@pytest.mark.usefixtures("logging_preservado")
def test_main_le_o_ambiente_e_sai_com_zero(
    api: Api, relogio: RelogioFixo, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    vencidos, vivo = _reservas(api, relogio)
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("SANEAMENTO_LOTE", "2")
    monkeypatch.setenv("SANEAMENTO_TETO", "50")
    assert expirar.main() == 0
    status = _status(engine)
    assert all(status[v] == ("A_VENDA", "RESERVA_EXPIRADA") for v in vencidos)
    assert status[vivo] == ("RESERVADO", None)


def test_comando_python_m_revenda_expirar(api: Api, relogio: RelogioFixo, engine: Engine) -> None:
    """O ponto de entrada do CronJob: processo separado, log JSON em stdout, saída 0."""
    vencidos, _ = _reservas(api, relogio)
    ambiente = {chave: valor for chave, valor in os.environ.items() if not chave.startswith("DB_")}
    ambiente["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    processo = subprocess.run(  # argumentos fixos, sem shell
        [sys.executable, "-m", "revenda.expirar"],
        cwd=RAIZ_PROJETO,
        env=ambiente,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert processo.returncode == 0, processo.stderr
    registros = [json.loads(linha) for linha in processo.stdout.splitlines() if linha]
    final = next(r for r in registros if r["mensagem"].startswith("saneamento"))
    assert final["logger"] == "revenda.expirar"
    assert (final["canceladas"], final["teto_atingido"]) == (3, False)
    assert all(_status(engine)[v][0] == "A_VENDA" for v in vencidos)
