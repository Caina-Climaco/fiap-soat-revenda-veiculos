"""CancelarVenda, ObterVenda e ListarVendas: motivos (R5), RN-10 e visibilidade (RN-13)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from apoio.cenario import CLIENTE_A, CLIENTE_B, GESTOR, Cenario
from revenda.catalogo.domain.veiculo import StatusVeiculo
from revenda.vendas.domain.erros import TransicaoVendaInvalidaError, VendaNaoEncontradaError
from revenda.vendas.domain.venda import MotivoCancelamento, StatusVenda


def test_dono_desiste(cenario: Cenario) -> None:
    veiculo = cenario.veiculo()
    venda = cenario.iniciar_compra().executar(veiculo.id, CLIENTE_A)
    cancelada = cenario.cancelar().executar(venda.id, CLIENTE_A)
    assert cancelada.motivo_cancelamento is MotivoCancelamento.DESISTENCIA_COMPRADOR
    assert cenario.status_veiculo(veiculo.id) is StatusVeiculo.A_VENDA
    assert "CompraCanceladaPeloComprador" in cenario.uow.nomes_publicados


def test_gestor_cancela_pela_loja(cenario: Cenario) -> None:
    veiculo = cenario.veiculo()
    venda = cenario.iniciar_compra().executar(veiculo.id, CLIENTE_A)
    cancelada = cenario.cancelar().executar(venda.id, GESTOR)
    assert cancelada.motivo_cancelamento is MotivoCancelamento.CANCELADA_PELA_LOJA


def test_cancelamento_de_reserva_vencida_registra_expiracao(cenario: Cenario) -> None:
    veiculo = cenario.veiculo()
    venda = cenario.iniciar_compra().executar(veiculo.id, CLIENTE_A)
    cenario.relogio.avancar(timedelta(minutes=30))
    cancelada = cenario.cancelar().executar(venda.id, CLIENTE_A)
    assert cancelada.motivo_cancelamento is MotivoCancelamento.RESERVA_EXPIRADA


def test_nao_dono_recebe_nao_encontrada(cenario: Cenario) -> None:
    veiculo = cenario.veiculo()
    venda = cenario.iniciar_compra().executar(veiculo.id, CLIENTE_A)
    with pytest.raises(VendaNaoEncontradaError):
        cenario.cancelar().executar(venda.id, CLIENTE_B)
    with pytest.raises(VendaNaoEncontradaError):
        cenario.obter().executar(venda.id, CLIENTE_B)
    with pytest.raises(VendaNaoEncontradaError):
        cenario.cancelar().executar(uuid.uuid4(), GESTOR)
    assert cenario.obter().executar(venda.id, CLIENTE_A).id == venda.id
    assert cenario.obter().executar(venda.id, GESTOR).id == venda.id


def test_cancelar_venda_efetivada_e_conflito(cenario: Cenario) -> None:
    veiculo = cenario.veiculo()
    venda = cenario.iniciar_compra().executar(veiculo.id, CLIENTE_A)
    cenario.processar_pagamento().executar(str(venda.codigo_pagamento), aprovado=True)
    with pytest.raises(TransicaoVendaInvalidaError):
        cenario.cancelar().executar(venda.id, CLIENTE_A)


def test_listagens(cenario: Cenario) -> None:
    v1, v2, v3 = (cenario.veiculo() for _ in range(3))
    a1 = cenario.iniciar_compra().executar(v1.id, CLIENTE_A)
    cenario.relogio.avancar(timedelta(minutes=1))
    a2 = cenario.iniciar_compra().executar(v2.id, CLIENTE_A)
    cenario.iniciar_compra().executar(v3.id, CLIENTE_B)
    cenario.cancelar().executar(a1.id, CLIENTE_A)

    minhas = cenario.listar().do_comprador("cliente-a", limite=20, deslocamento=0)
    assert [v.id for v in minhas.itens] == [a2.id, a1.id]
    assert minhas.total == 2
    canceladas = cenario.listar().todas(status=StatusVenda.CANCELADA, limite=20, deslocamento=0)
    assert [v.id for v in canceladas.itens] == [a1.id]
    assert cenario.listar().todas(status=None, limite=1, deslocamento=0).total == 3
