"""Agregado Veiculo (contexto Catálogo) — docs/02-modelagem-ddd.md, seção 2.5.1."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, fields
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum, StrEnum
from uuid import UUID

from revenda.catalogo.domain.erros import (
    DadosVeiculoInvalidosError,
    TransicaoInvalidaError,
    VeiculoNaoEditavelError,
)
from revenda.catalogo.domain.eventos import (
    EventoCatalogo,
    VeiculoCadastrado,
    VeiculoEditado,
    VeiculoLiberado,
    VeiculoReservado,
    VeiculoVendido,
)

ANO_MINIMO = 1950
TAMANHO_MAXIMO_MARCA = 60
TAMANHO_MAXIMO_MODELO = 60
TAMANHO_MAXIMO_COR = 30
PRECO_MAXIMO = Decimal("9999999999.99")  # limite de NUMERIC(12,2)
_CENTAVOS = Decimal("0.01")


class StatusVeiculo(StrEnum):
    A_VENDA = "A_VENDA"
    RESERVADO = "RESERVADO"
    VENDIDO = "VENDIDO"


class Transicao(Enum):
    """Transições de status permitidas — fonte única da regra.

    O repositório aplica a mesma pré-condição no UPDATE condicional (ADR-008) lendo
    `origem`/`destino` daqui, em vez de repetir literais no SQL.
    """

    RESERVAR = (StatusVeiculo.A_VENDA, StatusVeiculo.RESERVADO)
    LIBERAR = (StatusVeiculo.RESERVADO, StatusVeiculo.A_VENDA)
    MARCAR_VENDIDO = (StatusVeiculo.RESERVADO, StatusVeiculo.VENDIDO)

    @property
    def origem(self) -> StatusVeiculo:
        return self.value[0]

    @property
    def destino(self) -> StatusVeiculo:
        return self.value[1]

    def evento(self, veiculo_id: UUID, agora: datetime) -> EventoCatalogo:
        match self:
            case Transicao.RESERVAR:
                return VeiculoReservado(veiculo_id=veiculo_id, ocorrido_em=agora)
            case Transicao.LIBERAR:
                return VeiculoLiberado(veiculo_id=veiculo_id, ocorrido_em=agora)
            case Transicao.MARCAR_VENDIDO:
                return VeiculoVendido(veiculo_id=veiculo_id, ocorrido_em=agora)


@dataclass(frozen=True, slots=True)
class DadosVeiculo:
    """Campos editáveis já validados e normalizados (None = não informado)."""

    marca: str | None = None
    modelo: str | None = None
    ano: int | None = None
    cor: str | None = None
    preco: Decimal | None = None

    def informados(self) -> dict[str, object]:
        return {
            f.name: getattr(self, f.name) for f in fields(self) if getattr(self, f.name) is not None
        }


@dataclass(eq=False)
class Veiculo:
    id: UUID
    marca: str
    modelo: str
    ano: int
    cor: str
    preco: Decimal
    status: StatusVeiculo
    versao: int
    criado_em: datetime
    atualizado_em: datetime
    _eventos: list[EventoCatalogo] = field(default_factory=list, repr=False)

    @classmethod
    def cadastrar(
        cls,
        *,
        marca: str,
        modelo: str,
        ano: int,
        cor: str,
        preco: Decimal | str | int,
        agora: datetime,
        id_: UUID | None = None,
    ) -> Veiculo:
        dados = validar_dados(
            marca=marca, modelo=modelo, ano=ano, cor=cor, preco=preco, ano_corrente=agora.year
        )
        if (
            dados.marca is None
            or dados.modelo is None
            or dados.ano is None
            or dados.cor is None
            or dados.preco is None
        ):
            ausentes = sorted({"marca", "modelo", "ano", "cor", "preco"} - set(dados.informados()))
            raise DadosVeiculoInvalidosError([(c, "campo obrigatório") for c in ausentes])
        veiculo = cls(
            id=id_ or uuid.uuid4(),
            marca=dados.marca,
            modelo=dados.modelo,
            ano=dados.ano,
            cor=dados.cor,
            preco=dados.preco,
            status=StatusVeiculo.A_VENDA,
            versao=1,
            criado_em=agora,
            atualizado_em=agora,
        )
        veiculo._eventos.append(
            VeiculoCadastrado(veiculo_id=veiculo.id, preco=veiculo.preco, ocorrido_em=agora)
        )
        return veiculo

    def editar(
        self,
        *,
        agora: datetime,
        marca: str | None = None,
        modelo: str | None = None,
        ano: int | None = None,
        cor: str | None = None,
        preco: Decimal | str | int | None = None,
    ) -> None:
        """Edição parcial (merge). Só com o veículo à venda (RN-02)."""
        if self.status is not StatusVeiculo.A_VENDA:
            raise VeiculoNaoEditavelError(self.id, self.status)
        dados = validar_dados(
            marca=marca, modelo=modelo, ano=ano, cor=cor, preco=preco, ano_corrente=agora.year
        )
        alterados = dados.informados()
        if not alterados:
            raise DadosVeiculoInvalidosError([("corpo", "informe ao menos um campo para editar")])
        for nome, valor in alterados.items():
            setattr(self, nome, valor)
        self.versao += 1
        self.atualizado_em = agora
        self._eventos.append(
            VeiculoEditado(
                veiculo_id=self.id,
                versao=self.versao,
                campos=",".join(sorted(alterados)),
                ocorrido_em=agora,
            )
        )

    def reservar(self, agora: datetime) -> None:
        self.aplicar(Transicao.RESERVAR, agora)

    def liberar(self, agora: datetime) -> None:
        self.aplicar(Transicao.LIBERAR, agora)

    def marcar_vendido(self, agora: datetime) -> None:
        self.aplicar(Transicao.MARCAR_VENDIDO, agora)

    def aplicar(self, transicao: Transicao, agora: datetime) -> None:
        if self.status is not transicao.origem:
            raise TransicaoInvalidaError(self.id, self.status, transicao.destino)
        self.status = transicao.destino
        self.versao += 1
        self.atualizado_em = agora
        self._eventos.append(transicao.evento(self.id, agora))

    def coletar_eventos(self) -> list[EventoCatalogo]:
        eventos, self._eventos = self._eventos, []
        return eventos


# ---------------------------------------------------------------- validação (RN-15)


def validar_dados(
    *,
    ano_corrente: int,
    marca: object = None,
    modelo: object = None,
    ano: object = None,
    cor: object = None,
    preco: object = None,
) -> DadosVeiculo:
    """Valida e normaliza os campos informados (None = ausente), acumulando todos os erros."""
    erros: list[tuple[str, str]] = []

    def texto(nome: str, valor: object, maximo: int) -> str | None:
        if valor is None:
            return None
        if not isinstance(valor, str):
            erros.append((nome, "deve ser texto"))
            return None
        limpo = valor.strip()
        if not limpo:
            erros.append((nome, "não pode ser vazio"))
        elif len(limpo) > maximo:
            erros.append((nome, f"deve ter no máximo {maximo} caracteres"))
        else:
            return limpo
        return None

    dados = DadosVeiculo(
        marca=texto("marca", marca, TAMANHO_MAXIMO_MARCA),
        modelo=texto("modelo", modelo, TAMANHO_MAXIMO_MODELO),
        ano=_validar_ano(ano, ano_corrente, erros),
        cor=texto("cor", cor, TAMANHO_MAXIMO_COR),
        preco=_validar_preco(preco, erros),
    )
    if erros:
        raise DadosVeiculoInvalidosError(erros)
    return dados


def _validar_ano(valor: object, ano_corrente: int, erros: list[tuple[str, str]]) -> int | None:
    if valor is None:
        return None
    if isinstance(valor, bool) or not isinstance(valor, int):
        erros.append(("ano", "deve ser um número inteiro"))
        return None
    if not ANO_MINIMO <= valor <= ano_corrente + 1:
        erros.append(("ano", f"deve estar entre {ANO_MINIMO} e {ano_corrente + 1}"))
        return None
    return valor


def _validar_preco(valor: object, erros: list[tuple[str, str]]) -> Decimal | None:
    if valor is None:
        return None
    try:
        if isinstance(valor, bool) or not isinstance(valor, Decimal | str | int):
            raise InvalidOperation
        preco = Decimal(valor)
        if not preco.is_finite():
            raise InvalidOperation
    except InvalidOperation:
        erros.append(("preco", "deve ser um valor decimal"))
        return None
    if preco <= 0:
        erros.append(("preco", "deve ser maior que zero"))
        return None
    if preco != preco.quantize(_CENTAVOS):
        erros.append(("preco", "deve ter no máximo 2 casas decimais"))
        return None
    preco = preco.quantize(_CENTAVOS)
    if preco > PRECO_MAXIMO:
        erros.append(("preco", f"deve ser no máximo {PRECO_MAXIMO}"))
        return None
    return preco
