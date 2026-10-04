"""Agregado Venda: criação, efetivação idempotente, cancelamento e expiração (relógio fixo)."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from revenda.vendas.domain.erros import ReservaExpiradaError, TransicaoVendaInvalidaError
from revenda.vendas.domain.venda import (
    CodigoPagamento,
    DescricaoVeiculo,
    MotivoCancelamento,
    StatusVenda,
    Venda,
)

AS_10H = datetime(2026, 10, 3, 10, 0, tzinfo=UTC)
TTL = timedelta(minutes=30)


def nova_venda(**kwargs: object) -> Venda:
    dados: dict[str, object] = {
        "veiculo_id": uuid.uuid4(),
        "comprador_id": "8d2f6b1c-3e4a-4f5b-9c7d-1a2b3c4d5e6f",
        "preco_venda": Decimal("72000.00"),
        "veiculo": DescricaoVeiculo("Fiat", "Argo", 2022, "Prata"),
        "agora": AS_10H,
        "ttl": TTL,
    }
    dados.update(kwargs)
    return Venda.iniciar(**dados)  # type: ignore[arg-type]


def test_venda_nasce_aguardando_pagamento_com_codigo_e_prazo() -> None:
    venda = nova_venda()
    assert venda.status is StatusVenda.AGUARDANDO_PAGAMENTO
    assert re.fullmatch(r"PAG-[0-9a-f]{12}", str(venda.codigo_pagamento))
    assert venda.expira_em == AS_10H + TTL
    assert venda.efetivada_em is None
    assert venda.cancelada_em is None
    assert venda.motivo_cancelamento is None
    assert [e.nome for e in venda.coletar_eventos()] == ["CompraIniciada"]


def test_codigos_de_pagamento_sao_aleatorios_e_validados() -> None:
    codigos = {CodigoPagamento.gerar().valor for _ in range(200)}
    assert len(codigos) == 200
    with pytest.raises(ValueError, match="formato"):
        CodigoPagamento("PAG-XYZ")


@pytest.mark.parametrize(
    "kwargs",
    [{"comprador_id": " "}, {"preco_venda": Decimal("0")}, {"ttl": timedelta(0)}],
)
def test_iniciar_rejeita_dados_impossiveis(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        nova_venda(**kwargs)


def test_efetivar_dentro_do_prazo_e_idempotente() -> None:
    venda = nova_venda()
    venda.coletar_eventos()
    instante = AS_10H + timedelta(minutes=29, seconds=59)
    assert venda.efetivar(instante) is True
    assert venda.status is StatusVenda.EFETIVADA
    assert venda.efetivada_em == instante
    assert [e.nome for e in venda.coletar_eventos()] == ["PagamentoAprovado", "VendaEfetivada"]
    assert venda.efetivar(instante + timedelta(hours=1)) is False
    assert venda.efetivada_em == instante
    assert venda.coletar_eventos() == []


def test_bdd_08_efetivar_apos_expiracao_e_negado() -> None:
    """BDD-08 (unidade): no instante exato de expira_em a reserva já venceu."""
    venda = nova_venda()
    assert not venda.esta_expirada(AS_10H + TTL - timedelta(microseconds=1))
    assert venda.esta_expirada(AS_10H + TTL)
    with pytest.raises(ReservaExpiradaError):
        venda.efetivar(AS_10H + TTL)
    assert venda.status is StatusVenda.AGUARDANDO_PAGAMENTO


@pytest.mark.parametrize(
    ("motivo", "especializado"),
    [
        (MotivoCancelamento.PAGAMENTO_RECUSADO, "PagamentoRecusado"),
        (MotivoCancelamento.DESISTENCIA_COMPRADOR, "CompraCanceladaPeloComprador"),
        (MotivoCancelamento.RESERVA_EXPIRADA, "ReservaExpirada"),
        (MotivoCancelamento.CANCELADA_PELA_LOJA, None),
    ],
)
def test_cancelar_registra_motivo_e_eventos(
    motivo: MotivoCancelamento, especializado: str | None
) -> None:
    venda = nova_venda()
    venda.coletar_eventos()
    venda.cancelar(motivo, AS_10H)
    assert venda.status is StatusVenda.CANCELADA
    assert venda.motivo_cancelamento is motivo
    assert venda.cancelada_em == AS_10H
    eventos = venda.coletar_eventos()
    esperados = [especializado, "VendaCancelada"] if especializado else ["VendaCancelada"]
    assert [e.nome for e in eventos] == esperados
    assert eventos[-1].como_dict()["motivo"] == motivo.value


def test_estados_finais_nao_admitem_transicao() -> None:
    efetivada = nova_venda()
    efetivada.efetivar(AS_10H)
    with pytest.raises(TransicaoVendaInvalidaError):
        efetivada.cancelar(MotivoCancelamento.DESISTENCIA_COMPRADOR, AS_10H)

    cancelada = nova_venda()
    cancelada.cancelar(MotivoCancelamento.PAGAMENTO_RECUSADO, AS_10H)
    with pytest.raises(TransicaoVendaInvalidaError):
        cancelada.efetivar(AS_10H)
    with pytest.raises(TransicaoVendaInvalidaError):
        cancelada.cancelar(MotivoCancelamento.PAGAMENTO_RECUSADO, AS_10H)
    assert not cancelada.esta_expirada(AS_10H + timedelta(days=1))


def test_expirar_so_vale_para_reserva_vencida() -> None:
    venda = nova_venda()
    with pytest.raises(TransicaoVendaInvalidaError):
        venda.expirar(AS_10H)
    venda.expirar(AS_10H + TTL)
    assert venda.motivo_cancelamento is MotivoCancelamento.RESERVA_EXPIRADA


def test_status_ativa_e_dono() -> None:
    venda = nova_venda(comprador_id="abc")
    assert venda.pertence_a("abc")
    assert not venda.pertence_a("outro")
    assert StatusVenda.AGUARDANDO_PAGAMENTO.ativa
    assert StatusVenda.EFETIVADA.ativa
    assert not StatusVenda.CANCELADA.ativa
