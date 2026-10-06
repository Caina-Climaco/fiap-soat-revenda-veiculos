"""Repositórios SQLAlchemy contra PostgreSQL real (ordenação, UPDATE condicional, índices)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apoio.cenario import AS_10H, TTL
from revenda.catalogo.domain.veiculo import StatusVeiculo, Transicao, Veiculo
from revenda.catalogo.infrastructure.repositorio_sql import SqlVeiculoRepository
from revenda.shared.db import BancoDeDados
from revenda.vendas.domain.erros import ConflitoConcorrenciaVendaError, VendaAtivaDuplicadaError
from revenda.vendas.domain.venda import (
    CodigoPagamento,
    DescricaoVeiculo,
    MotivoCancelamento,
    StatusVenda,
    Venda,
)
from revenda.vendas.infrastructure.repositorio_sql import SqlVendaRepository


@pytest.fixture
def sessao(banco: BancoDeDados) -> Iterator[Session]:
    with banco.nova_sessao() as sessao:
        yield sessao


def _veiculo(preco: str, *, minutos: int = 0, modelo: str = "Argo") -> Veiculo:
    return Veiculo.cadastrar(
        marca="Fiat",
        modelo=modelo,
        ano=2022,
        cor="Prata",
        preco=preco,
        agora=AS_10H + timedelta(minutes=minutos),
    )


def _venda(veiculo_id: UUID, *, comprador: str = "sub-1", minutos: int = 0) -> Venda:
    return Venda.iniciar(
        veiculo_id=veiculo_id,
        comprador_id=comprador,
        preco_venda=Decimal("72000.00"),
        veiculo=DescricaoVeiculo(marca="Fiat", modelo="Argo", ano=2022, cor="Prata"),
        agora=AS_10H + timedelta(minutes=minutos),
        ttl=TTL,
    )


# ---------------------------------------------------------------- veículos


def test_veiculo_ida_e_volta_preserva_decimal_e_utc(sessao: Session) -> None:
    repo = SqlVeiculoRepository(sessao)
    veiculo = _veiculo("54900.5")
    repo.adicionar(veiculo)
    sessao.commit()
    lido = repo.obter(veiculo.id)
    assert lido is not None
    assert lido.preco == Decimal("54900.50")
    assert str(lido.preco) == "54900.50"
    assert lido.criado_em == AS_10H
    assert lido.criado_em.utcoffset() == timedelta(0)
    assert repo.obter(_veiculo("1").id) is None


def test_listagem_ordena_por_preco_criado_em_e_id_com_paginacao(sessao: Session) -> None:
    repo = SqlVeiculoRepository(sessao)
    caro = _veiculo("150000.00", minutos=0, modelo="Compass")
    barato = _veiculo("45000.00", minutos=1, modelo="Mobi")
    empate_antigo = _veiculo("72000.00", minutos=2, modelo="Argo antigo")
    empate_novo = _veiculo("72000.00", minutos=3, modelo="Argo novo")
    for v in (caro, empate_novo, barato, empate_antigo):
        repo.adicionar(v)
    vendido = _veiculo("10.00", modelo="Vendido")
    vendido.status = StatusVeiculo.VENDIDO
    repo.adicionar(vendido)
    sessao.commit()

    itens, total = repo.listar_por_status(StatusVeiculo.A_VENDA, limite=10, deslocamento=0)
    assert total == 4
    assert [v.modelo for v in itens] == ["Mobi", "Argo antigo", "Argo novo", "Compass"]
    pagina, total = repo.listar_por_status(StatusVeiculo.A_VENDA, limite=2, deslocamento=2)
    assert [v.modelo for v in pagina] == ["Argo novo", "Compass"]
    assert total == 4
    vendidos, total = repo.listar_por_status(StatusVeiculo.VENDIDO, limite=10, deslocamento=0)
    assert ([v.modelo for v in vendidos], total) == (["Vendido"], 1)


def test_update_condicional_so_afeta_o_status_de_origem(sessao: Session) -> None:
    repo = SqlVeiculoRepository(sessao)
    veiculo = _veiculo("72000.00")
    repo.adicionar(veiculo)
    depois = AS_10H + timedelta(minutes=5)

    reservado = repo.aplicar_transicao(veiculo.id, Transicao.RESERVAR, depois)
    assert reservado is not None
    assert (reservado.status, reservado.versao, reservado.atualizado_em) == (
        StatusVeiculo.RESERVADO,
        2,
        depois,
    )
    # Segunda reserva: 0 linhas afetadas (é o que decide a disputa entre compradores).
    assert repo.aplicar_transicao(veiculo.id, Transicao.RESERVAR, depois) is None
    assert repo.aplicar_transicao(_veiculo("1").id, Transicao.RESERVAR, depois) is None
    vendido = repo.aplicar_transicao(veiculo.id, Transicao.MARCAR_VENDIDO, depois)
    assert vendido is not None
    assert vendido.status is StatusVeiculo.VENDIDO
    assert repo.aplicar_transicao(veiculo.id, Transicao.LIBERAR, depois) is None


def test_salvar_edicao_exige_versao_lida_e_veiculo_a_venda(sessao: Session) -> None:
    repo = SqlVeiculoRepository(sessao)
    veiculo = _veiculo("72000.00")
    repo.adicionar(veiculo)
    sessao.commit()

    editado = repo.obter(veiculo.id)
    assert editado is not None
    editado.editar(agora=AS_10H, preco=Decimal("70000.00"))
    assert repo.salvar_edicao(editado, versao_lida=1) is True
    # Releitura com versão desatualizada: outra operação já mudou o veículo.
    assert repo.salvar_edicao(editado, versao_lida=1) is False

    repo.aplicar_transicao(veiculo.id, Transicao.RESERVAR, AS_10H)
    atual = repo.obter(veiculo.id)
    assert atual is not None
    atual.status = StatusVeiculo.A_VENDA  # simula leitura anterior à reserva
    assert repo.salvar_edicao(atual, versao_lida=atual.versao) is False
    sessao.commit()
    final = repo.obter(veiculo.id)
    assert final is not None
    assert (final.preco, final.status) == (Decimal("70000.00"), StatusVeiculo.RESERVADO)


def test_banco_recusa_veiculo_invalido_mesmo_se_o_dominio_falhar(sessao: Session) -> None:
    with pytest.raises(IntegrityError, match="ck_veiculos_preco_positivo"):
        sessao.execute(
            text(
                "INSERT INTO catalogo.veiculos (id, marca, modelo, ano, cor, preco) "
                "VALUES (gen_random_uuid(), 'Fiat', 'Uno', 2000, 'Azul', 0)"
            )
        )


# ---------------------------------------------------------------- vendas


def test_venda_ida_e_volta_e_consultas(sessao: Session) -> None:
    repo = SqlVendaRepository(sessao)
    veiculo_id = _veiculo("1").id
    venda = _venda(veiculo_id)
    repo.adicionar(venda)
    sessao.commit()

    for lida in (
        repo.obter(venda.id),
        repo.obter(venda.id, para_atualizar=True),
        repo.obter_por_codigo(str(venda.codigo_pagamento)),
        repo.obter_ativa_do_veiculo(veiculo_id, para_atualizar=True),
    ):
        assert lida is not None
        assert lida.id == venda.id
        assert lida.codigo_pagamento == venda.codigo_pagamento
        assert lida.veiculo == venda.veiculo
        assert lida.preco_venda == Decimal("72000.00")
        assert lida.expira_em == AS_10H + TTL
    assert repo.obter_por_codigo("PAG-000000000000") is None
    sessao.rollback()


def test_indice_unico_parcial_barra_segunda_venda_ativa_sem_abortar_transacao(
    sessao: Session,
) -> None:
    repo = SqlVendaRepository(sessao)
    veiculo_id = _veiculo("1").id
    primeira = _venda(veiculo_id)
    repo.adicionar(primeira)
    with pytest.raises(VendaAtivaDuplicadaError):
        repo.adicionar(_venda(veiculo_id, comprador="sub-2"))
    # O savepoint preservou a transação: a primeira venda continua gravável.
    sessao.commit()
    assert repo.obter(primeira.id) is not None

    # Venda cancelada não ocupa o veículo: uma nova compra é aceita.
    primeira.cancelar(MotivoCancelamento.DESISTENCIA_COMPRADOR, AS_10H)
    repo.salvar(primeira)
    repo.adicionar(_venda(veiculo_id, comprador="sub-3"))
    sessao.commit()


def test_codigo_de_pagamento_duplicado_nao_e_confundido_com_venda_ativa(
    sessao: Session,
) -> None:
    repo = SqlVendaRepository(sessao)
    venda = _venda(_veiculo("1").id)
    repo.adicionar(venda)
    clone = _venda(_veiculo("1").id)
    clone.codigo_pagamento = CodigoPagamento(str(venda.codigo_pagamento))
    with pytest.raises(IntegrityError, match="uq_vendas_codigo_pagamento"):
        repo.adicionar(clone)
    sessao.rollback()


def test_salvar_so_transiciona_venda_aguardando_pagamento(sessao: Session) -> None:
    repo = SqlVendaRepository(sessao)
    venda = _venda(_veiculo("1").id)
    repo.adicionar(venda)
    venda.efetivar(AS_10H + timedelta(minutes=1))
    repo.salvar(venda)
    lida = repo.obter(venda.id)
    assert lida is not None
    assert lida.status is StatusVenda.EFETIVADA
    assert lida.efetivada_em == AS_10H + timedelta(minutes=1)
    with pytest.raises(ConflitoConcorrenciaVendaError):
        repo.salvar(venda)
    sessao.rollback()


def test_banco_recusa_estado_incoerente_da_venda(sessao: Session) -> None:
    repo = SqlVendaRepository(sessao)
    venda = _venda(_veiculo("1").id)
    repo.adicionar(venda)
    with pytest.raises(IntegrityError, match="ck_vendas_cancelada_coerente"):
        sessao.execute(
            text("UPDATE vendas.vendas SET status = 'CANCELADA' WHERE id = :id"), {"id": venda.id}
        )
    sessao.rollback()


def test_listar_expiradas_e_listagens(sessao: Session, banco: BancoDeDados) -> None:
    repo = SqlVendaRepository(sessao)
    antiga = _venda(_veiculo("1").id, comprador="a", minutos=0)
    recente = _venda(_veiculo("1").id, comprador="a", minutos=20)
    de_outro = _venda(_veiculo("1").id, comprador="b", minutos=10)
    for v in (antiga, recente, de_outro):
        repo.adicionar(v)
    de_outro.cancelar(MotivoCancelamento.PAGAMENTO_RECUSADO, AS_10H + timedelta(minutes=11))
    repo.salvar(de_outro)
    sessao.commit()

    agora = AS_10H + timedelta(minutes=45)  # antiga venceu às 10:30; recente vence às 10:50
    assert [v.id for v in repo.listar_expiradas(agora, 10)] == [antiga.id]
    assert repo.listar_expiradas(agora, 0) == []
    sessao.rollback()  # solta os locks da varredura acima

    # SKIP LOCKED: outra transação que já travou a venda vencida não bloqueia a varredura.
    with banco.nova_sessao() as outra:
        assert len(SqlVendaRepository(outra).listar_expiradas(agora, 10)) == 1
        assert repo.listar_expiradas(agora, 10) == []
        outra.rollback()
    sessao.rollback()

    itens, total = repo.listar(comprador_id="a", status=None, limite=10, deslocamento=0)
    assert ([v.id for v in itens], total) == ([recente.id, antiga.id], 2)
    itens, total = repo.listar(
        comprador_id=None, status=StatusVenda.CANCELADA, limite=10, deslocamento=0
    )
    assert ([v.id for v in itens], total) == ([de_outro.id], 1)
    itens, total = repo.listar(comprador_id=None, status=None, limite=1, deslocamento=1)
    assert ([v.id for v in itens], total) == ([de_outro.id], 3)
