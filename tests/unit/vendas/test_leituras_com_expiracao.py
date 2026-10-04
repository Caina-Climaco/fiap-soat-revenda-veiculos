"""Leituras de Vendas aplicam a expiração preguiçosa antes de consultar (ADR-009, R1).

Relógio fixo: nenhuma leitura mostra como AGUARDANDO_PAGAMENTO uma reserva já vencida.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from apoio.cenario import CLIENTE_A, GESTOR, TTL, Cenario
from revenda.catalogo.domain.veiculo import StatusVeiculo
from revenda.vendas.application.casos_uso import ListarVendas, ObterVenda
from revenda.vendas.domain.venda import MotivoCancelamento, StatusVenda


def _venda_vencida(cenario: Cenario) -> tuple[UUID, UUID]:
    veiculo = cenario.veiculo()
    venda = cenario.iniciar_compra().executar(veiculo.id, CLIENTE_A)
    cenario.relogio.avancar(TTL)  # agora == expira_em: já vencida
    return veiculo.id, venda.id


def test_obter_venda_vencida_mostra_cancelamento_por_expiracao(cenario: Cenario) -> None:
    veiculo_id, venda_id = _venda_vencida(cenario)
    venda = cenario.obter().executar(venda_id, CLIENTE_A)
    assert venda.status is StatusVenda.CANCELADA
    assert venda.motivo_cancelamento is MotivoCancelamento.RESERVA_EXPIRADA
    assert venda.cancelada_em == cenario.relogio.agora()
    assert cenario.status_veiculo(veiculo_id) is StatusVeiculo.A_VENDA
    assert "ReservaExpirada" in cenario.uow.nomes_publicados


def test_listagens_nao_mostram_reserva_vencida_como_ativa(cenario: Cenario) -> None:
    _, venda_id = _venda_vencida(cenario)
    minhas = cenario.listar().do_comprador(CLIENTE_A.id, limite=20, deslocamento=0)
    assert [(v.id, v.status) for v in minhas.itens] == [(venda_id, StatusVenda.CANCELADA)]
    aguardando = cenario.listar().todas(
        status=StatusVenda.AGUARDANDO_PAGAMENTO, limite=20, deslocamento=0
    )
    assert aguardando.total == 0


def test_lista_do_gestor_tambem_expira(cenario: Cenario) -> None:
    _, venda_id = _venda_vencida(cenario)
    todas = cenario.listar().todas(status=None, limite=20, deslocamento=0)
    assert todas.itens[0].motivo_cancelamento is MotivoCancelamento.RESERVA_EXPIRADA
    assert cenario.obter().executar(venda_id, GESTOR).status is StatusVenda.CANCELADA


def test_reserva_ainda_valida_nao_e_tocada(cenario: Cenario) -> None:
    veiculo = cenario.veiculo()
    venda = cenario.iniciar_compra().executar(veiculo.id, CLIENTE_A)
    cenario.relogio.avancar(TTL - timedelta(seconds=1))
    confirmacoes = cenario.uow.confirmacoes
    assert cenario.obter().executar(venda.id, CLIENTE_A).status is StatusVenda.AGUARDANDO_PAGAMENTO
    assert cenario.listar().do_comprador(CLIENTE_A.id, limite=20, deslocamento=0).total == 1
    assert cenario.uow.confirmacoes == confirmacoes  # nada a expirar: nenhuma escrita


def test_sem_expirador_a_leitura_e_pura(cenario: Cenario) -> None:
    _, venda_id = _venda_vencida(cenario)
    venda = ObterVenda(cenario.vendas).executar(venda_id, CLIENTE_A)
    assert venda.status is StatusVenda.AGUARDANDO_PAGAMENTO
    pagina = ListarVendas(cenario.vendas).todas(status=None, limite=20, deslocamento=0)
    assert pagina.itens[0].status is StatusVenda.AGUARDANDO_PAGAMENTO
