"""Exceções do contexto Vendas. Mensagens em português, sem dados pessoais."""

from __future__ import annotations

from uuid import UUID


class VendasError(Exception):
    """Base das exceções de negócio de Vendas."""


class VeiculoNaoEncontradoError(VendasError):
    def __init__(self, veiculo_id: UUID) -> None:
        self.veiculo_id = veiculo_id
        super().__init__(f"O veículo {veiculo_id} não existe.")


class VeiculoIndisponivelError(VendasError):
    def __init__(self, veiculo_id: UUID, status: str | None = None) -> None:
        self.veiculo_id = veiculo_id
        self.status = status
        complemento = f" (status atual: {status})" if status else ""
        super().__init__(f"O veículo {veiculo_id} não está à venda{complemento}.")


class CompraNaoPermitidaError(VendasError):
    """Gestor não compra pelo canal de clientes (RN-05)."""

    def __init__(self) -> None:
        super().__init__(
            "Usuários com o papel gestor não podem comprar veículos (segregação de funções)."
        )


class VendaNaoEncontradaError(VendasError):
    """Também usada quando a venda existe, mas é de outro comprador (RN-13)."""

    def __init__(self, venda_id: UUID) -> None:
        self.venda_id = venda_id
        super().__init__(f"A venda {venda_id} não existe.")


class PagamentoNaoEncontradoError(VendasError):
    def __init__(self, codigo_pagamento: str) -> None:
        self.codigo_pagamento = codigo_pagamento
        super().__init__(f"Nenhuma venda tem o código de pagamento {codigo_pagamento}.")


class TransicaoVendaInvalidaError(VendasError):
    def __init__(self, venda_id: UUID, atual: str, operacao: str) -> None:
        self.venda_id = venda_id
        self.atual = atual
        self.operacao = operacao
        super().__init__(f"Não é possível {operacao}: a venda {venda_id} está {atual}.")


class ReservaExpiradaError(VendasError):
    """Pagamento aprovado depois do prazo (RN-14): a venda já foi cancelada."""

    def __init__(self, venda_id: UUID) -> None:
        self.venda_id = venda_id
        super().__init__(
            f"A reserva da venda {venda_id} expirou antes da confirmação do pagamento; "
            "a venda foi cancelada (RESERVA_EXPIRADA) e o veículo liberado. "
            "O estorno é responsabilidade do gateway."
        )


class VendaAtivaDuplicadaError(VendasError):
    """Violação do índice único parcial: já existe venda ativa para o veículo (RN-03)."""

    def __init__(self, veiculo_id: UUID) -> None:
        self.veiculo_id = veiculo_id
        super().__init__(f"O veículo {veiculo_id} já tem uma venda em andamento ou efetivada.")


class ConflitoConcorrenciaVendaError(VendasError):
    def __init__(self, venda_id: UUID) -> None:
        self.venda_id = venda_id
        super().__init__(
            f"A venda {venda_id} foi alterada por outra operação; consulte-a e tente de novo."
        )


class InconsistenciaCatalogoError(VendasError):
    """O veículo não estava no status esperado pela venda (não deveria ocorrer)."""

    def __init__(self, veiculo_id: UUID, operacao: str) -> None:
        self.veiculo_id = veiculo_id
        super().__init__(
            f"Não foi possível {operacao} o veículo {veiculo_id}: o status no catálogo "
            "não corresponde ao da venda."
        )
