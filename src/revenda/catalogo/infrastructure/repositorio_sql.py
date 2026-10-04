"""Repositório SQLAlchemy do agregado Veiculo."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from revenda.catalogo.domain.veiculo import StatusVeiculo, Transicao, Veiculo
from revenda.catalogo.infrastructure.tabelas import veiculos


class SqlVeiculoRepository:
    def __init__(self, sessao: Session) -> None:
        self._sessao = sessao

    def adicionar(self, veiculo: Veiculo) -> None:
        self._sessao.execute(insert(veiculos).values(**_para_linha(veiculo)))

    def obter(self, veiculo_id: UUID) -> Veiculo | None:
        linha = self._sessao.execute(select(veiculos).where(veiculos.c.id == veiculo_id))
        registro = linha.mappings().one_or_none()
        return None if registro is None else _para_dominio(registro)

    def salvar_edicao(self, veiculo: Veiculo, versao_lida: int) -> bool:
        valores = _para_linha(veiculo)
        for chave in ("id", "status", "criado_em"):
            valores.pop(chave)
        resultado = self._sessao.execute(
            update(veiculos)
            .where(
                veiculos.c.id == veiculo.id,
                veiculos.c.versao == versao_lida,
                veiculos.c.status == StatusVeiculo.A_VENDA.value,
            )
            .values(**valores)
        )
        return _linhas_afetadas(resultado) == 1

    def aplicar_transicao(
        self, veiculo_id: UUID, transicao: Transicao, agora: datetime
    ) -> Veiculo | None:
        # ADR-008: a pré-condição do domínio vai no WHERE. Em READ COMMITTED, uma transação
        # concorrente espera o lock da linha e reavalia o WHERE após o commit da primeira.
        resultado = self._sessao.execute(
            update(veiculos)
            .where(veiculos.c.id == veiculo_id, veiculos.c.status == transicao.origem.value)
            .values(
                status=transicao.destino.value,
                versao=veiculos.c.versao + 1,
                atualizado_em=agora,
            )
            .returning(*veiculos.c)
        )
        registro = resultado.mappings().one_or_none()
        return None if registro is None else _para_dominio(registro)

    def listar_por_status(
        self, status: StatusVeiculo, *, limite: int, deslocamento: int
    ) -> tuple[Sequence[Veiculo], int]:
        filtro = veiculos.c.status == status.value
        total = self._sessao.execute(
            select(func.count()).select_from(veiculos).where(filtro)
        ).scalar_one()
        linhas = self._sessao.execute(
            select(veiculos)
            .where(filtro)
            .order_by(veiculos.c.preco.asc(), veiculos.c.criado_em.asc(), veiculos.c.id.asc())
            .limit(limite)
            .offset(deslocamento)
        )
        return [_para_dominio(r) for r in linhas.mappings()], int(total)


def _linhas_afetadas(resultado: Any) -> int:
    return int(resultado.rowcount)


def _para_linha(veiculo: Veiculo) -> dict[str, Any]:
    return {
        "id": veiculo.id,
        "marca": veiculo.marca,
        "modelo": veiculo.modelo,
        "ano": veiculo.ano,
        "cor": veiculo.cor,
        "preco": veiculo.preco,
        "status": veiculo.status.value,
        "versao": veiculo.versao,
        "criado_em": veiculo.criado_em,
        "atualizado_em": veiculo.atualizado_em,
    }


def _para_dominio(registro: RowMapping) -> Veiculo:
    return Veiculo(
        id=registro["id"],
        marca=registro["marca"],
        modelo=registro["modelo"],
        ano=registro["ano"],
        cor=registro["cor"],
        preco=registro["preco"],
        status=StatusVeiculo(registro["status"]),
        versao=registro["versao"],
        criado_em=registro["criado_em"],
        atualizado_em=registro["atualizado_em"],
    )
