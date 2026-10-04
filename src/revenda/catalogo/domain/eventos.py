"""Eventos de domínio do Catálogo (registrados em log estruturado após o commit)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID


@dataclass(frozen=True, slots=True)
class EventoCatalogo:
    NOME: ClassVar[str] = "EventoCatalogo"

    veiculo_id: UUID
    ocorrido_em: datetime

    @property
    def nome(self) -> str:
        return self.NOME

    def como_dict(self) -> dict[str, str]:
        return {"veiculo_id": str(self.veiculo_id), "ocorrido_em": self.ocorrido_em.isoformat()}


@dataclass(frozen=True, slots=True)
class VeiculoCadastrado(EventoCatalogo):
    NOME: ClassVar[str] = "VeiculoCadastrado"

    preco: Decimal = Decimal("0")

    def como_dict(self) -> dict[str, str]:
        return {**EventoCatalogo.como_dict(self), "preco": str(self.preco)}


@dataclass(frozen=True, slots=True)
class VeiculoEditado(EventoCatalogo):
    NOME: ClassVar[str] = "VeiculoEditado"

    versao: int = 0
    campos: str = ""

    def como_dict(self) -> dict[str, str]:
        return {
            **EventoCatalogo.como_dict(self),
            "versao": str(self.versao),
            "campos": self.campos,
        }


@dataclass(frozen=True, slots=True)
class VeiculoReservado(EventoCatalogo):
    NOME: ClassVar[str] = "VeiculoReservado"


@dataclass(frozen=True, slots=True)
class VeiculoLiberado(EventoCatalogo):
    NOME: ClassVar[str] = "VeiculoLiberado"


@dataclass(frozen=True, slots=True)
class VeiculoVendido(EventoCatalogo):
    NOME: ClassVar[str] = "VeiculoVendido"
