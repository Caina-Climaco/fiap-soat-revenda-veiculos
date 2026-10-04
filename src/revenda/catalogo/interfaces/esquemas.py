"""Esquemas HTTP do Catálogo (docs/05-api.md, seção 3.1)."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, model_validator

from revenda.catalogo.domain.veiculo import (
    ANO_MINIMO,
    TAMANHO_MAXIMO_COR,
    TAMANHO_MAXIMO_MARCA,
    TAMANHO_MAXIMO_MODELO,
    StatusVeiculo,
)
from revenda.shared.http import DataHoraUtc, Dinheiro, ModeloRequisicao, ModeloResposta

Marca = Annotated[str, Field(min_length=1, max_length=TAMANHO_MAXIMO_MARCA, examples=["Fiat"])]
Modelo = Annotated[
    str, Field(min_length=1, max_length=TAMANHO_MAXIMO_MODELO, examples=["Argo Drive 1.3"])
]
Ano = Annotated[
    int,
    Field(
        ge=ANO_MINIMO,
        description="De 1950 até o ano corrente + 1 (o limite superior é validado no domínio).",
        examples=[2023],
    ),
]
Cor = Annotated[str, Field(min_length=1, max_length=TAMANHO_MAXIMO_COR, examples=["Vermelho"])]
Preco = Annotated[
    Decimal,
    Field(
        gt=0,
        max_digits=12,
        decimal_places=2,
        description='String decimal com até 2 casas (BRL), ex.: "79900.00".',
        examples=["79900.00"],
    ),
]


class VeiculoCriacao(ModeloRequisicao):
    marca: Marca
    modelo: Modelo
    ano: Ano
    cor: Cor
    preco: Preco


class VeiculoEdicao(ModeloRequisicao):
    """Edição parcial (merge): só os campos enviados mudam; ao menos um é obrigatório."""

    marca: Marca | None = None
    modelo: Modelo | None = None
    ano: Ano | None = None
    cor: Cor | None = None
    preco: Preco | None = None

    @model_validator(mode="after")
    def _sem_nulos_explicitos(self) -> Self:
        nulos = sorted(c for c in self.model_fields_set if getattr(self, c) is None)
        if nulos:
            raise ValueError("campos não podem ser nulos: " + ", ".join(nulos))
        if not self.model_fields_set:
            raise ValueError("informe ao menos um campo para editar")
        return self


class VeiculoResposta(ModeloResposta):
    id: UUID
    marca: str
    modelo: str
    ano: int
    cor: str
    preco: Dinheiro
    status: StatusVeiculo
    versao: int
    criado_em: DataHoraUtc
    atualizado_em: DataHoraUtc


class PaginaVeiculos(ModeloResposta):
    itens: list[VeiculoResposta]
    total: int
    limite: int
    deslocamento: int
