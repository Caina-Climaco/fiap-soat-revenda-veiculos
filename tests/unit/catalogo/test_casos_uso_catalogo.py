"""Casos de uso do Catálogo com repositório em memória e relógio fixo."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apoio.fakes import UowFalsa, VeiculoRepoMemoria
from revenda.catalogo.application.adaptador_vendas import CatalogoAdapter
from revenda.catalogo.application.casos_uso import (
    CadastrarVeiculo,
    DadosCadastro,
    DadosEdicao,
    EditarVeiculo,
    ListarAVenda,
    ListarVendidos,
    ObterVeiculo,
)
from revenda.catalogo.domain.erros import ConflitoConcorrenciaError, VeiculoNaoEncontradoError
from revenda.catalogo.domain.veiculo import StatusVeiculo, Veiculo
from revenda.shared.clock import RelogioFixo

AGORA = datetime(2026, 10, 3, 10, 0, tzinfo=UTC)


@pytest.fixture
def repo() -> VeiculoRepoMemoria:
    return VeiculoRepoMemoria()


@pytest.fixture
def uow() -> UowFalsa:
    return UowFalsa()


@pytest.fixture
def relogio() -> RelogioFixo:
    return RelogioFixo(AGORA)


def cadastrar(repo: VeiculoRepoMemoria, uow: UowFalsa, relogio: RelogioFixo, preco: str) -> Veiculo:
    dados = DadosCadastro(marca="Fiat", modelo="Argo", ano=2022, cor="Prata", preco=Decimal(preco))
    return CadastrarVeiculo(repo, uow, relogio).executar(dados)


def test_cadastrar_persiste_e_publica_evento_apos_confirmar(
    repo: VeiculoRepoMemoria, uow: UowFalsa, relogio: RelogioFixo
) -> None:
    veiculo = cadastrar(repo, uow, relogio, "72000.00")
    assert repo.obter(veiculo.id) is not None
    assert uow.confirmacoes == 1
    assert uow.nomes_publicados == ["VeiculoCadastrado"]


def test_editar_veiculo_a_venda(
    repo: VeiculoRepoMemoria, uow: UowFalsa, relogio: RelogioFixo
) -> None:
    veiculo = cadastrar(repo, uow, relogio, "95000.00")
    relogio.avancar(timedelta(minutes=1))
    editado = EditarVeiculo(repo, uow, relogio).executar(
        veiculo.id, DadosEdicao(preco=Decimal("90000.00"))
    )
    assert editado.preco == Decimal("90000.00")
    armazenado = repo.obter(veiculo.id)
    assert armazenado is not None
    assert armazenado.versao == 2
    assert uow.nomes_publicados[-1] == "VeiculoEditado"


def test_editar_inexistente(repo: VeiculoRepoMemoria, uow: UowFalsa, relogio: RelogioFixo) -> None:
    with pytest.raises(VeiculoNaoEncontradoError):
        EditarVeiculo(repo, uow, relogio).executar(uuid.uuid4(), DadosEdicao(cor="Azul"))


def test_editar_detecta_alteracao_concorrente(
    repo: VeiculoRepoMemoria, uow: UowFalsa, relogio: RelogioFixo
) -> None:
    veiculo = cadastrar(repo, uow, relogio, "95000.00")

    class RepoQueReservaNoMeio(VeiculoRepoMemoria):
        def obter(self, veiculo_id: uuid.UUID) -> Veiculo | None:
            lido = super().obter(veiculo_id)
            # Outra transação reserva o veículo depois da leitura.
            self.dados[veiculo_id].status = StatusVeiculo.RESERVADO
            return lido

    concorrente = RepoQueReservaNoMeio()
    concorrente.dados = repo.dados
    with pytest.raises(ConflitoConcorrenciaError):
        EditarVeiculo(concorrente, uow, relogio).executar(
            veiculo.id, DadosEdicao(preco=Decimal("1.00"))
        )
    assert repo.dados[veiculo.id].preco == Decimal("95000.00")


def test_obter(repo: VeiculoRepoMemoria, uow: UowFalsa, relogio: RelogioFixo) -> None:
    veiculo = cadastrar(repo, uow, relogio, "1.00")
    assert ObterVeiculo(repo).executar(veiculo.id).id == veiculo.id
    with pytest.raises(VeiculoNaoEncontradoError):
        ObterVeiculo(repo).executar(uuid.uuid4())


class ExpiradorEspiao:
    def __init__(self) -> None:
        self.chamadas: list[int] = []

    def expirar_vencidas(self, limite: int) -> int:
        self.chamadas.append(limite)
        return 0


def test_listar_a_venda_ordena_por_preco_e_aciona_expiracao(
    repo: VeiculoRepoMemoria, uow: UowFalsa, relogio: RelogioFixo
) -> None:
    for preco in ("150000.00", "45000.00", "72000.00"):
        cadastrar(repo, uow, relogio, preco)
    expirador = ExpiradorEspiao()
    pagina = ListarAVenda(repo, expirador).executar(limite=2, deslocamento=0)
    assert [str(v.preco) for v in pagina.itens] == ["45000.00", "72000.00"]
    assert pagina.total == 3
    assert expirador.chamadas == [100]
    assert ListarAVenda(repo, None).executar(limite=2, deslocamento=2).total == 3


def test_listar_vendidos(repo: VeiculoRepoMemoria, uow: UowFalsa, relogio: RelogioFixo) -> None:
    caro = cadastrar(repo, uow, relogio, "120000.00")
    barato = cadastrar(repo, uow, relogio, "55000.00")
    cadastrar(repo, uow, relogio, "1000.00")
    adaptador = CatalogoAdapter(repo, uow)
    for veiculo in (caro, barato):
        assert adaptador.reservar(veiculo.id, AGORA) is not None
        assert adaptador.marcar_vendido(veiculo.id, AGORA)
    pagina = ListarVendidos(repo).executar(limite=20, deslocamento=0)
    assert [v.id for v in pagina.itens] == [barato.id, caro.id]
    assert pagina.total == 2


def test_adaptador_catalogo(repo: VeiculoRepoMemoria, uow: UowFalsa, relogio: RelogioFixo) -> None:
    veiculo = cadastrar(repo, uow, relogio, "50000.00")
    adaptador = CatalogoAdapter(repo, uow)
    reservado = adaptador.reservar(veiculo.id, AGORA)
    assert reservado is not None
    assert (reservado.marca, reservado.preco) == ("Fiat", Decimal("50000.00"))
    assert adaptador.reservar(veiculo.id, AGORA) is None
    assert adaptador.status_veiculo(veiculo.id) == "RESERVADO"
    assert adaptador.status_veiculo(uuid.uuid4()) is None
    assert adaptador.liberar(veiculo.id, AGORA)
    assert not adaptador.liberar(veiculo.id, AGORA)
    assert not adaptador.marcar_vendido(veiculo.id, AGORA)
    assert [e.nome for e in uow.pendentes] == [
        "VeiculoReservado",
        "VeiculoLiberado",
    ]
