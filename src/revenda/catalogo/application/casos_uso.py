"""Casos de uso do Catálogo (docs/04-arquitetura.md, seção 4)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from revenda.catalogo.domain.erros import ConflitoConcorrenciaError, VeiculoNaoEncontradoError
from revenda.catalogo.domain.repositorio import VeiculoRepository
from revenda.catalogo.domain.veiculo import StatusVeiculo, Veiculo
from revenda.shared.clock import Clock
from revenda.shared.paginacao import Pagina
from revenda.shared.uow import UnidadeDeTrabalho

LIMITE_VARREDURA_EXPIRADAS = 100


class ExpiradorReservas(Protocol):
    """Porta para a expiração preguiçosa das reservas vencidas (ADR-009, R1).

    Pertence ao Catálogo porque é a vitrine que precisa dela; a implementação é do módulo
    Vendas (dono das vendas e dos prazos) e é ligada na composição da aplicação.
    """

    def expirar_vencidas(self, limite: int) -> int:
        """Cancela até `limite` vendas vencidas e libera os veículos; devolve quantas."""
        ...


@dataclass(frozen=True, slots=True)
class DadosCadastro:
    marca: str
    modelo: str
    ano: int
    cor: str
    preco: Decimal


@dataclass(frozen=True, slots=True)
class DadosEdicao:
    marca: str | None = None
    modelo: str | None = None
    ano: int | None = None
    cor: str | None = None
    preco: Decimal | None = None


class CadastrarVeiculo:
    def __init__(self, repo: VeiculoRepository, uow: UnidadeDeTrabalho, relogio: Clock) -> None:
        self._repo = repo
        self._uow = uow
        self._relogio = relogio

    def executar(self, dados: DadosCadastro) -> Veiculo:
        veiculo = Veiculo.cadastrar(
            marca=dados.marca,
            modelo=dados.modelo,
            ano=dados.ano,
            cor=dados.cor,
            preco=dados.preco,
            agora=self._relogio.agora(),
        )
        self._repo.adicionar(veiculo)
        self._uow.registrar_eventos(veiculo.coletar_eventos())
        self._uow.confirmar()
        return veiculo


class EditarVeiculo:
    def __init__(self, repo: VeiculoRepository, uow: UnidadeDeTrabalho, relogio: Clock) -> None:
        self._repo = repo
        self._uow = uow
        self._relogio = relogio

    def executar(self, veiculo_id: UUID, dados: DadosEdicao) -> Veiculo:
        veiculo = self._repo.obter(veiculo_id)
        if veiculo is None:
            raise VeiculoNaoEncontradoError(veiculo_id)
        versao_lida = veiculo.versao
        alterou = veiculo.editar(
            agora=self._relogio.agora(),
            marca=dados.marca,
            modelo=dados.modelo,
            ano=dados.ano,
            cor=dados.cor,
            preco=dados.preco,
        )
        if not alterou:
            return veiculo  # nada mudou: sem nova versão, sem evento, sem escrita
        # A leitura não trava a linha: se o veículo for reservado ou editado entre a
        # leitura e a gravação, o UPDATE condicional não afeta nenhuma linha.
        if not self._repo.salvar_edicao(veiculo, versao_lida):
            raise ConflitoConcorrenciaError(veiculo_id)
        self._uow.registrar_eventos(veiculo.coletar_eventos())
        self._uow.confirmar()
        return veiculo


class ObterVeiculo:
    def __init__(self, repo: VeiculoRepository, expirador: ExpiradorReservas | None = None) -> None:
        self._repo = repo
        self._expirador = expirador

    def executar(self, veiculo_id: UUID) -> Veiculo:
        # Mesma expiração preguiçosa da vitrine: a consulta nunca mostra RESERVADO para um
        # veículo cuja reserva já venceu.
        if self._expirador is not None:
            self._expirador.expirar_vencidas(LIMITE_VARREDURA_EXPIRADAS)
        veiculo = self._repo.obter(veiculo_id)
        if veiculo is None:
            raise VeiculoNaoEncontradoError(veiculo_id)
        return veiculo


class ListarAVenda:
    def __init__(self, repo: VeiculoRepository, expirador: ExpiradorReservas | None) -> None:
        self._repo = repo
        self._expirador = expirador

    def executar(self, *, limite: int, deslocamento: int) -> Pagina[Veiculo]:
        # Sem esta varredura, um veículo cuja reserva venceu ficaria fora da vitrine até
        # alguém tentar comprá-lo pelo id — o que ninguém faria, já que ele não aparece.
        if self._expirador is not None:
            self._expirador.expirar_vencidas(LIMITE_VARREDURA_EXPIRADAS)
        itens, total = self._repo.listar_por_status(
            StatusVeiculo.A_VENDA, limite=limite, deslocamento=deslocamento
        )
        return Pagina(itens=itens, total=total, limite=limite, deslocamento=deslocamento)


class ListarVendidos:
    def __init__(self, repo: VeiculoRepository) -> None:
        self._repo = repo

    def executar(self, *, limite: int, deslocamento: int) -> Pagina[Veiculo]:
        itens, total = self._repo.listar_por_status(
            StatusVeiculo.VENDIDO, limite=limite, deslocamento=deslocamento
        )
        return Pagina(itens=itens, total=total, limite=limite, deslocamento=deslocamento)


@dataclass(frozen=True, slots=True)
class CasosUsoCatalogo:
    """Casos de uso já ligados a uma sessão; entregues aos routers por injeção."""

    cadastrar: CadastrarVeiculo
    editar: EditarVeiculo
    obter: ObterVeiculo
    listar_a_venda: ListarAVenda
    listar_vendidos: ListarVendidos


FabricaCasosUsoCatalogo = Callable[..., CasosUsoCatalogo]
