"""Rotas HTTP de Vendas: /api/v1/vendas e a ACL do webhook /api/v1/pagamentos/webhook."""

# Sem `from __future__ import annotations` neste módulo: as dependências usam aliases
# `Annotated[..., Depends(...)]` locais à fábrica, e o FastAPI só os resolve se as
# anotações forem avaliadas na definição da função (com o escopo local).

import hmac
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from fastapi.security import APIKeyHeader

from revenda.shared.auth import PAPEL_CLIENTE, PAPEL_GESTOR, Autenticacao, Principal
from revenda.shared.errors import ACESSO_NEGADO, TipoProblema, WebhookNaoAutorizadoError
from revenda.shared.http import ParametrosPaginacao, paginacao, respostas_problema
from revenda.vendas.application.casos_uso import (
    CasosUsoVendas,
    FabricaCasosUsoVendas,
    Solicitante,
)
from revenda.vendas.domain.erros import (
    CompraNaoPermitidaError,
    ConflitoConcorrenciaVendaError,
    InconsistenciaCatalogoError,
    PagamentoNaoEncontradoError,
    ReservaExpiradaError,
    TransicaoVendaInvalidaError,
    VeiculoIndisponivelError,
    VeiculoNaoEncontradoError,
    VendaNaoEncontradaError,
)
from revenda.vendas.domain.venda import StatusVenda
from revenda.vendas.interfaces.esquemas import (
    CompraRequisicao,
    NotificacaoPagamento,
    PaginaVendas,
    VendaGestorResposta,
    VendaResposta,
    para_resposta,
)

_INDISPONIVEL = TipoProblema("veiculo-indisponivel", "Veículo indisponível para compra", 409)
_TRANSICAO = TipoProblema("transicao-invalida", "Transição de estado inválida", 409)

PROBLEMAS_VENDAS: dict[type[Exception], TipoProblema] = {
    CompraNaoPermitidaError: ACESSO_NEGADO,
    VeiculoNaoEncontradoError: TipoProblema(
        "veiculo-nao-encontrado", "Veículo não encontrado", 404
    ),
    VeiculoIndisponivelError: _INDISPONIVEL,
    VendaNaoEncontradaError: TipoProblema("venda-nao-encontrada", "Venda não encontrada", 404),
    PagamentoNaoEncontradoError: TipoProblema(
        "pagamento-nao-encontrado", "Código de pagamento não encontrado", 404
    ),
    TransicaoVendaInvalidaError: _TRANSICAO,
    InconsistenciaCatalogoError: _TRANSICAO,
    ReservaExpiradaError: TipoProblema("reserva-expirada", "Reserva expirada", 409),
    ConflitoConcorrenciaVendaError: TipoProblema(
        "conflito-concorrencia", "Conflito de atualização concorrente", 409
    ),
}

IdVenda = Annotated[UUID, Path(description="Identificador da venda (UUID).")]
RespostaVenda = VendaGestorResposta | VendaResposta


def _solicitante(principal: Principal) -> Solicitante:
    return Solicitante(id=principal.sub, eh_gestor=principal.eh_gestor)


