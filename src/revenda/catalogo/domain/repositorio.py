"""Porta de persistência do agregado Veiculo (implementada em catalogo/infrastructure)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from revenda.catalogo.domain.veiculo import StatusVeiculo, Transicao, Veiculo


class VeiculoRepository(Protocol):
    def adicionar(self, veiculo: Veiculo) -> None: ...

    def obter(self, veiculo_id: UUID) -> Veiculo | None: ...

    def salvar_edicao(self, veiculo: Veiculo, versao_lida: int) -> bool:
        """Grava a edição só se o veículo ainda estiver na `versao_lida` e à venda.

        Devolve False quando outra operação alterou o veículo nesse meio-tempo.
        """
        ...

    def aplicar_transicao(
        self, veiculo_id: UUID, transicao: Transicao, agora: datetime
    ) -> Veiculo | None:
        """UPDATE condicional (ADR-008): muda o status só se ele for `transicao.origem`.

        Devolve o veículo já atualizado, ou None se nenhuma linha foi afetada (veículo
        inexistente ou em outro status).
        """
        ...

    def listar_por_status(
        self, status: StatusVeiculo, *, limite: int, deslocamento: int
    ) -> tuple[Sequence[Veiculo], int]:
        """Página ordenada por preço asc, criado_em asc, id (RN-17) e o total do filtro."""
        ...
