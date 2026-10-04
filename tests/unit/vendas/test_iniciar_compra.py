"""IniciarCompra: reserva, preço congelado, RN-05, indisponibilidade e expiração preguiçosa."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from apoio.cenario import AS_10H, CLIENTE_A, CLIENTE_B, GESTOR, TTL, Cenario
from apoio.fakes import VendaRepoMemoria
from revenda.catalogo.domain.veiculo import StatusVeiculo
from revenda.vendas.domain.erros import (
    CompraNaoPermitidaError,
    VeiculoIndisponivelError,
    VeiculoNaoEncontradoError,
)
from revenda.vendas.domain.venda import CodigoPagamento, MotivoCancelamento, StatusVenda, Venda


def test_compra_reserva_veiculo_e_congela_preco(cenario: Cenario) -> None:
    veiculo = cenario.veiculo("72000.00")
    venda = cenario.iniciar_compra().executar(veiculo.id, CLIENTE_A)
    assert venda.status is StatusVenda.AGUARDANDO_PAGAMENTO
    assert venda.preco_venda == Decimal("72000.00")
    assert venda.comprador_id == "cliente-a"
    assert (venda.veiculo.marca, venda.veiculo.ano) == ("Hyundai", 2021)
    assert venda.expira_em == AS_10H + TTL
    assert cenario.status_veiculo(veiculo.id) is StatusVeiculo.RESERVADO
    assert cenario.uow.confirmacoes == 1
    assert cenario.uow.nomes_publicados == ["VeiculoReservado", "CompraIniciada"]


def test_codigo_de_pagamento_injetavel(cenario: Cenario) -> None:
    veiculo = cenario.veiculo()
    caso = cenario.iniciar_compra()
    caso._gerar_codigo = lambda: CodigoPagamento("PAG-0123456789ab")
    assert str(caso.executar(veiculo.id, CLIENTE_A).codigo_pagamento) == "PAG-0123456789ab"


def test_bdd_05_gestor_nao_compra(cenario: Cenario) -> None:
    """BDD-05 (unidade): RN-05, mesmo antes de olhar o veículo."""
    veiculo = cenario.veiculo()
    with pytest.raises(CompraNaoPermitidaError):
        cenario.iniciar_compra().executar(veiculo.id, GESTOR)
    assert cenario.status_veiculo(veiculo.id) is StatusVeiculo.A_VENDA
    assert cenario.vendas.dados == {}


def test_veiculo_inexistente(cenario: Cenario) -> None:
    with pytest.raises(VeiculoNaoEncontradoError):
        cenario.iniciar_compra().executar(uuid.uuid4(), CLIENTE_A)


def test_veiculo_reservado_com_reserva_vigente_esta_indisponivel(cenario: Cenario) -> None:
    veiculo = cenario.veiculo()
    cenario.iniciar_compra().executar(veiculo.id, CLIENTE_A)
    cenario.relogio.avancar(TTL - timedelta(seconds=1))
    with pytest.raises(VeiculoIndisponivelError) as erro:
        cenario.iniciar_compra().executar(veiculo.id, CLIENTE_B)
    assert erro.value.status == "RESERVADO"
    assert len(cenario.vendas.dados) == 1


def test_veiculo_vendido_esta_indisponivel(cenario: Cenario) -> None:
    veiculo = cenario.veiculo()
    venda = cenario.iniciar_compra().executar(veiculo.id, CLIENTE_A)
    cenario.processar_pagamento().executar(str(venda.codigo_pagamento), aprovado=True)
    cenario.relogio.avancar(timedelta(days=1))
    with pytest.raises(VeiculoIndisponivelError, match="VENDIDO"):
        cenario.iniciar_compra().executar(veiculo.id, CLIENTE_B)


def test_bdd_08_outro_cliente_compra_apos_expiracao(cenario: Cenario) -> None:
    """BDD-08 (unidade): às 10:31 a venda de A expira e B consegue comprar."""
    veiculo = cenario.veiculo()
    venda_a = cenario.iniciar_compra().executar(veiculo.id, CLIENTE_A)
    cenario.relogio.avancar(timedelta(minutes=31))
    venda_b = cenario.iniciar_compra().executar(veiculo.id, CLIENTE_B)

    a = cenario.vendas.dados[venda_a.id]
    assert a.status is StatusVenda.CANCELADA
    assert a.motivo_cancelamento is MotivoCancelamento.RESERVA_EXPIRADA
    ativas = [v for v in cenario.vendas.dados.values() if v.status.ativa]
    assert [v.id for v in ativas] == [venda_b.id]
    assert ativas[0].comprador_id == "cliente-b"
    assert cenario.status_veiculo(veiculo.id) is StatusVeiculo.RESERVADO
    assert cenario.uow.nomes_publicados[-5:] == [
        "VeiculoLiberado",
        "VeiculoReservado",
        "ReservaExpirada",
        "VendaCancelada",
        "CompraIniciada",
    ]


def test_venda_ativa_duplicada_vira_indisponivel(cenario: Cenario) -> None:
    """Segunda barreira: se a reserva for contornada, o índice único ainda impede."""
    veiculo = cenario.veiculo()
    cenario.iniciar_compra().executar(veiculo.id, CLIENTE_A)
    # Simula a reserva contornada: o veículo volta a A_VENDA sem cancelar a venda.
    cenario.veiculos.dados[veiculo.id].status = StatusVeiculo.A_VENDA

    class SemVendaAtiva(VendaRepoMemoria):
        def obter_ativa_do_veiculo(
            self, veiculo_id: uuid.UUID, *, para_atualizar: bool = False
        ) -> Venda | None:
            return None

    repo = SemVendaAtiva()
    repo.dados = cenario.vendas.dados
    cenario.vendas = repo
    with pytest.raises(VeiculoIndisponivelError):
        cenario.iniciar_compra().executar(veiculo.id, CLIENTE_B)
