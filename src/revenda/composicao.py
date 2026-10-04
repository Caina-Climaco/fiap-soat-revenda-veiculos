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
from revenda.catalogo.domain.eventos import VeiculoCadastrado
from revenda.catalogo.infrastructure.repositorio_sql import SqlVeiculoRepository
from revenda.shared.clock import Clock
from revenda.shared.db import BancoDeDados, SqlUnidadeDeTrabalho
from revenda.shared.eventos import EventoDominio, PublicadorEventos
from revenda.shared.metricas import AcaoMetrica, Metricas, rotulo_do_evento
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
from revenda.vendas.domain.eventos import CompraIniciada, VendaCancelada, VendaEfetivada
from revenda.vendas.domain.venda import MotivoCancelamento
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
        expirador = self._expirador(sessao, uow, repo)
        return CasosUsoCatalogo(
            cadastrar=CadastrarVeiculo(repo, uow, self._relogio),
            editar=EditarVeiculo(repo, uow, self._relogio),
            obter=ObterVeiculo(repo, expirador),
            listar_a_venda=ListarAVenda(repo, expirador),
            listar_vendidos=ListarVendidos(repo),
        )

    def casos_uso_vendas(self, sessao: Session) -> CasosUsoVendas:
        uow = SqlUnidadeDeTrabalho(sessao, self._publicador)
        repo = SqlVendaRepository(sessao)
        catalogo: CatalogoPort = CatalogoAdapter(SqlVeiculoRepository(sessao), uow)
        expirador = ExpirarReservasVencidas(repo, catalogo, uow, self._relogio)
        return CasosUsoVendas(
            iniciar_compra=IniciarCompra(repo, catalogo, uow, self._relogio, ttl_reserva=self._ttl),
            processar_pagamento=ProcessarPagamento(repo, catalogo, uow, self._relogio),
            cancelar=CancelarVenda(repo, catalogo, uow, self._relogio),
            obter=ObterVenda(repo, expirador),
            listar=ListarVendas(repo, expirador),
        )

    def _expirador(
        self, sessao: Session, uow: SqlUnidadeDeTrabalho, repo: SqlVeiculoRepository
    ) -> ExpirarReservasVencidas:
        catalogo: CatalogoPort = CatalogoAdapter(repo, uow)
        return ExpirarReservasVencidas(SqlVendaRepository(sessao), catalogo, uow, self._relogio)


def acoes_metricas_negocio(metricas: Metricas) -> dict[str, AcaoMetrica]:
    """Liga os eventos de domínio (já confirmados) aos contadores de negócio.

    Fica aqui, e não em `shared/metricas.py`, porque só a composição conhece os eventos
    dos dois módulos; o domínio continua sem saber que existem métricas.
    """
    for motivo in MotivoCancelamento:  # séries com zero desde o início (rate() sem lacunas)
        metricas.vendas_canceladas.labels(motivo=motivo.value)

    def cancelada(evento: EventoDominio) -> None:
        metricas.vendas_canceladas.labels(motivo=rotulo_do_evento(evento, "motivo")).inc()

    return {
        VeiculoCadastrado.NOME: lambda _evento: metricas.veiculos_cadastrados.inc(),
        CompraIniciada.NOME: lambda _evento: metricas.vendas_iniciadas.inc(),
        VendaEfetivada.NOME: lambda _evento: metricas.vendas_efetivadas.inc(),
        VendaCancelada.NOME: cancelada,
    }
