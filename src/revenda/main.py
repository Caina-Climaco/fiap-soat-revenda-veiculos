"""App factory da revenda-api. Entrada do container: `uvicorn revenda.main:app`."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.openapi.utils import get_openapi

from revenda import __version__
from revenda.catalogo.interfaces.router import PROBLEMAS_CATALOGO, criar_router_veiculos
from revenda.composicao import Composicao, acoes_metricas_negocio
from revenda.shared.auth import Autenticacao, ProvedorJwks, ValidadorToken
from revenda.shared.clock import Clock, RelogioSistema
from revenda.shared.config import Settings
from revenda.shared.db import BancoDeDados, criar_engine
from revenda.shared.errors import registrar_problemas, registrar_tratadores_globais
from revenda.shared.eventos import PublicadorEventos, PublicadorEventosLog
from revenda.shared.http import Problema
from revenda.shared.logging import configurar_logs
from revenda.shared.metricas import Metricas, MetricasMiddleware, PublicadorEventosComMetricas
from revenda.shared.middleware import CorrelacaoMiddleware
from revenda.shared.saude import criar_router_saude
from revenda.vendas.interfaces.router import (
    PROBLEMAS_VENDAS,
    criar_router_pagamentos,
    criar_router_vendas,
)

PREFIXO_API = "/api/v1"

DESCRICAO = """
API de uma revenda de veículos: cadastro e edição de veículos, compra online por clientes
cadastrados, efetivação da compra por notificação do gateway de pagamento e listagens de
veículos à venda e vendidos, ordenadas por preço.

**Autenticação**: clique em *Authorize* e entre pelo Keycloak (realm `revenda`, Authorization
Code + PKCE). Novos clientes se cadastram pelo link *Register* da tela de login. O webhook do
gateway usa o header `X-Webhook-Secret`.

Erros seguem a RFC 9457 (`application/problem+json`).
"""

TAGS = [
    {"name": "Veículos", "description": "Catálogo: cadastro, edição e vitrine."},
    {"name": "Vendas", "description": "Compra, consulta e cancelamento."},
    {"name": "Pagamentos (gateway)", "description": "Notificação do gateway (webhook)."},
    {"name": "Saúde", "description": "Probes de liveness e readiness."},
]


def criar_app(
    settings: Settings | None = None,
    *,
    banco: BancoDeDados | None = None,
    validador: ValidadorToken | None = None,
    relogio: Clock | None = None,
    publicador: PublicadorEventos | None = None,
) -> FastAPI:
    """Monta a aplicação; os parâmetros opcionais permitem substituir adaptadores nos testes."""
    settings = settings or Settings()  # valores vêm do ambiente
    configurar_logs(settings.log_level)

    banco = banco or BancoDeDados(criar_engine(settings.url_banco()))
    validador = validador or ValidadorToken(
        ProvedorJwks(settings.jwks_url),
        emissor=settings.oidc_issuer,
        audiencia=settings.oidc_audience,
        azp_permitidos=settings.oidc_azp_permitidos,
    )
    auth = Autenticacao(
        validador, url_autorizacao=settings.url_autorizacao, url_token=settings.url_token
    )
    metricas = Metricas()
    composicao = Composicao(
        banco,
        relogio or RelogioSistema(),
        PublicadorEventosComMetricas(
            publicador or PublicadorEventosLog(), acoes_metricas_negocio(metricas)
        ),
        ttl_reserva=timedelta(minutes=settings.reserva_ttl_minutos),
    )
    dep_catalogo, dep_vendas = composicao.dependencias()

    app = FastAPI(
        title="Revenda de Veículos: API",
        version=__version__,
        description=DESCRICAO,
        openapi_tags=TAGS,
        swagger_ui_init_oauth={
            "clientId": settings.oidc_swagger_client_id,
            "usePkceWithAuthorizationCodeGrant": True,
            "scopes": "openid",
        },
        swagger_ui_parameters={"persistAuthorization": True},
    )
    # O último adicionado é o mais externo: a correlação envolve as métricas, então o 500
    # que ela produz para uma exceção também é contado (o middleware de métricas vê a
    # exceção passar e registra status 500).
    app.add_middleware(MetricasMiddleware, metricas=metricas)
    app.add_middleware(CorrelacaoMiddleware)
    registrar_tratadores_globais(app)
    registrar_problemas(app, {**PROBLEMAS_CATALOGO, **PROBLEMAS_VENDAS})

    api = APIRouter(prefix=PREFIXO_API)
    api.include_router(criar_router_veiculos(auth, dep_catalogo))
    api.include_router(criar_router_vendas(auth, dep_vendas))
    api.include_router(
        criar_router_pagamentos(settings.webhook_secret.get_secret_value(), dep_vendas)
    )
    app.include_router(api)
    app.include_router(criar_router_saude(banco.disponivel))
    # Formato de exposição do Prometheus. Público no ambiente local; em produção, restringir
    # ao scraper (NetworkPolicy/porta interna) ou proteger no proxy (ver shared/metricas.py).
    app.add_route("/metrics", metricas.endpoint(), methods=["GET"], include_in_schema=False)

    _incluir_esquema_problema(app)
    app.state.banco = banco
    app.state.metricas = metricas
    return app


def _incluir_esquema_problema(app: FastAPI) -> None:
    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            esquema = get_openapi(
                title=app.title,
                version=app.version,
                description=app.description,
                routes=app.routes,
                tags=app.openapi_tags,
            )
            componentes = esquema.setdefault("components", {}).setdefault("schemas", {})
            componentes["Problema"] = Problema.model_json_schema(
                ref_template="#/components/schemas/{model}"
            )
            componentes.update(componentes["Problema"].pop("$defs", {}))
            app.openapi_schema = esquema
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]


_app: FastAPI | None = None


def __getattr__(nome: str) -> Any:
    # `app` é criado sob demanda (PEP 562): importar revenda.main nos testes ou no Alembic
    # não exige as variáveis de ambiente da aplicação; o uvicorn acessa `revenda.main:app`.
    global _app
    if nome == "app":
        if _app is None:
            _app = criar_app()
        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {nome!r}")
