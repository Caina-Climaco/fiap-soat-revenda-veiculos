"""Agregado Venda (contexto Vendas) — docs/02-modelagem-ddd.md, seção 2.5.2."""

from __future__ import annotations

import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from revenda.vendas.domain.erros import ReservaExpiradaError, TransicaoVendaInvalidaError
from revenda.vendas.domain.eventos import (
    CompraCanceladaPeloComprador,
    CompraIniciada,
    EventoVenda,
    PagamentoAprovado,
    PagamentoRecusado,
    ReservaExpirada,
    VendaCancelada,
    VendaEfetivada,
)

PADRAO_CODIGO_PAGAMENTO = r"^PAG-[0-9a-f]{12}$"
_CODIGO_PAGAMENTO = re.compile(PADRAO_CODIGO_PAGAMENTO)


class StatusVenda(StrEnum):
    AGUARDANDO_PAGAMENTO = "AGUARDANDO_PAGAMENTO"
    EFETIVADA = "EFETIVADA"
    CANCELADA = "CANCELADA"

    @property
    def ativa(self) -> bool:
        """Venda ativa ocupa o veículo (índice único parcial `ux_vendas_veiculo_ativa`)."""
        return self is not StatusVenda.CANCELADA


class MotivoCancelamento(StrEnum):
    PAGAMENTO_RECUSADO = "PAGAMENTO_RECUSADO"
    DESISTENCIA_COMPRADOR = "DESISTENCIA_COMPRADOR"
    CANCELADA_PELA_LOJA = "CANCELADA_PELA_LOJA"
    RESERVA_EXPIRADA = "RESERVA_EXPIRADA"


_EVENTO_POR_MOTIVO: dict[MotivoCancelamento, type[EventoVenda]] = {
    MotivoCancelamento.PAGAMENTO_RECUSADO: PagamentoRecusado,
    MotivoCancelamento.DESISTENCIA_COMPRADOR: CompraCanceladaPeloComprador,
    MotivoCancelamento.RESERVA_EXPIRADA: ReservaExpirada,
}


@dataclass(frozen=True, slots=True)
class CodigoPagamento:
    """`PAG-` + 12 hexadecimais aleatórios (RN-18): único e não previsível."""

    valor: str

    def __post_init__(self) -> None:
        if not _CODIGO_PAGAMENTO.match(self.valor):
            raise ValueError("Código de pagamento fora do formato PAG- + 12 hexadecimais.")

    @classmethod
    def gerar(cls) -> CodigoPagamento:
        return cls(f"PAG-{secrets.token_hex(6)}")

    def __str__(self) -> str:
        return self.valor


@dataclass(frozen=True, slots=True)
class DescricaoVeiculo:
    """Cópia de marca/modelo/ano/cor no momento da compra (RN-12)."""

    marca: str
    modelo: str
    ano: int
    cor: str


@dataclass(eq=False)
class Venda:
    id: UUID
    veiculo_id: UUID
    comprador_id: str
    preco_venda: Decimal
    veiculo: DescricaoVeiculo
    status: StatusVenda
    codigo_pagamento: CodigoPagamento
    expira_em: datetime
    criada_em: datetime
    efetivada_em: datetime | None = None
    cancelada_em: datetime | None = None
    motivo_cancelamento: MotivoCancelamento | None = None
    _eventos: list[EventoVenda] = field(default_factory=list, repr=False)

    @classmethod
    def iniciar(
        cls,
        *,
        veiculo_id: UUID,
        comprador_id: str,
        preco_venda: Decimal,
        veiculo: DescricaoVeiculo,
        agora: datetime,
        ttl: timedelta,
        codigo_pagamento: CodigoPagamento | None = None,
        id_: UUID | None = None,
    ) -> Venda:
        """Cria a venda depois que o veículo foi reservado com sucesso (preço congelado, RN-01)."""
        if not comprador_id.strip():
            raise ValueError("A venda exige o identificador do comprador.")
        if preco_venda <= 0:
            raise ValueError("O preço de venda deve ser maior que zero.")
        if ttl <= timedelta(0):
            raise ValueError("O prazo da reserva deve ser positivo.")
        venda = cls(
            id=id_ or uuid.uuid4(),
            veiculo_id=veiculo_id,
            comprador_id=comprador_id,
            preco_venda=preco_venda,
            veiculo=veiculo,
            status=StatusVenda.AGUARDANDO_PAGAMENTO,
            codigo_pagamento=codigo_pagamento or CodigoPagamento.gerar(),
            expira_em=agora + ttl,
            criada_em=agora,
        )
        venda._eventos.append(
            CompraIniciada(
                venda_id=venda.id,
                veiculo_id=veiculo_id,
                ocorrido_em=agora,
                preco_venda=str(preco_venda),
                expira_em=venda.expira_em.isoformat(),
            )
        )
        return venda

    def esta_expirada(self, agora: datetime) -> bool:
        return self.status is StatusVenda.AGUARDANDO_PAGAMENTO and agora >= self.expira_em

    def pertence_a(self, comprador_id: str) -> bool:
        return self.comprador_id == comprador_id

    def efetivar(self, agora: datetime) -> bool:
        """Confirma o pagamento. Devolve False se a venda já estava efetivada (idempotente)."""
        if self.status is StatusVenda.EFETIVADA:
            return False
        if self.status is not StatusVenda.AGUARDANDO_PAGAMENTO:
            raise TransicaoVendaInvalidaError(self.id, self.status.value, "efetivar")
        if self.esta_expirada(agora):
            raise ReservaExpiradaError(self.id)
        self.status = StatusVenda.EFETIVADA
        self.efetivada_em = agora
        self._eventos += [
            PagamentoAprovado(venda_id=self.id, veiculo_id=self.veiculo_id, ocorrido_em=agora),
            VendaEfetivada(venda_id=self.id, veiculo_id=self.veiculo_id, ocorrido_em=agora),
        ]
        return True

    def cancelar(self, motivo: MotivoCancelamento, agora: datetime) -> None:
        if self.status is not StatusVenda.AGUARDANDO_PAGAMENTO:
            raise TransicaoVendaInvalidaError(self.id, self.status.value, "cancelar")
        self.status = StatusVenda.CANCELADA
        self.cancelada_em = agora
        self.motivo_cancelamento = motivo
        # VendaCancelada é o evento genérico; os especializados existem para leitura do log (R5).
        especializado = _EVENTO_POR_MOTIVO.get(motivo)
        if especializado is not None:
            self._eventos.append(
                especializado(venda_id=self.id, veiculo_id=self.veiculo_id, ocorrido_em=agora)
            )
        self._eventos.append(
            VendaCancelada(
                venda_id=self.id, veiculo_id=self.veiculo_id, ocorrido_em=agora, motivo=motivo
            )
        )

    def expirar(self, agora: datetime) -> None:
        """Cancela por RESERVA_EXPIRADA; só faz sentido se `esta_expirada(agora)`."""
        if not self.esta_expirada(agora):
            raise TransicaoVendaInvalidaError(self.id, self.status.value, "expirar")
        self.cancelar(MotivoCancelamento.RESERVA_EXPIRADA, agora)

    def coletar_eventos(self) -> list[EventoVenda]:
        eventos, self._eventos = self._eventos, []
        return eventos
