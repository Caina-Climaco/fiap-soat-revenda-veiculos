"""Validação dos access tokens do Keycloak (JWT RS256 via JWKS) e dependências de autorização."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol

import jwt
from fastapi import Depends, Request
from fastapi.security import OAuth2AuthorizationCodeBearer

from revenda.shared.errors import AcessoNegadoError, NaoAutenticadoError

_logger = logging.getLogger("revenda.auth")

ALGORITMOS_PERMITIDOS = ["RS256"]
TOLERANCIA_RELOGIO_SEGUNDOS = 30
PAPEL_CLIENTE = "cliente"
PAPEL_GESTOR = "gestor"


@dataclass(frozen=True, slots=True)
class Principal:
    """Quem fez a requisição: apenas o pseudônimo `sub` e os papéis (nenhum dado pessoal)."""

    sub: str
    papeis: frozenset[str]

    @property
    def eh_gestor(self) -> bool:
        return PAPEL_GESTOR in self.papeis

    @property
    def eh_cliente(self) -> bool:
        return PAPEL_CLIENTE in self.papeis


class TokenInvalidoError(NaoAutenticadoError):
    pass


class ProvedorChaves(Protocol):
    def chave_para(self, kid: str) -> Any:
        """Chave pública de verificação para o `kid`; TokenInvalidoError se desconhecido."""
        ...


class ProvedorJwks:
    """JWKS do Keycloak com cache (PyJWKClient) e recarga controlada.

    Um `kid` desconhecido força uma recarga (rotação de chaves), limitada a uma por
    `intervalo_recarga` segundos para que tokens com `kid` aleatório não virem um vetor de
    negação de serviço contra o Keycloak.
    """

    def __init__(
        self,
        url: str,
        *,
        ttl_cache_segundos: int = 600,
        intervalo_recarga: float = 60.0,
        timeout_segundos: int = 5,
        cliente: jwt.PyJWKClient | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._cliente = cliente or jwt.PyJWKClient(
            url, cache_jwk_set=True, lifespan=ttl_cache_segundos, timeout=timeout_segundos
        )
        self._intervalo_recarga = intervalo_recarga
        self._monotonic = monotonic
        self._ultima_recarga: float | None = None
        self._trava = threading.Lock()

    def chave_para(self, kid: str) -> Any:
        with self._trava:
            chave = self._procurar(kid, recarregar=False)
            if chave is None and self._pode_recarregar():
                self._ultima_recarga = self._monotonic()
                chave = self._procurar(kid, recarregar=True)
        if chave is None:
            raise TokenInvalidoError("Chave de assinatura do token desconhecida.")
        return chave

    def _pode_recarregar(self) -> bool:
        if self._ultima_recarga is None:
            return True
        return self._monotonic() - self._ultima_recarga >= self._intervalo_recarga

    def _procurar(self, kid: str, *, recarregar: bool) -> Any:
        try:
            conjunto = self._cliente.get_jwk_set(refresh=recarregar)
        except jwt.PyJWKClientError as exc:
            _logger.warning("falha ao obter o JWKS do provedor de identidade: %s", exc)
            raise TokenInvalidoError("Não foi possível validar o token no momento.") from exc
        for chave in conjunto.keys:
            if chave.key_id == kid and chave.public_key_use in (None, "sig"):
                return chave.key
        return None


class ValidadorToken:
    def __init__(
        self,
        provedor: ProvedorChaves,
        *,
        emissor: str,
        audiencia: str,
        azp_permitidos: Iterable[str],
    ) -> None:
        self._provedor = provedor
        self._emissor = emissor
        self._audiencia = audiencia
        self._azp_permitidos = frozenset(azp_permitidos)

    def validar(self, token: str) -> Principal:
        try:
            cabecalho = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise TokenInvalidoError("Token malformado.") from exc
        # Algoritmo fixo: elimina "alg: none" e a confusão RS256/HS256.
        if cabecalho.get("alg") not in ALGORITMOS_PERMITIDOS:
            raise TokenInvalidoError("Algoritmo de assinatura não permitido.")
        kid = cabecalho.get("kid")
        if not isinstance(kid, str) or not kid:
            raise TokenInvalidoError("Token sem identificador de chave (kid).")
        chave = self._provedor.chave_para(kid)
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                chave,
                algorithms=ALGORITMOS_PERMITIDOS,
                audience=self._audiencia,
                issuer=self._emissor,
                leeway=TOLERANCIA_RELOGIO_SEGUNDOS,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenInvalidoError("Token expirado.") from exc
        except jwt.PyJWTError as exc:
            raise TokenInvalidoError(f"Token inválido: {exc}.") from exc

        if claims.get("azp") not in self._azp_permitidos:
            raise TokenInvalidoError("Token emitido para um client não autorizado.")
        sub = claims.get("sub")
        if not isinstance(sub, str) or not sub.strip():
            raise TokenInvalidoError("Token sem identificador do usuário (sub).")
        return Principal(sub=sub, papeis=_papeis(claims))


def _papeis(claims: dict[str, Any]) -> frozenset[str]:
    acesso = claims.get("realm_access")
    papeis = acesso.get("roles") if isinstance(acesso, dict) else None
    if not isinstance(papeis, list):
        return frozenset()
    return frozenset(p for p in papeis if isinstance(p, str))


DependenciaPrincipal = Callable[..., Principal]


class Autenticacao:
    """Dependências FastAPI de autenticação/autorização ligadas a um validador concreto.

    O esquema OAuth2 Authorization Code faz o Swagger UI exibir o botão "Authorize"
    (com PKCE, configurado em main.py).
    """

    def __init__(self, validador: ValidadorToken, *, url_autorizacao: str, url_token: str):
        self._validador = validador
        self.esquema = OAuth2AuthorizationCodeBearer(
            authorizationUrl=url_autorizacao,
            tokenUrl=url_token,
            scopes={"openid": "Identificação OpenID Connect"},
            scheme_name="keycloak",
            description="Login no Keycloak (realm revenda) com Authorization Code + PKCE.",
            auto_error=False,
        )
        self.principal: DependenciaPrincipal = self._criar_dependencia_principal()

    def _criar_dependencia_principal(self) -> DependenciaPrincipal:
        esquema = self.esquema
        validador = self._validador

        def obter_principal(request: Request, token: str | None = Depends(esquema)) -> Principal:
            if not token:
                raise NaoAutenticadoError("Token de acesso ausente.")
            principal = validador.validar(token)
            # Registrado só para o log de acesso: o sub é um pseudônimo, não um dado pessoal.
            request.state.sub = principal.sub
            return principal

        return obter_principal

    def exigir_papel(self, *papeis: str) -> DependenciaPrincipal:
        exigidos = frozenset(papeis)
        dependencia_principal = self.principal

        def verificar(principal: Principal = Depends(dependencia_principal)) -> Principal:
            if not principal.papeis & exigidos:
                raise AcessoNegadoError(
                    "Esta operação exige o papel " + " ou ".join(sorted(exigidos)) + "."
                )
            return principal

        return verificar
