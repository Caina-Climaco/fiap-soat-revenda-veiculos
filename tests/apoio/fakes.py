"""Adaptadores em memória para os testes de unidade (sem banco, sem rede)."""

from __future__ import annotations

import copy
from collections.abc import Iterable, Sequence
from datetime import datetime
from uuid import UUID

from revenda.catalogo.domain.veiculo import StatusVeiculo, Transicao, Veiculo
from revenda.shared.eventos import EventoDominio
from revenda.vendas.domain.erros import ConflitoConcorrenciaVendaError, VendaAtivaDuplicadaError
from revenda.vendas.domain.venda import StatusVenda, Venda


def _armazenavel[T: (Veiculo, Venda)](agregado: T) -> T:
    """Cópia sem eventos pendentes: o banco guarda estado, não eventos."""
    copia = copy.deepcopy(agregado)
    copia._eventos = []
    return copia


class UowFalsa:
    def __init__(self) -> None:
        self.confirmacoes = 0
        self.pendentes: list[EventoDominio] = []
        self.publicados: list[EventoDominio] = []

    def registrar_eventos(self, eventos: Iterable[EventoDominio]) -> None:
        self.pendentes.extend(eventos)

    def confirmar(self) -> None:
        self.confirmacoes += 1
        self.publicados.extend(self.pendentes)
        self.pendentes.clear()

    @property
    def nomes_publicados(self) -> list[str]:
        return [e.nome for e in self.publicados]


class VeiculoRepoMemoria:
    """Guarda cópias, como um banco: alterar o objeto devolvido não altera o armazenado."""

    def __init__(self) -> None:
        self.dados: dict[UUID, Veiculo] = {}

    def adicionar(self, veiculo: Veiculo) -> None:
        self.dados[veiculo.id] = _armazenavel(veiculo)

    def obter(self, veiculo_id: UUID) -> Veiculo | None:
        veiculo = self.dados.get(veiculo_id)
        return copy.deepcopy(veiculo) if veiculo else None

    def salvar_edicao(self, veiculo: Veiculo, versao_lida: int) -> bool:
        atual = self.dados.get(veiculo.id)
        if (
            atual is None
            or atual.versao != versao_lida
            or atual.status is not StatusVeiculo.A_VENDA
        ):
            return False
        self.dados[veiculo.id] = _armazenavel(veiculo)
        return True

    def aplicar_transicao(
        self, veiculo_id: UUID, transicao: Transicao, agora: datetime
    ) -> Veiculo | None:
        atual = self.dados.get(veiculo_id)
        if atual is None or atual.status is not transicao.origem:
            return None
        atual.status = transicao.destino
        atual.versao += 1
        atual.atualizado_em = agora
        return copy.deepcopy(atual)

    def listar_por_status(
        self, status: StatusVeiculo, *, limite: int, deslocamento: int
    ) -> tuple[Sequence[Veiculo], int]:
        filtrados = sorted(
            (v for v in self.dados.values() if v.status is status),
            key=lambda v: (v.preco, v.criado_em, v.id),
        )
        return filtrados[deslocamento : deslocamento + limite], len(filtrados)


class VendaRepoMemoria:
    def __init__(self) -> None:
        self.dados: dict[UUID, Venda] = {}

    def adicionar(self, venda: Venda) -> None:
        if any(v.veiculo_id == venda.veiculo_id and v.status.ativa for v in self.dados.values()):
            raise VendaAtivaDuplicadaError(venda.veiculo_id)
        self.dados[venda.id] = _armazenavel(venda)

    def salvar(self, venda: Venda) -> None:
        atual = self.dados.get(venda.id)
        if atual is None or atual.status is not StatusVenda.AGUARDANDO_PAGAMENTO:
            raise ConflitoConcorrenciaVendaError(venda.id)
        self.dados[venda.id] = _armazenavel(venda)

    def obter(self, venda_id: UUID, *, para_atualizar: bool = False) -> Venda | None:
        venda = self.dados.get(venda_id)
        return copy.deepcopy(venda) if venda else None

    def obter_por_codigo(
        self, codigo_pagamento: str, *, para_atualizar: bool = False
    ) -> Venda | None:
        for venda in self.dados.values():
            if str(venda.codigo_pagamento) == codigo_pagamento:
                return copy.deepcopy(venda)
        return None

    def obter_ativa_do_veiculo(
        self, veiculo_id: UUID, *, para_atualizar: bool = False
    ) -> Venda | None:
        for venda in self.dados.values():
            if venda.veiculo_id == veiculo_id and venda.status.ativa:
                return copy.deepcopy(venda)
        return None

    def listar_expiradas(self, agora: datetime, limite: int) -> Sequence[Venda]:
        vencidas = sorted(
            (v for v in self.dados.values() if v.esta_expirada(agora)), key=lambda v: v.expira_em
        )
        return [copy.deepcopy(v) for v in vencidas[:limite]]

    def listar(
        self,
        *,
        comprador_id: str | None,
        status: StatusVenda | None,
        limite: int,
        deslocamento: int,
    ) -> tuple[Sequence[Venda], int]:
        filtradas = [
            v
            for v in self.dados.values()
            if (comprador_id is None or v.comprador_id == comprador_id)
            and (status is None or v.status is status)
        ]
        filtradas.sort(key=lambda v: (-v.criada_em.timestamp(), str(v.id)))
        return filtradas[deslocamento : deslocamento + limite], len(filtradas)
