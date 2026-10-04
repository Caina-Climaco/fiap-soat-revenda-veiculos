"""Casos de uso de Vendas (docs/04-arquitetura.md, seções 4 e 6)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from revenda.shared.clock import Clock
from revenda.shared.paginacao import Pagina
from revenda.shared.uow import UnidadeDeTrabalho
from revenda.vendas.application.portas import CatalogoPort, GeradorCodigoPagamento
from revenda.vendas.domain.erros import (
    CompraNaoPermitidaError,
    InconsistenciaCatalogoError,
    PagamentoNaoEncontradoError,
    ReservaExpiradaError,
    TransicaoVendaInvalidaError,
    VeiculoIndisponivelError,
    VeiculoNaoEncontradoError,
    VendaAtivaDuplicadaError,
    VendaNaoEncontradaError,
)
from revenda.vendas.domain.repositorio import VendaRepository
from revenda.vendas.domain.venda import (
    CodigoPagamento,
    DescricaoVeiculo,
    MotivoCancelamento,
    StatusVenda,
    Venda,
)

_logger = logging.getLogger("revenda.vendas")


@dataclass(frozen=True, slots=True)
class Solicitante:
    """Quem pede a operação, já autenticado: pseudônimo `sub` e o que ele pode fazer."""

    id: str
    eh_gestor: bool


class _BaseVendas:
    def __init__(
        self,
        repo: VendaRepository,
        catalogo: CatalogoPort,
        uow: UnidadeDeTrabalho,
        relogio: Clock,
    ) -> None:
        self._repo = repo
        self._catalogo = catalogo
        self._uow = uow
        self._relogio = relogio

    def _expirar(self, venda: Venda, agora: datetime) -> None:
        """Cancela por RESERVA_EXPIRADA e libera o veículo (ADR-009), na transação corrente."""
        venda.expirar(agora)
        self._repo.salvar(venda)
        if not self._catalogo.liberar(venda.veiculo_id, agora):
            # Tolerado: a liberação é idempotente e o objetivo (veículo fora da reserva
            # desta venda) já está atendido; registra-se para investigação.
            _logger.warning(
                "veículo não estava reservado ao expirar a venda",
                extra={"campos": {"venda_id": str(venda.id), "veiculo_id": str(venda.veiculo_id)}},
            )

    def _cancelar_e_liberar(
        self, venda: Venda, motivo: MotivoCancelamento, agora: datetime
    ) -> None:
        venda.cancelar(motivo, agora)
        self._repo.salvar(venda)
        if not self._catalogo.liberar(venda.veiculo_id, agora):
            raise InconsistenciaCatalogoError(venda.veiculo_id, "liberar")

    def _confirmar(self, *vendas: Venda) -> None:
        for venda in vendas:
            self._uow.registrar_eventos(venda.coletar_eventos())
        self._uow.confirmar()


class IniciarCompra(_BaseVendas):
    def __init__(
        self,
        repo: VendaRepository,
        catalogo: CatalogoPort,
        uow: UnidadeDeTrabalho,
        relogio: Clock,
        *,
        ttl_reserva: timedelta,
        gerar_codigo: GeradorCodigoPagamento = CodigoPagamento.gerar,
    ) -> None:
        super().__init__(repo, catalogo, uow, relogio)
        self._ttl = ttl_reserva
        self._gerar_codigo = gerar_codigo

    def executar(self, veiculo_id: UUID, solicitante: Solicitante) -> Venda:
        if solicitante.eh_gestor:
            raise CompraNaoPermitidaError
        agora = self._relogio.agora()

        # Expiração preguiçosa: uma venda vencida ainda "ocupa" o veículo; cancelá-la
        # aqui, na mesma transação, permite que esta compra o reserve em seguida.
        vencida = self._repo.obter_ativa_do_veiculo(veiculo_id, para_atualizar=True)
        expiradas: list[Venda] = []
        if vencida is not None and vencida.esta_expirada(agora):
            self._expirar(vencida, agora)
            expiradas.append(vencida)

        reservado = self._catalogo.reservar(veiculo_id, agora)
        if reservado is None:
            status = self._catalogo.status_veiculo(veiculo_id)
            if status is None:
                raise VeiculoNaoEncontradoError(veiculo_id)
            raise VeiculoIndisponivelError(veiculo_id, status)

        venda = Venda.iniciar(
            veiculo_id=veiculo_id,
            comprador_id=solicitante.id,
            preco_venda=reservado.preco,
            veiculo=DescricaoVeiculo(
                marca=reservado.marca, modelo=reservado.modelo, ano=reservado.ano, cor=reservado.cor
            ),
            agora=agora,
            ttl=self._ttl,
            codigo_pagamento=self._gerar_codigo(),
        )
        try:
            self._repo.adicionar(venda)
        except VendaAtivaDuplicadaError as exc:
            # Segunda barreira (índice único parcial): só ocorre se a reserva do veículo
            # tiver sido contornada; para o cliente é o mesmo "veículo indisponível".
            raise VeiculoIndisponivelError(veiculo_id) from exc
        self._confirmar(*expiradas, venda)
        return venda


class ProcessarPagamento(_BaseVendas):
    """Resultado do gateway já traduzido pela ACL do webhook (aprovado: bool)."""

    def executar(self, codigo_pagamento: str, *, aprovado: bool) -> Venda:
        agora = self._relogio.agora()
        venda = self._repo.obter_por_codigo(codigo_pagamento, para_atualizar=True)
        if venda is None:
            raise PagamentoNaoEncontradoError(codigo_pagamento)
        if aprovado:
            return self._aprovar(venda, agora)
        return self._recusar(venda, agora)

    def _aprovar(self, venda: Venda, agora: datetime) -> Venda:
        if venda.esta_expirada(agora):
            # RN-14: confirma o cancelamento antes de responder 409, para que a reserva
            # vencida não continue travando o veículo.
            self._expirar(venda, agora)
            self._confirmar(venda)
            raise ReservaExpiradaError(venda.id)
        if not venda.efetivar(agora):
            return venda  # já EFETIVADA: notificação repetida, sem efeito (RN-08)
        self._repo.salvar(venda)
        if not self._catalogo.marcar_vendido(venda.veiculo_id, agora):
            raise InconsistenciaCatalogoError(venda.veiculo_id, "marcar como vendido")
        self._confirmar(venda)
        return venda

    def _recusar(self, venda: Venda, agora: datetime) -> Venda:
        if venda.status is StatusVenda.CANCELADA:
            return venda  # recusa repetida (ou venda já cancelada): sem efeito (RN-08)
        if venda.status is StatusVenda.EFETIVADA:
            raise TransicaoVendaInvalidaError(venda.id, venda.status.value, "recusar o pagamento")
        if venda.esta_expirada(agora):
            self._expirar(venda, agora)
        else:
            self._cancelar_e_liberar(venda, MotivoCancelamento.PAGAMENTO_RECUSADO, agora)
        self._confirmar(venda)
        return venda


class CancelarVenda(_BaseVendas):
    def executar(self, venda_id: UUID, solicitante: Solicitante) -> Venda:
        agora = self._relogio.agora()
        venda = self._repo.obter(venda_id, para_atualizar=True)
        if venda is None or not _visivel(venda, solicitante):
            raise VendaNaoEncontradaError(venda_id)
        if venda.status is not StatusVenda.AGUARDANDO_PAGAMENTO:
            raise TransicaoVendaInvalidaError(venda.id, venda.status.value, "cancelar")
        if venda.esta_expirada(agora):
            self._expirar(venda, agora)
        else:
            motivo = (
                MotivoCancelamento.CANCELADA_PELA_LOJA
                if solicitante.eh_gestor
                else MotivoCancelamento.DESISTENCIA_COMPRADOR
            )
            self._cancelar_e_liberar(venda, motivo, agora)
        self._confirmar(venda)
        return venda


class ExpirarReservasVencidas(_BaseVendas):
    """Varredura limitada de reservas vencidas; implementa `ExpiradorReservas` do Catálogo."""

    def expirar_vencidas(self, limite: int) -> int:
        agora = self._relogio.agora()
        vencidas = list(self._repo.listar_expiradas(agora, limite))
        if not vencidas:
            return 0
        for venda in vencidas:
            self._expirar(venda, agora)
        self._confirmar(*vencidas)
        return len(vencidas)


class ObterVenda:
    def __init__(self, repo: VendaRepository) -> None:
        self._repo = repo

    def executar(self, venda_id: UUID, solicitante: Solicitante) -> Venda:
        venda = self._repo.obter(venda_id)
        # Para quem não é dono nem gestor, a venda "não existe" (RN-13, proteção BOLA).
        if venda is None or not _visivel(venda, solicitante):
            raise VendaNaoEncontradaError(venda_id)
        return venda


class ListarVendas:
    def __init__(self, repo: VendaRepository) -> None:
        self._repo = repo

    def do_comprador(self, comprador_id: str, *, limite: int, deslocamento: int) -> Pagina[Venda]:
        itens, total = self._repo.listar(
            comprador_id=comprador_id, status=None, limite=limite, deslocamento=deslocamento
        )
        return Pagina(itens=itens, total=total, limite=limite, deslocamento=deslocamento)

    def todas(self, *, status: StatusVenda | None, limite: int, deslocamento: int) -> Pagina[Venda]:
        itens, total = self._repo.listar(
            comprador_id=None, status=status, limite=limite, deslocamento=deslocamento
        )
        return Pagina(itens=itens, total=total, limite=limite, deslocamento=deslocamento)


def _visivel(venda: Venda, solicitante: Solicitante) -> bool:
    return solicitante.eh_gestor or venda.pertence_a(solicitante.id)


@dataclass(frozen=True, slots=True)
class CasosUsoVendas:
    """Casos de uso já ligados a uma sessão; entregues aos routers por injeção."""

    iniciar_compra: IniciarCompra
    processar_pagamento: ProcessarPagamento
    cancelar: CancelarVenda
    obter: ObterVenda
    listar: ListarVendas


FabricaCasosUsoVendas = Callable[..., CasosUsoVendas]
