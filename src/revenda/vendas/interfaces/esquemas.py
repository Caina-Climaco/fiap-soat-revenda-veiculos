"""Esquemas HTTP de Vendas (docs/05-api.md, seções 3.2, 4.8 a 4.13)."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from revenda.shared.http import DataHoraUtc, Dinheiro, ModeloRequisicao, ModeloResposta
from revenda.vendas.domain.venda import (
    PADRAO_CODIGO_PAGAMENTO,
    MotivoCancelamento,
    StatusVenda,
    Venda,
)


class CompraRequisicao(ModeloRequisicao):
    """Só o veículo: o comprador vem do token (`sub`), nunca do corpo."""

    veiculo_id: UUID


class VeiculoDaVenda(ModeloResposta):
    marca: str
    modelo: str
    ano: int
    cor: str


class VendaResposta(ModeloResposta):
    id: UUID
    veiculo_id: UUID
    veiculo: VeiculoDaVenda = Field(description="Snapshot do veículo no momento da compra.")
    preco_venda: Dinheiro = Field(description="Preço congelado no início da compra.")
    status: StatusVenda
    codigo_pagamento: str = Field(examples=["PAG-3f9a1c0b7e21"])
    expira_em: DataHoraUtc
    criada_em: DataHoraUtc
    efetivada_em: DataHoraUtc | None
    cancelada_em: DataHoraUtc | None
    motivo_cancelamento: MotivoCancelamento | None


class VendaGestorResposta(VendaResposta):
    """Visão do gestor: inclui o pseudônimo do comprador (claim `sub`)."""

    comprador_id: str


class PaginaVendas(ModeloResposta):
    itens: list[VendaGestorResposta | VendaResposta]
    total: int
    limite: int
    deslocamento: int


class NotificacaoPagamento(ModeloRequisicao):
    """Payload do gateway: vocabulário externo, traduzido pela ACL do webhook."""

    codigo_pagamento: Annotated[
        str, Field(pattern=PADRAO_CODIGO_PAGAMENTO, examples=["PAG-3f9a1c0b7e21"])
    ]
    status: Literal["APROVADO", "RECUSADO"]


def para_resposta(venda: Venda, *, visao_gestor: bool) -> VendaResposta:
    campos: dict[str, object] = {
        "id": venda.id,
        "veiculo_id": venda.veiculo_id,
        "veiculo": VeiculoDaVenda.model_validate(venda.veiculo),
        "preco_venda": venda.preco_venda,
        "status": venda.status,
        "codigo_pagamento": str(venda.codigo_pagamento),
        "expira_em": venda.expira_em,
        "criada_em": venda.criada_em,
        "efetivada_em": venda.efetivada_em,
        "cancelada_em": venda.cancelada_em,
        "motivo_cancelamento": venda.motivo_cancelamento,
    }
    if visao_gestor:
        return VendaGestorResposta.model_validate({**campos, "comprador_id": venda.comprador_id})
    return VendaResposta.model_validate(campos)
