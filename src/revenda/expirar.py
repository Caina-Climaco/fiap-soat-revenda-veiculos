"""Saneamento das reservas vencidas: `python -m revenda.expirar` (CronJob do Kubernetes).

Segunda linha de defesa da expiração preguiçosa (ADR-009). A garantia de correção continua
sendo a expiração aplicada pela própria API em cada escrita e leitura; este comando só
antecipa o cancelamento das reservas que ninguém consultou, para que relatórios que leem o
banco diretamente não vejam como `AGUARDANDO_PAGAMENTO` uma reserva já vencida.

Reutiliza o caso de uso `ExpirarReservasVencidas` (o mesmo das leituras da API): cada lote
é uma transação própria, com os mesmos UPDATEs condicionais, então o CronJob pode rodar ao
mesmo tempo que as requisições sem cancelar duas vezes nem travar o veículo (ADR-008).

Laço: cancela em lotes de `SANEAMENTO_LOTE` (padrão 100) até não sobrar reserva vencida ou
atingir o teto `SANEAMENTO_TETO` (padrão 1000) por execução; o que sobrar fica para a próxima
execução (a cada 10 min) ou para a própria API. Sai sempre com 0 quando o banco respondeu;
uma falha de conexão/consulta propaga a exceção e o Job registra a falha.

Mesmas variáveis de banco da API e do Job de migração (DATABASE_URL ou
DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from pydantic import Field
from sqlalchemy.orm import Session

from revenda.catalogo.application.adaptador_vendas import CatalogoAdapter
from revenda.catalogo.infrastructure.repositorio_sql import SqlVeiculoRepository
from revenda.shared.clock import RelogioSistema
from revenda.shared.config import DatabaseSettings
from revenda.shared.db import BancoDeDados, SqlUnidadeDeTrabalho, criar_engine
from revenda.shared.eventos import PublicadorEventosLog
from revenda.shared.logging import configurar_logs
from revenda.shared.paginacao import LIMITE_VARREDURA_EXPIRADAS
from revenda.vendas.application.casos_uso import ExpirarReservasVencidas
from revenda.vendas.application.portas import CatalogoPort
from revenda.vendas.infrastructure.repositorio_sql import SqlVendaRepository

_logger = logging.getLogger("revenda.expirar")

TETO_PADRAO = 1000


class SaneamentoSettings(DatabaseSettings):
    """Banco + parâmetros do laço; sem as variáveis de OIDC e do webhook (como a migração)."""

    saneamento_lote: int = Field(default=LIMITE_VARREDURA_EXPIRADAS, ge=1, le=1000)
    saneamento_teto: int = Field(default=TETO_PADRAO, ge=1)
    log_level: str = "INFO"


class Expirador(Protocol):
    def expirar_vencidas(self, limite: int) -> int:
        """Cancela até `limite` reservas vencidas numa transação e devolve quantas cancelou."""
        ...


@dataclass(frozen=True, slots=True)
class Resultado:
    canceladas: int
    lotes: int  # chamadas que cancelaram ao menos uma reserva
    teto_atingido: bool  # True: pode haver sobras (ficam para a próxima execução)


def executar(expirador: Expirador, *, lote: int, teto: int) -> Resultado:
    """Laço de saneamento: lotes de até `lote`, no máximo `teto` cancelamentos no total."""
    if lote < 1 or teto < 1:
        raise ValueError("lote e teto devem ser positivos")
    canceladas = lotes = 0
    while canceladas < teto:
        quantidade = expirador.expirar_vencidas(min(lote, teto - canceladas))
        if quantidade == 0:
            break
        canceladas += quantidade
        lotes += 1
        _logger.info(
            "lote de reservas vencidas cancelado",
            extra={"campos": {"lote": lotes, "canceladas_no_lote": quantidade}},
        )
    resultado = Resultado(canceladas=canceladas, lotes=lotes, teto_atingido=canceladas >= teto)
    _logger.log(
        logging.WARNING if resultado.teto_atingido else logging.INFO,
        "saneamento de reservas vencidas concluído",
        extra={
            "campos": {
                "canceladas": resultado.canceladas,
                "lotes": resultado.lotes,
                "teto": teto,
                "teto_atingido": resultado.teto_atingido,
            }
        },
    )
    return resultado


def expirador_sql(banco: BancoDeDados) -> tuple[ExpirarReservasVencidas, Session]:
    """Monta o caso de uso sobre uma sessão nova, como `Composicao._expirador` faz na API."""
    sessao = banco.nova_sessao()
    uow = SqlUnidadeDeTrabalho(sessao, PublicadorEventosLog())
    catalogo: CatalogoPort = CatalogoAdapter(SqlVeiculoRepository(sessao), uow)
    expirador = ExpirarReservasVencidas(SqlVendaRepository(sessao), catalogo, uow, RelogioSistema())
    return expirador, sessao


def main() -> int:
    settings = SaneamentoSettings()  # valores vêm do ambiente
    configurar_logs(settings.log_level)
    engine = criar_engine(settings.url_banco(), pool_size=1, max_overflow=0)
    try:
        expirador, sessao = expirador_sql(BancoDeDados(engine))
        try:
            executar(expirador, lote=settings.saneamento_lote, teto=settings.saneamento_teto)
        finally:
            sessao.close()
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":  # pragma: no cover - ponto de entrada do CronJob
    raise SystemExit(main())