def criar_router_vendas(auth: Autenticacao, casos_uso: FabricaCasosUsoVendas) -> APIRouter:
    router = APIRouter(prefix="/vendas", tags=["Vendas"])
    Cliente = Annotated[Principal, Depends(auth.exigir_papel(PAPEL_CLIENTE))]
    Gestor = Annotated[Principal, Depends(auth.exigir_papel(PAPEL_GESTOR))]
    ClienteOuGestor = Annotated[Principal, Depends(auth.exigir_papel(PAPEL_CLIENTE, PAPEL_GESTOR))]
    CasosUso = Annotated[CasosUsoVendas, Depends(casos_uso)]
    Paginacao = Annotated[ParametrosPaginacao, Depends(paginacao)]

    @router.post(
        "",
        status_code=status.HTTP_201_CREATED,
        summary="Iniciar compra",
        description=(
            "Papel **cliente** (usuários com papel gestor recebem 403, mesmo que também sejam "
            "clientes). Reserva o veículo e cria a venda AGUARDANDO_PAGAMENTO com preço "
            "congelado, código de pagamento e prazo de expiração."
        ),
        response_model=VendaResposta,
        responses=respostas_problema(
            400,
            401,
            403,
            404,
            409,
            422,
            s404="Veículo inexistente",
            s409="Veículo reservado ou vendido",
        ),
    )
    def iniciar_compra(
        cliente: Cliente,
        uc: CasosUso,
        corpo: CompraRequisicao,
        request: Request,
        response: Response,
    ) -> VendaResposta:
        venda = uc.iniciar_compra.executar(corpo.veiculo_id, _solicitante(cliente))
        response.headers["Location"] = f"{request.url.path.rstrip('/')}/{venda.id}"
        return para_resposta(venda, visao_gestor=False)

    @router.get(
        "/minhas",
        summary="Minhas compras",
        description="Papel **cliente**. Vendas do usuário do token, da mais recente à mais antiga.",
        response_model=PaginaVendas,
        responses=respostas_problema(401, 403, 422),
    )
    def minhas(cliente: Cliente, uc: CasosUso, pag: Paginacao) -> PaginaVendas:
        pagina = uc.listar.do_comprador(
            cliente.sub, limite=pag.limite, deslocamento=pag.deslocamento
        )
        return PaginaVendas(
            itens=[para_resposta(v, visao_gestor=False) for v in pagina.itens],
            total=pagina.total,
            limite=pagina.limite,
            deslocamento=pagina.deslocamento,
        )

    @router.get(
        "",
        summary="Listar vendas (gestão)",
        description="Papel **gestor**. Todas as vendas, da mais recente à mais antiga.",
        response_model=PaginaVendas,
        responses=respostas_problema(401, 403, 422),
    )
    def listar(
        _gestor: Gestor,
        uc: CasosUso,
        pag: Paginacao,
        status_venda: Annotated[
            StatusVenda | None, Query(alias="status", description="Filtra pelo status.")
        ] = None,
    ) -> PaginaVendas:
        pagina = uc.listar.todas(
            status=status_venda, limite=pag.limite, deslocamento=pag.deslocamento
        )
        return PaginaVendas(
            itens=[para_resposta(v, visao_gestor=True) for v in pagina.itens],
            total=pagina.total,
            limite=pagina.limite,
            deslocamento=pagina.deslocamento,
        )

    @router.get(
        "/{venda_id}",
        summary="Consultar venda",
        description=(
            "Dono (cliente) ou **gestor**. Para um cliente que não é o dono a resposta é 404, "
            "para não revelar a existência da venda."
        ),
        response_model=RespostaVenda,
        responses=respostas_problema(401, 403, 404, 422),
    )
    def obter(principal: ClienteOuGestor, uc: CasosUso, venda_id: IdVenda) -> RespostaVenda:
        venda = uc.obter.executar(venda_id, _solicitante(principal))
        return para_resposta(venda, visao_gestor=principal.eh_gestor)

    @router.post(
        "/{venda_id}/cancelar",
        summary="Cancelar venda",
        description=(
            "Dono (cliente) ou **gestor**, só para vendas AGUARDANDO_PAGAMENTO. Motivo: "
            "DESISTENCIA_COMPRADOR (dono) ou CANCELADA_PELA_LOJA (gestor); RESERVA_EXPIRADA "
            "se o prazo já tiver vencido. O veículo volta à venda."
        ),
        response_model=RespostaVenda,
        responses=respostas_problema(401, 403, 404, 409, 422),
    )
    def cancelar(principal: ClienteOuGestor, uc: CasosUso, venda_id: IdVenda) -> RespostaVenda:
        venda = uc.cancelar.executar(venda_id, _solicitante(principal))
        return para_resposta(venda, visao_gestor=principal.eh_gestor)

    return router


def criar_router_pagamentos(segredo_webhook: str, casos_uso: FabricaCasosUsoVendas) -> APIRouter:
    """Camada anticorrupção do gateway: autentica e traduz o payload em comando de domínio."""
    router = APIRouter(prefix="/pagamentos", tags=["Pagamentos (gateway)"])
    esquema = APIKeyHeader(
        name="X-Webhook-Secret",
        scheme_name="webhook",
        description="Segredo compartilhado com o gateway de pagamento.",
        auto_error=False,
    )
    esperado = segredo_webhook.encode()

    def verificar_segredo(recebido: Annotated[str | None, Depends(esquema)]) -> None:
        # Comparação em tempo constante; ausente e incorreto respondem igual (RN-19).
        if not recebido or not hmac.compare_digest(recebido.encode(), esperado):
            raise WebhookNaoAutorizadoError("Segredo do webhook ausente ou inválido.")

    CasosUso = Annotated[CasosUsoVendas, Depends(casos_uso)]

    @router.post(
        "/webhook",
        summary="Notificação de pagamento (gateway)",
        description=(
            "Chamado pelo gateway com o header `X-Webhook-Secret`. APROVADO efetiva a venda e "
            "marca o veículo como vendido; RECUSADO cancela a venda e libera o veículo. "
            "Notificações repetidas são idempotentes; aprovação após a expiração cancela a "
            "venda e responde 409 (reserva-expirada)."
        ),
        response_model=VendaResposta,
        dependencies=[Depends(verificar_segredo)],
        responses=respostas_problema(
            400, 401, 404, 409, 422, s404="Código de pagamento desconhecido"
        ),
    )
    def webhook(uc: CasosUso, notificacao: NotificacaoPagamento) -> VendaResposta:
        venda = uc.processar_pagamento.executar(
            notificacao.codigo_pagamento, aprovado=notificacao.status == "APROVADO"
        )
        return para_resposta(venda, visao_gestor=False)

    return router
