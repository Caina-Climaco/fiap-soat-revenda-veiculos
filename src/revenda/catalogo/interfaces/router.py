"""Rotas HTTP do Catálogo: /api/v1/veiculos (docs/05-api.md, seções 4.3 a 4.7)."""

# Sem `from __future__ import annotations` neste módulo: as dependências usam aliases
# `Annotated[..., Depends(...)]` locais à fábrica, e o FastAPI só os resolve se as
# anotações forem avaliadas na definição da função (com o escopo local).

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, Response, status

from revenda.catalogo.application.casos_uso import (
    CasosUsoCatalogo,
    DadosCadastro,
    DadosEdicao,
    FabricaCasosUsoCatalogo,
)
from revenda.catalogo.domain.erros import (
    ConflitoConcorrenciaError,
    DadosVeiculoInvalidosError,
    TransicaoInvalidaError,
    VeiculoNaoEditavelError,
    VeiculoNaoEncontradoError,
)
from revenda.catalogo.interfaces.esquemas import (
    PaginaVeiculos,
    VeiculoCriacao,
    VeiculoEdicao,
    VeiculoResposta,
)
from revenda.shared.auth import PAPEL_GESTOR, Autenticacao, Principal
from revenda.shared.errors import VALIDACAO, TipoProblema
from revenda.shared.http import ParametrosPaginacao, paginacao, respostas_problema

PROBLEMAS_CATALOGO: dict[type[Exception], TipoProblema] = {
    DadosVeiculoInvalidosError: VALIDACAO,
    VeiculoNaoEncontradoError: TipoProblema(
        "veiculo-nao-encontrado", "Veículo não encontrado", 404
    ),
    VeiculoNaoEditavelError: TipoProblema("veiculo-nao-editavel", "Veículo não editável", 409),
    TransicaoInvalidaError: TipoProblema("transicao-invalida", "Transição de estado inválida", 409),
    ConflitoConcorrenciaError: TipoProblema(
        "conflito-concorrencia", "Conflito de atualização concorrente", 409
    ),
}

IdVeiculo = Annotated[UUID, Path(description="Identificador do veículo (UUID).")]


def criar_router_veiculos(auth: Autenticacao, casos_uso: FabricaCasosUsoCatalogo) -> APIRouter:
    router = APIRouter(prefix="/veiculos", tags=["Veículos"])
    Gestor = Annotated[Principal, Depends(auth.exigir_papel(PAPEL_GESTOR))]
    CasosUso = Annotated[CasosUsoCatalogo, Depends(casos_uso)]
    Paginacao = Annotated[ParametrosPaginacao, Depends(paginacao)]

    # As rotas literais (/a-venda, /vendidos) vêm antes de /{veiculo_id}.
    @router.get(
        "/a-venda",
        summary="Listar veículos à venda (preço ascendente)",
        description=(
            "Público. Veículos com status A_VENDA, do mais barato ao mais caro (desempate: "
            "criado_em e id). Antes da consulta, reservas vencidas são canceladas e seus "
            "veículos voltam à vitrine (expiração preguiçosa)."
        ),
        response_model=PaginaVeiculos,
        responses=respostas_problema(422),
    )
    def listar_a_venda(uc: CasosUso, pag: Paginacao) -> PaginaVeiculos:
        pagina = uc.listar_a_venda.executar(limite=pag.limite, deslocamento=pag.deslocamento)
        return PaginaVeiculos.model_validate(pagina)

    @router.get(
        "/vendidos",
        summary="Listar veículos vendidos (preço ascendente)",
        description="Público. Veículos com status VENDIDO, do mais barato ao mais caro.",
        response_model=PaginaVeiculos,
        responses=respostas_problema(422),
    )
    def listar_vendidos(uc: CasosUso, pag: Paginacao) -> PaginaVeiculos:
        pagina = uc.listar_vendidos.executar(limite=pag.limite, deslocamento=pag.deslocamento)
        return PaginaVeiculos.model_validate(pagina)

    @router.post(
        "",
        status_code=status.HTTP_201_CREATED,
        summary="Cadastrar veículo",
        description="Papel **gestor**. O veículo nasce à venda (A_VENDA) com versao 1.",
        response_model=VeiculoResposta,
        responses=respostas_problema(400, 401, 403, 422),
    )
    def cadastrar(
        _gestor: Gestor,
        uc: CasosUso,
        corpo: VeiculoCriacao,
        request: Request,
        response: Response,
    ) -> VeiculoResposta:
        veiculo = uc.cadastrar.executar(DadosCadastro(**corpo.model_dump()))
        response.headers["Location"] = f"{request.url.path.rstrip('/')}/{veiculo.id}"
        return VeiculoResposta.model_validate(veiculo)

    @router.patch(
        "/{veiculo_id}",
        summary="Editar veículo",
        description=(
            "Papel **gestor**. Atualização parcial de marca, modelo, ano, cor e/ou preço; "
            "só com o veículo à venda (reservado ou vendido → 409)."
        ),
        response_model=VeiculoResposta,
        responses=respostas_problema(400, 401, 403, 404, 409, 422),
    )
    def editar(
        _gestor: Gestor, uc: CasosUso, veiculo_id: IdVeiculo, corpo: VeiculoEdicao
    ) -> VeiculoResposta:
        dados = DadosEdicao(**corpo.model_dump(exclude_unset=True))
        return VeiculoResposta.model_validate(uc.editar.executar(veiculo_id, dados))

    @router.get(
        "/{veiculo_id}",
        summary="Consultar veículo",
        description="Público. Retorna o veículo em qualquer status.",
        response_model=VeiculoResposta,
        responses=respostas_problema(404, 422),
    )
    def obter(uc: CasosUso, veiculo_id: IdVeiculo) -> VeiculoResposta:
        return VeiculoResposta.model_validate(uc.obter.executar(veiculo_id))

    return router
