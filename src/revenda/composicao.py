"""Composição dos módulos: o único lugar que conhece Catálogo e Vendas ao mesmo tempo.

Cada requisição recebe uma sessão; repositórios, Unit of Work, `CatalogoAdapter` e casos
de uso são montados sobre ela, de modo que a venda e o veículo mudam na mesma transação.
"""

# Sem `from __future__ import annotations` neste módulo: as dependências usam aliases
# `Annotated[..., Depends(...)]` locais à fábrica, e o FastAPI só os resolve se as
# anotações forem avaliadas na definição da função (com o escopo local).

from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from revenda.catalogo.application.adaptador_vendas import CatalogoAdapter
from revenda.catalogo.application.casos_uso import (
    CadastrarVeiculo,
    CasosUsoCatalogo,
    EditarVeiculo,
    ListarAVenda,
    ListarVendidos,
    ObterVeiculo,
)
from revenda.catalogo.infrastructure.repositorio_sql import SqlVeiculoRepository
from revenda.shared.clock import Clock
from revenda.shared.db import BancoDeDados, SqlUnidadeDeTrabalho
from revenda.shared.eventos import PublicadorEventos
from revenda.vendas.application.casos_uso import (
    CancelarVenda,
    CasosUsoVendas,
    ExpirarReservasVencidas,
    IniciarCompra,
    ListarVendas,
    ObterVenda,
    ProcessarPagamento,
)
from revenda.vendas.application.portas import CatalogoPort
from revenda.vendas.infrastructure.repositorio_sql import SqlVendaRepository


class Composicao:
    def __init__(
        self,
        banco: BancoDeDados,
        relogio: Clock,
        publicador: PublicadorEventos,
        *,
        ttl_reserva: timedelta,
    ) -> None:
        self._banco = banco
        self._relogio = relogio
        self._publicador = publicador
        self._ttl = ttl_reserva

    def dependencias(
        self,
    ) -> tuple[Callable[..., CasosUsoCatalogo], Callable[..., CasosUsoVendas]]:
        """Dependências FastAPI que entregam os casos de uso de cada módulo."""

        def sessao() -> Iterator[Session]:
            yield from self._banco.sessao()

        Sessao = Annotated[Session, Depends(sessao)]

        def catalogo(sessao: Sessao) -> CasosUsoCatalogo:
            return self.casos_uso_catalogo(sessao)

        def vendas(sessao: Sessao) -> CasosUsoVendas:
            return self.casos_uso_vendas(sessao)

        return catalogo, vendas

    def casos_uso_catalogo(self, sessao: Session) -> CasosUsoCatalogo:
        uow = SqlUnidadeDeTrabalho(sessao, self._publicador)
        repo = SqlVeiculoRepository(sessao)
        return CasosUsoCatalogo(
            cadastrar=CadastrarVeiculo(repo, uow, self._relogio),
            editar=EditarVeiculo(repo, uow, self._relogio),
            obter=ObterVeiculo(repo),
            listar_a_venda=ListarAVenda(repo, self._expirador(sessao, uow, repo)),
            listar_vendidos=ListarVendidos(repo),
        )

    def casos_uso_vendas(self, sessao: Session) -> CasosUsoVendas:
        uow = SqlUnidadeDeTrabalho(sessao, self._publicador)
        repo = SqlVendaRepository(sessao)
        catalogo: CatalogoPort = CatalogoAdapter(SqlVeiculoRepository(sessao), uow)
        return CasosUsoVendas(
            iniciar_compra=IniciarCompra(repo, catalogo, uow, self._relogio, ttl_reserva=self._ttl),
            processar_pagamento=ProcessarPagamento(repo, catalogo, uow, self._relogio),
            cancelar=CancelarVenda(repo, catalogo, uow, self._relogio),
            obter=ObterVenda(repo),
            listar=ListarVendas(repo),
        )

    def _expirador(
        self, sessao: Session, uow: SqlUnidadeDeTrabalho, repo: SqlVeiculoRepository
    ) -> ExpirarReservasVencidas:
        catalogo: CatalogoPort = CatalogoAdapter(repo, uow)
        return ExpirarReservasVencidas(SqlVendaRepository(sessao), catalogo, uow, self._relogio)
