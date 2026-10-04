"""Repositório SQLAlchemy do agregado Venda."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, insert, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from revenda.vendas.domain.erros import ConflitoConcorrenciaVendaError, VendaAtivaDuplicadaError
from revenda.vendas.domain.venda import (
    CodigoPagamento,
    DescricaoVeiculo,
    MotivoCancelamento,
    StatusVenda,
    Venda,
)
from revenda.vendas.infrastructure.tabelas import INDICE_VENDA_ATIVA, vendas

_ATIVAS = (StatusVenda.AGUARDANDO_PAGAMENTO.value, StatusVenda.EFETIVADA.value)


class SqlVendaRepository:
    def __init__(self, sessao: Session) -> None:
        self._sessao = sessao

    def adicionar(self, venda: Venda) -> None:
        try:
            # Savepoint: a violação do índice não pode abortar a transação inteira, para
            # que o chamador ainda consiga traduzir o erro e desfazer de forma limpa.
            with self._sessao.begin_nested():
                self._sessao.execute(insert(vendas).values(**_para_linha(venda)))
        except IntegrityError as exc:
            if _constraint_violada(exc) == INDICE_VENDA_ATIVA:
                raise VendaAtivaDuplicadaError(venda.veiculo_id) from exc
            raise

    def salvar(self, venda: Venda) -> None:
        resultado = self._sessao.execute(
            update(vendas)
            .where(
                vendas.c.id == venda.id,
                vendas.c.status == StatusVenda.AGUARDANDO_PAGAMENTO.value,
            )
            .values(
                status=venda.status.value,
                efetivada_em=venda.efetivada_em,
                cancelada_em=venda.cancelada_em,
                motivo_cancelamento=(
                    venda.motivo_cancelamento.value if venda.motivo_cancelamento else None
                ),
            )
        )
        if _linhas_afetadas(resultado) != 1:
            raise ConflitoConcorrenciaVendaError(venda.id)

    def obter(self, venda_id: UUID, *, para_atualizar: bool = False) -> Venda | None:
        return self._um(select(vendas).where(vendas.c.id == venda_id), para_atualizar)

    def obter_por_codigo(
        self, codigo_pagamento: str, *, para_atualizar: bool = False
    ) -> Venda | None:
        consulta = select(vendas).where(vendas.c.codigo_pagamento == codigo_pagamento)
        return self._um(consulta, para_atualizar)

    def obter_ativa_do_veiculo(
        self, veiculo_id: UUID, *, para_atualizar: bool = False
    ) -> Venda | None:
        consulta = select(vendas).where(
            vendas.c.veiculo_id == veiculo_id, vendas.c.status.in_(_ATIVAS)
        )
        return self._um(consulta, para_atualizar)

    def listar_expiradas(self, agora: datetime, limite: int) -> Sequence[Venda]:
        # SKIP LOCKED: réplicas que varrem ao mesmo tempo dividem o trabalho em vez de
        # esperarem umas pelas outras (e pelas compras/webhooks em andamento).
        linhas = self._sessao.execute(
            select(vendas)
            .where(
                vendas.c.status == StatusVenda.AGUARDANDO_PAGAMENTO.value,
                vendas.c.expira_em <= agora,
            )
            .order_by(vendas.c.expira_em)
            .limit(limite)
            .with_for_update(skip_locked=True)
        )
        return [_para_dominio(r) for r in linhas.mappings()]

    def listar(
        self,
        *,
        comprador_id: str | None,
        status: StatusVenda | None,
        limite: int,
        deslocamento: int,
    ) -> tuple[Sequence[Venda], int]:
        filtros = []
        if comprador_id is not None:
            filtros.append(vendas.c.comprador_id == comprador_id)
        if status is not None:
            filtros.append(vendas.c.status == status.value)
        total = self._sessao.execute(
            select(func.count()).select_from(vendas).where(*filtros)
        ).scalar_one()
        linhas = self._sessao.execute(
            select(vendas)
            .where(*filtros)
            .order_by(vendas.c.criada_em.desc(), vendas.c.id.asc())
            .limit(limite)
            .offset(deslocamento)
        )
        return [_para_dominio(r) for r in linhas.mappings()], int(total)

    def _um(self, consulta: Select[Any], para_atualizar: bool) -> Venda | None:
        if para_atualizar:
            consulta = consulta.with_for_update()
        registro = self._sessao.execute(consulta).mappings().one_or_none()
        return None if registro is None else _para_dominio(registro)


def _constraint_violada(exc: IntegrityError) -> str | None:
    diag = getattr(exc.orig, "diag", None)
    nome = getattr(diag, "constraint_name", None)
    return nome if isinstance(nome, str) else None


def _linhas_afetadas(resultado: Any) -> int:
    return int(resultado.rowcount)


def _para_linha(venda: Venda) -> dict[str, Any]:
    return {
        "id": venda.id,
        "veiculo_id": venda.veiculo_id,
        "comprador_id": venda.comprador_id,
        "preco_venda": venda.preco_venda,
        "veiculo_marca": venda.veiculo.marca,
        "veiculo_modelo": venda.veiculo.modelo,
        "veiculo_ano": venda.veiculo.ano,
        "veiculo_cor": venda.veiculo.cor,
        "status": venda.status.value,
        "codigo_pagamento": str(venda.codigo_pagamento),
        "expira_em": venda.expira_em,
        "criada_em": venda.criada_em,
        "efetivada_em": venda.efetivada_em,
        "cancelada_em": venda.cancelada_em,
        "motivo_cancelamento": (
            venda.motivo_cancelamento.value if venda.motivo_cancelamento else None
        ),
    }


def _para_dominio(registro: RowMapping) -> Venda:
    motivo = registro["motivo_cancelamento"]
    return Venda(
        id=registro["id"],
        veiculo_id=registro["veiculo_id"],
        comprador_id=registro["comprador_id"],
        preco_venda=registro["preco_venda"],
        veiculo=DescricaoVeiculo(
            marca=registro["veiculo_marca"],
            modelo=registro["veiculo_modelo"],
            ano=registro["veiculo_ano"],
            cor=registro["veiculo_cor"],
        ),
        status=StatusVenda(registro["status"]),
        codigo_pagamento=CodigoPagamento(registro["codigo_pagamento"]),
        expira_em=registro["expira_em"],
        criada_em=registro["criada_em"],
        efetivada_em=registro["efetivada_em"],
        cancelada_em=registro["cancelada_em"],
        motivo_cancelamento=MotivoCancelamento(motivo) if motivo else None,
    )
