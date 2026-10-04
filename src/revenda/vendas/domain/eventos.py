"""Eventos de domínio de Vendas (docs/02-modelagem-ddd.md, seção 2.2.1).

Nenhum evento carrega dados pessoais; o comprador aparece só pelo pseudônimo nos logs
de acesso, não aqui.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar
from uuid import UUID


@dataclass(frozen=True, slots=True)
class EventoVenda:
    NOME: ClassVar[str] = "EventoVenda"

    venda_id: UUID
    veiculo_id: UUID
    ocorrido_em: datetime

    @property
    def nome(self) -> str:
        return self.NOME

    def como_dict(self) -> dict[str, str]:
        return {
            "venda_id": str(self.venda_id),
            "veiculo_id": str(self.veiculo_id),
            "ocorrido_em": self.ocorrido_em.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class CompraIniciada(EventoVenda):
    NOME: ClassVar[str] = "CompraIniciada"

    preco_venda: str = ""
    expira_em: str = ""

    def como_dict(self) -> dict[str, str]:
        return {
            **EventoVenda.como_dict(self),
            "preco_venda": self.preco_venda,
            "expira_em": self.expira_em,
        }


@dataclass(frozen=True, slots=True)
class PagamentoAprovado(EventoVenda):
    NOME: ClassVar[str] = "PagamentoAprovado"


@dataclass(frozen=True, slots=True)
class VendaEfetivada(EventoVenda):
    NOME: ClassVar[str] = "VendaEfetivada"


@dataclass(frozen=True, slots=True)
class VendaCancelada(EventoVenda):
    NOME: ClassVar[str] = "VendaCancelada"

    motivo: str = ""

    def como_dict(self) -> dict[str, str]:
        return {**EventoVenda.como_dict(self), "motivo": self.motivo}


@dataclass(frozen=True, slots=True)
class PagamentoRecusado(EventoVenda):
    NOME: ClassVar[str] = "PagamentoRecusado"


@dataclass(frozen=True, slots=True)
class CompraCanceladaPeloComprador(EventoVenda):
    NOME: ClassVar[str] = "CompraCanceladaPeloComprador"


@dataclass(frozen=True, slots=True)
class ReservaExpirada(EventoVenda):
    NOME: ClassVar[str] = "ReservaExpirada"
