"""Porta de persistência do agregado Venda (implementada em vendas/infrastructure)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from revenda.vendas.domain.venda import StatusVenda, Venda


class VendaRepository(Protocol):
    def adicionar(self, venda: Venda) -> None:
        """Insere a venda. VendaAtivaDuplicadaError se o veículo já tiver venda ativa."""
        ...

    def salvar(self, venda: Venda) -> None:
        """Grava a transição de uma venda que estava AGUARDANDO_PAGAMENTO.

        ConflitoConcorrenciaVendaError se a venda não estava mais aguardando pagamento.
        """
        ...

    def obter(self, venda_id: UUID, *, para_atualizar: bool = False) -> Venda | None: ...

    def obter_por_codigo(
        self, codigo_pagamento: str, *, para_atualizar: bool = False
    ) -> Venda | None: ...

    def obter_ativa_do_veiculo(
        self, veiculo_id: UUID, *, para_atualizar: bool = False
    ) -> Venda | None: ...

    def listar_expiradas(self, agora: datetime, limite: int) -> Sequence[Venda]:
        """Vendas aguardando pagamento vencidas, travadas para atualização (SKIP LOCKED)."""
        ...

    def listar(
        self,
        *,
        comprador_id: str | None,
        status: StatusVenda | None,
        limite: int,
        deslocamento: int,
    ) -> tuple[Sequence[Venda], int]:
        """Página ordenada por criada_em desc (desempate id) e o total do filtro."""
        ...
