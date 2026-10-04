"""ProcessarPagamento: efetivação, recusa, idempotência (RN-08) e expiração (RN-14)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from apoio.cenario import CLIENTE_A, Cenario
from revenda.catalogo.domain.veiculo import StatusVeiculo
from revenda.vendas.domain.erros import (
    InconsistenciaCatalogoError,
    PagamentoNaoEncontradoError,
    ReservaExpiradaError,
    TransicaoVendaInvalidaError,
)
from revenda.vendas.domain.venda import MotivoCancelamento, StatusVenda, Venda


def compra(cenario: Cenario) -> Venda:
    veiculo = cenario.veiculo()
    return cenario.iniciar_compra().executar(veiculo.id, CLIENTE_A)


def test_bdd_01_aprovado_efetiva_venda_e_vende_veiculo(cenario: Cenario) -> None:
    venda = compra(cenario)
    cenario.relogio.avancar(timedelta(minutes=2))
    efetivada = cenario.processar_pagamento().executar(str(venda.codigo_pagamento), aprovado=True)
    assert efetivada.status is StatusVenda.EFETIVADA
    assert efetivada.efetivada_em == cenario.relogio.agora()
    assert cenario.status_veiculo(venda.veiculo_id) is StatusVeiculo.VENDIDO
    assert cenario.uow.nomes_publicados[-3:] == [
        "VeiculoVendido",
        "PagamentoAprovado",
        "VendaEfetivada",
    ]


def test_bdd_01_aprovado_repetido_nao_tem_efeito(cenario: Cenario) -> None:
    venda = compra(cenario)
    codigo = str(venda.codigo_pagamento)
    primeira = cenario.processar_pagamento().executar(codigo, aprovado=True)
    confirmacoes = cenario.uow.confirmacoes
    cenario.relogio.avancar(timedelta(hours=2))
    segunda = cenario.processar_pagamento().executar(codigo, aprovado=True)
    assert segunda.status is StatusVenda.EFETIVADA
    assert segunda.efetivada_em == primeira.efetivada_em
    assert cenario.uow.confirmacoes == confirmacoes


def test_bdd_02_recusado_cancela_e_libera(cenario: Cenario) -> None:
    venda = compra(cenario)
    cancelada = cenario.processar_pagamento().executar(str(venda.codigo_pagamento), aprovado=False)
    assert cancelada.status is StatusVenda.CANCELADA
    assert cancelada.motivo_cancelamento is MotivoCancelamento.PAGAMENTO_RECUSADO
    assert cenario.status_veiculo(venda.veiculo_id) is StatusVeiculo.A_VENDA


def test_recusado_repetido_nao_tem_efeito(cenario: Cenario) -> None:
    venda = compra(cenario)
    codigo = str(venda.codigo_pagamento)
    cenario.processar_pagamento().executar(codigo, aprovado=False)
    confirmacoes = cenario.uow.confirmacoes
    repetida = cenario.processar_pagamento().executar(codigo, aprovado=False)
    assert repetida.motivo_cancelamento is MotivoCancelamento.PAGAMENTO_RECUSADO
    assert cenario.uow.confirmacoes == confirmacoes


def test_aprovado_para_venda_cancelada_e_conflito(cenario: Cenario) -> None:
    venda = compra(cenario)
    codigo = str(venda.codigo_pagamento)
    cenario.processar_pagamento().executar(codigo, aprovado=False)
    with pytest.raises(TransicaoVendaInvalidaError):
        cenario.processar_pagamento().executar(codigo, aprovado=True)


def test_recusado_para_venda_efetivada_e_conflito(cenario: Cenario) -> None:
    venda = compra(cenario)
    codigo = str(venda.codigo_pagamento)
    cenario.processar_pagamento().executar(codigo, aprovado=True)
    with pytest.raises(TransicaoVendaInvalidaError):
        cenario.processar_pagamento().executar(codigo, aprovado=False)
    assert cenario.status_veiculo(venda.veiculo_id) is StatusVeiculo.VENDIDO


def test_bdd_08_aprovado_apos_expiracao_cancela_confirma_e_responde_conflito(
    cenario: Cenario,
) -> None:
    venda = compra(cenario)
    cenario.relogio.avancar(timedelta(minutes=31))
    confirmacoes = cenario.uow.confirmacoes
    with pytest.raises(ReservaExpiradaError):
        cenario.processar_pagamento().executar(str(venda.codigo_pagamento), aprovado=True)
    # O cancelamento foi confirmado antes do erro (RN-14).
    assert cenario.uow.confirmacoes == confirmacoes + 1
    armazenada = cenario.vendas.dados[venda.id]
    assert armazenada.motivo_cancelamento is MotivoCancelamento.RESERVA_EXPIRADA
    assert cenario.status_veiculo(venda.veiculo_id) is StatusVeiculo.A_VENDA


def test_recusado_apos_expiracao_cancela_por_expiracao(cenario: Cenario) -> None:
    venda = compra(cenario)
    cenario.relogio.avancar(timedelta(minutes=45))
    cancelada = cenario.processar_pagamento().executar(str(venda.codigo_pagamento), aprovado=False)
    assert cancelada.motivo_cancelamento is MotivoCancelamento.RESERVA_EXPIRADA
    assert cenario.status_veiculo(venda.veiculo_id) is StatusVeiculo.A_VENDA


def test_codigo_desconhecido(cenario: Cenario) -> None:
    with pytest.raises(PagamentoNaoEncontradoError):
        cenario.processar_pagamento().executar("PAG-000000000000", aprovado=True)


@pytest.mark.parametrize("aprovado", [True, False])
def test_inconsistencia_no_catalogo_nao_e_silenciosa(cenario: Cenario, aprovado: bool) -> None:
    venda = compra(cenario)
    cenario.veiculos.dados[venda.veiculo_id].status = StatusVeiculo.A_VENDA
    confirmacoes = cenario.uow.confirmacoes
    with pytest.raises(InconsistenciaCatalogoError):
        cenario.processar_pagamento().executar(str(venda.codigo_pagamento), aprovado=aprovado)
    assert cenario.uow.confirmacoes == confirmacoes


def test_expirar_vencidas_em_lote(cenario: Cenario) -> None:
    vendas = [compra(cenario) for _ in range(3)]
    expirar = cenario.expirar()
    assert expirar.expirar_vencidas(100) == 0
    cenario.relogio.avancar(timedelta(minutes=30))
    assert expirar.expirar_vencidas(2) == 2
    assert expirar.expirar_vencidas(100) == 1
    for venda in vendas:
        assert cenario.status_veiculo(venda.veiculo_id) is StatusVeiculo.A_VENDA
        assert cenario.vendas.dados[venda.id].status is StatusVenda.CANCELADA


def test_expirar_tolera_veiculo_ja_liberado(cenario: Cenario) -> None:
    venda = compra(cenario)
    cenario.veiculos.dados[venda.veiculo_id].status = StatusVeiculo.A_VENDA
    cenario.relogio.avancar(timedelta(hours=1))
    assert cenario.expirar().expirar_vencidas(100) == 1
    assert cenario.vendas.dados[venda.id].status is StatusVenda.CANCELADA
