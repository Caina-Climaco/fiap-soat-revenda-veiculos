"""Exceções do contexto Catálogo. Mensagens em português, sem dados pessoais."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from revenda.catalogo.domain.veiculo import StatusVeiculo


class CatalogoError(Exception):
    """Base das exceções de negócio do Catálogo."""


class DadosVeiculoInvalidosError(CatalogoError):
    """Campos fora das regras (RN-15). `erros` lista pares (campo, mensagem)."""

    def __init__(self, erros: Sequence[tuple[str, str]]) -> None:
        self.erros = list(erros)
        super().__init__("Um ou mais campos são inválidos.")


class VeiculoNaoEncontradoError(CatalogoError):
    def __init__(self, veiculo_id: UUID) -> None:
        self.veiculo_id = veiculo_id
        super().__init__(f"O veículo {veiculo_id} não existe.")


class VeiculoNaoEditavelError(CatalogoError):
    """Edição de veículo que não está à venda (RN-02)."""

    def __init__(self, veiculo_id: UUID, status: StatusVeiculo) -> None:
        self.veiculo_id = veiculo_id
        self.status = status
        super().__init__(
            f"O veículo {veiculo_id} não pode ser editado (status atual: {status.value}); "
            "só veículos à venda podem ser alterados."
        )


class TransicaoInvalidaError(CatalogoError):
    def __init__(self, veiculo_id: UUID, atual: StatusVeiculo, destino: StatusVeiculo) -> None:
        self.veiculo_id = veiculo_id
        self.atual = atual
        self.destino = destino
        super().__init__(
            f"O veículo {veiculo_id} não pode passar de {atual.value} para {destino.value}."
        )


class ConflitoConcorrenciaError(CatalogoError):
    """O veículo mudou entre a leitura e a gravação (controle otimista pela `versao`)."""

    def __init__(self, veiculo_id: UUID) -> None:
        self.veiculo_id = veiculo_id
        super().__init__(
            f"O veículo {veiculo_id} foi alterado por outra operação; consulte-o e tente de novo."
        )
