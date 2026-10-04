"""Concorrência real no PostgreSQL (ADR-008): uma sessão/conexão por thread e uma barreira.

As transações disputam a mesma linha de `catalogo.veiculos`; o UPDATE condicional decide a
disputa (READ COMMITTED: quem espera o lock reavalia o WHERE e afeta 0 linhas).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import Engine, text

from apoio.cenario import AS_10H
from revenda.catalogo.domain.veiculo import Veiculo
from revenda.catalogo.infrastructure.repositorio_sql import SqlVeiculoRepository
from revenda.composicao import Composicao
from revenda.shared.clock import RelogioFixo
from revenda.shared.db import BancoDeDados
from revenda.shared.eventos import PublicadorEventosLog
from revenda.vendas.application.casos_uso import Solicitante
from revenda.vendas.domain.erros import VeiculoIndisponivelError, VendaAtivaDuplicadaError
from revenda.vendas.domain.venda import DescricaoVeiculo, Venda
from revenda.vendas.infrastructure.repositorio_sql import SqlVendaRepository

TTL = timedelta(minutes=30)


def _cadastrar(banco: BancoDeDados) -> Veiculo:
    veiculo = Veiculo.cadastrar(
        marca="Honda", modelo="Civic", ano=2020, cor="Preto", preco="98000.00", agora=AS_10H
    )
    with banco.nova_sessao() as sessao:
        SqlVeiculoRepository(sessao).adicionar(veiculo)
        sessao.commit()
    return veiculo


def _em_paralelo(n: int, tarefa: Callable[[int], object]) -> list[object]:
    """Roda `tarefa(i)` em n threads liberadas juntas por uma barreira; devolve resultados."""
    barreira = threading.Barrier(n)
    resultados: list[object] = [None] * n

    def rodar(i: int) -> None:
        barreira.wait(timeout=10)
        try:
            resultados[i] = tarefa(i)
        except Exception as exc:  # o resultado esperado de quem perde a disputa
            resultados[i] = exc

    threads = [threading.Thread(target=rodar, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads), "thread travada (deadlock?)"
    return resultados


def _contar(engine: Engine, sql: str) -> int:
    with engine.connect() as conexao:
        return int(conexao.execute(text(sql)).scalar_one())


def _comprar_em_paralelo(banco: BancoDeDados, n: int) -> tuple[Veiculo, list[object]]:
    veiculo = _cadastrar(banco)
    composicao = Composicao(banco, RelogioFixo(AS_10H), PublicadorEventosLog(), ttl_reserva=TTL)

    def comprar(i: int) -> Venda:
        with banco.nova_sessao() as sessao:  # uma conexão por thread
            casos = composicao.casos_uso_vendas(sessao)
            return casos.iniciar_compra.executar(
                veiculo.id, Solicitante(id=f"cliente-{i}", eh_gestor=False)
            )

    return veiculo, _em_paralelo(n, comprar)


def test_duas_compras_simultaneas_so_uma_vence(banco: BancoDeDados, engine: Engine) -> None:
    _, resultados = _comprar_em_paralelo(banco, 2)
    assert sum(isinstance(r, Venda) for r in resultados) == 1
    assert sum(isinstance(r, VeiculoIndisponivelError) for r in resultados) == 1
    assert _contar(engine, "SELECT count(*) FROM vendas.vendas") == 1


def test_bdd_03_compra_concorrente(banco: BancoDeDados, engine: Engine) -> None:
    """BDD-03: 10 clientes compram o mesmo veículo ao mesmo tempo; exatamente 1 vence."""
    veiculo, resultados = _comprar_em_paralelo(banco, 10)

    vencedoras = [r for r in resultados if isinstance(r, Venda)]
    perdedoras = [r for r in resultados if isinstance(r, VeiculoIndisponivelError)]
    assert len(vencedoras) == 1
    assert len(perdedoras) == 9, resultados
    assert all(e.status == "RESERVADO" for e in perdedoras)

    assert (
        _contar(
            engine,
            "SELECT count(*) FROM vendas.vendas "
            "WHERE status IN ('AGUARDANDO_PAGAMENTO', 'EFETIVADA')",
        )
        == 1
    )
    with engine.connect() as conexao:
        status, versao = conexao.execute(
            text("SELECT status, versao FROM catalogo.veiculos WHERE id = :id"),
            {"id": veiculo.id},
        ).one()
    assert (status, versao) == ("RESERVADO", 2)


def test_indice_unico_parcial_e_a_segunda_barreira_sob_concorrencia(
    banco: BancoDeDados, engine: Engine
) -> None:
    """Mesmo contornando a reserva, duas vendas ativas simultâneas: o índice barra uma."""
    veiculo = _cadastrar(banco)

    def inserir(i: int) -> Venda:
        venda = Venda.iniciar(
            veiculo_id=veiculo.id,
            comprador_id=f"cliente-{i}",
            preco_venda=veiculo.preco,
            veiculo=DescricaoVeiculo(marca="Honda", modelo="Civic", ano=2020, cor="Preto"),
            agora=AS_10H,
            ttl=TTL,
        )
        with banco.nova_sessao() as sessao:
            SqlVendaRepository(sessao).adicionar(venda)
            sessao.commit()
        return venda

    resultados = _em_paralelo(2, inserir)
    assert sum(isinstance(r, Venda) for r in resultados) == 1
    assert sum(isinstance(r, VendaAtivaDuplicadaError) for r in resultados) == 1
    assert _contar(engine, "SELECT count(*) FROM vendas.vendas") == 1
