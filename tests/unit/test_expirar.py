"""Laço de saneamento das reservas vencidas (src/revenda/expirar.py), sem banco.

Cenário em memória com relógio fixo: várias reservas vencidas, lotes pequenos e um teto,
para verificar que o laço para quando não há mais nada a cancelar ou ao atingir o teto.
"""

from __future__ import annotations

import json
import logging

import pytest

from apoio.cenario import CLIENTE_A, TTL, Cenario, novo_cenario
from revenda.catalogo.domain.veiculo import StatusVeiculo
from revenda.expirar import TETO_PADRAO, Resultado, SaneamentoSettings, executar
from revenda.shared.logging import FormatadorJson
from revenda.vendas.domain.venda import MotivoCancelamento, StatusVenda


def _cenario_com_vencidas(quantidade: int) -> Cenario:
    cenario = novo_cenario()
    for _ in range(quantidade):
        veiculo = cenario.veiculo()
        cenario.iniciar_compra().executar(veiculo.id, CLIENTE_A)
    cenario.relogio.avancar(TTL)  # agora == expira_em: todas vencidas
    return cenario


def test_cancela_tudo_em_lotes_e_para_quando_nao_sobra_nada(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cenario = _cenario_com_vencidas(5)
    with caplog.at_level(logging.INFO, logger="revenda.expirar"):
        resultado = executar(cenario.expirar(), lote=2, teto=TETO_PADRAO)
    assert resultado == Resultado(canceladas=5, lotes=3, teto_atingido=False)
    assert all(v.status is StatusVenda.CANCELADA for v in cenario.vendas.dados.values())
    assert all(
        v.motivo_cancelamento is MotivoCancelamento.RESERVA_EXPIRADA
        for v in cenario.vendas.dados.values()
    )
    assert all(v.status is StatusVeiculo.A_VENDA for v in cenario.veiculos.dados.values())
    # Cada lote é uma transação própria (3 lotes com cancelamentos); a 4ª chamada devolve 0
    # sem confirmar nada. As 5 compras iniciais também confirmaram uma vez cada.
    assert cenario.uow.confirmacoes == 5 + 3
    assert cenario.uow.nomes_publicados.count("ReservaExpirada") == 5
    final = next(r for r in caplog.records if "concluído" in r.getMessage())
    assert final.levelno == logging.INFO
    registro = json.loads(FormatadorJson().format(final))
    assert registro["canceladas"] == 5
    assert registro["lotes"] == 3
    assert registro["teto_atingido"] is False
    assert registro["logger"] == "revenda.expirar"


def test_teto_limita_a_execucao_e_deixa_o_resto_para_a_proxima(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cenario = _cenario_com_vencidas(5)
    with caplog.at_level(logging.INFO, logger="revenda.expirar"):
        resultado = executar(cenario.expirar(), lote=2, teto=3)
    # 2 no primeiro lote e só 1 no segundo: o último lote é reduzido para não passar do teto.
    assert resultado == Resultado(canceladas=3, lotes=2, teto_atingido=True)
    ativas = [v for v in cenario.vendas.dados.values() if v.status.ativa]
    assert len(ativas) == 2
    final = next(r for r in caplog.records if "concluído" in r.getMessage())
    assert final.levelno == logging.WARNING  # sobras possíveis: chama a atenção no log
    # A execução seguinte termina o serviço.
    assert executar(cenario.expirar(), lote=2, teto=3) == Resultado(2, 1, False)
    assert not [v for v in cenario.vendas.dados.values() if v.status.ativa]


def test_sem_reservas_vencidas_nao_escreve_nada() -> None:
    cenario = novo_cenario()
    veiculo = cenario.veiculo()
    cenario.iniciar_compra().executar(veiculo.id, CLIENTE_A)
    cenario.relogio.avancar(TTL - TTL / 2)  # ainda dentro do TTL
    confirmacoes = cenario.uow.confirmacoes
    assert executar(cenario.expirar(), lote=100, teto=TETO_PADRAO) == Resultado(0, 0, False)
    assert cenario.uow.confirmacoes == confirmacoes
    assert cenario.vendas.dados[next(iter(cenario.vendas.dados))].status.ativa


class _ExpiradorContador:
    """Devolve sempre o limite pedido: simula um banco com reservas vencidas sem fim."""

    def __init__(self) -> None:
        self.limites: list[int] = []

    def expirar_vencidas(self, limite: int) -> int:
        self.limites.append(limite)
        return limite


def test_laco_nunca_pede_mais_do_que_falta_para_o_teto() -> None:
    expirador = _ExpiradorContador()
    assert executar(expirador, lote=100, teto=250) == Resultado(250, 3, True)
    assert expirador.limites == [100, 100, 50]


@pytest.mark.parametrize(("lote", "teto"), [(0, 10), (10, 0), (-1, 1)])
def test_parametros_invalidos_sao_recusados(lote: int, teto: int) -> None:
    with pytest.raises(ValueError, match="positivos"):
        executar(_ExpiradorContador(), lote=lote, teto=teto)


def test_configuracao_vem_do_ambiente_com_padroes(monkeypatch: pytest.MonkeyPatch) -> None:
    for nome in ("SANEAMENTO_LOTE", "SANEAMENTO_TETO", "LOG_LEVEL"):
        monkeypatch.delenv(nome, raising=False)
    padrao = SaneamentoSettings()
    assert (padrao.saneamento_lote, padrao.saneamento_teto) == (100, TETO_PADRAO)
    monkeypatch.setenv("SANEAMENTO_LOTE", "25")
    monkeypatch.setenv("SANEAMENTO_TETO", "40")
    ajustado = SaneamentoSettings()
    assert (ajustado.saneamento_lote, ajustado.saneamento_teto) == (25, 40)
