"""Portas de saída de Vendas.

`CatalogoPort` é definida pelo consumidor (Vendas) com o que ele precisa do Catálogo; a
implementação (`CatalogoAdapter`) mora no módulo Catálogo e é ligada na composição.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from revenda.vendas.domain.venda import CodigoPagamento


class DadosVeiculoReservado(Protocol):
    @property
    def marca(self) -> str: ...

    @property
    def modelo(self) -> str: ...

    @property
    def ano(self) -> int: ...

    @property
    def cor(self) -> str: ...

    @property
    def preco(self) -> Decimal: ...


class CatalogoPort(Protocol):
    def reservar(self, veiculo_id: UUID, agora: datetime) -> DadosVeiculoReservado | None:
        """A_VENDA → RESERVADO de forma atômica; None se o veículo não estava à venda."""
        ...

    def liberar(self, veiculo_id: UUID, agora: datetime) -> bool:
        """RESERVADO → A_VENDA; False se o veículo não estava reservado."""
        ...

    def marcar_vendido(self, veiculo_id: UUID, agora: datetime) -> bool:
        """RESERVADO → VENDIDO; False se o veículo não estava reservado."""
        ...

    def status_veiculo(self, veiculo_id: UUID) -> str | None:
        """Status atual (para diagnosticar uma reserva negada); None se não existe."""
        ...


GeradorCodigoPagamento = Callable[[], CodigoPagamento]
