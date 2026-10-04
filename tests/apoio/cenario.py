"""Cenário de Vendas em memória: catálogo real (adaptador) sobre repositórios falsos."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from apoio.fakes import UowFalsa, VeiculoRepoMemoria, VendaRepoMemoria
from revenda.catalogo.application.adaptador_vendas import CatalogoAdapter
from revenda.catalogo.domain.veiculo import StatusVeiculo, Veiculo
from revenda.shared.clock import RelogioFixo
from revenda.vendas.application.casos_uso import (
    CancelarVenda,
    ExpirarReservasVencidas,
    IniciarCompra,
    ListarVendas,
    ObterVenda,
    ProcessarPagamento,
    Solicitante,
)

AS_10H = datetime(2026, 10, 3, 10, 0, tzinfo=UTC)
TTL = timedelta(minutes=30)
CLIENTE_A = Solicitante(id="cliente-a", eh_gestor=False)
CLIENTE_B = Solicitante(id="cliente-b", eh_gestor=False)
GESTOR = Solicitante(id="gestor", eh_gestor=True)


@dataclass
class Cenario:
    veiculos: VeiculoRepoMemoria
    vendas: VendaRepoMemoria
    uow: UowFalsa
    relogio: RelogioFixo

    @property
    def catalogo(self) -> CatalogoAdapter:
        return CatalogoAdapter(self.veiculos, self.uow)

    def veiculo(self, preco: str = "72000.00") -> Veiculo:
        veiculo = Veiculo.cadastrar(
            marca="Hyundai", modelo="HB20", ano=2021, cor="Azul", preco=preco, agora=AS_10H
        )
        self.veiculos.adicionar(veiculo)
        return veiculo

    def status_veiculo(self, veiculo_id: UUID) -> StatusVeiculo:
        return self.veiculos.dados[veiculo_id].status

    def preco_veiculo(self, veiculo_id: UUID) -> Decimal:
        return self.veiculos.dados[veiculo_id].preco

    def iniciar_compra(self) -> IniciarCompra:
        return IniciarCompra(self.vendas, self.catalogo, self.uow, self.relogio, ttl_reserva=TTL)

    def processar_pagamento(self) -> ProcessarPagamento:
        return ProcessarPagamento(self.vendas, self.catalogo, self.uow, self.relogio)

    def cancelar(self) -> CancelarVenda:
        return CancelarVenda(self.vendas, self.catalogo, self.uow, self.relogio)

    def expirar(self) -> ExpirarReservasVencidas:
        return ExpirarReservasVencidas(self.vendas, self.catalogo, self.uow, self.relogio)

    def obter(self) -> ObterVenda:
        # Ligado ao expirador, como na composição da aplicação.
        return ObterVenda(self.vendas, self.expirar())

    def listar(self) -> ListarVendas:
        return ListarVendas(self.vendas, self.expirar())


def novo_cenario() -> Cenario:
    return Cenario(VeiculoRepoMemoria(), VendaRepoMemoria(), UowFalsa(), RelogioFixo(AS_10H))
