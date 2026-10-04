"""Implementação in-process da `CatalogoPort` de Vendas (relação cliente-fornecedor).

O Catálogo não importa nada de Vendas: este adaptador satisfaz a porta por tipagem
estrutural (Protocol) e é ligado na composição da aplicação. Roda na mesma sessão (e
transação) do caso de uso de Vendas que o chama.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from revenda.catalogo.domain.repositorio import VeiculoRepository
from revenda.catalogo.domain.veiculo import Transicao
from revenda.shared.uow import UnidadeDeTrabalho


@dataclass(frozen=True, slots=True)
class VeiculoReservadoInfo:
    """Snapshot do veículo no instante da reserva (base do preço congelado da venda)."""

    marca: str
    modelo: str
    ano: int
    cor: str
    preco: Decimal


class CatalogoAdapter:
    def __init__(self, repo: VeiculoRepository, uow: UnidadeDeTrabalho) -> None:
        self._repo = repo
        self._uow = uow

    def reservar(self, veiculo_id: UUID, agora: datetime) -> VeiculoReservadoInfo | None:
        veiculo = self._repo.aplicar_transicao(veiculo_id, Transicao.RESERVAR, agora)
        if veiculo is None:
            return None
        self._uow.registrar_eventos([Transicao.RESERVAR.evento(veiculo_id, agora)])
        return VeiculoReservadoInfo(
            marca=veiculo.marca,
            modelo=veiculo.modelo,
            ano=veiculo.ano,
            cor=veiculo.cor,
            preco=veiculo.preco,
        )

    def liberar(self, veiculo_id: UUID, agora: datetime) -> bool:
        return self._transitar(veiculo_id, Transicao.LIBERAR, agora)

    def marcar_vendido(self, veiculo_id: UUID, agora: datetime) -> bool:
        return self._transitar(veiculo_id, Transicao.MARCAR_VENDIDO, agora)

    def status_veiculo(self, veiculo_id: UUID) -> str | None:
        veiculo = self._repo.obter(veiculo_id)
        return None if veiculo is None else veiculo.status.value

    def _transitar(self, veiculo_id: UUID, transicao: Transicao, agora: datetime) -> bool:
        if self._repo.aplicar_transicao(veiculo_id, transicao, agora) is None:
            return False
        self._uow.registrar_eventos([transicao.evento(veiculo_id, agora)])
        return True
