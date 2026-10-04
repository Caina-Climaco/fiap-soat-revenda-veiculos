"""Emissão de JWTs RS256 de teste, assinados por uma chave RSA gerada na hora."""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterable
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from revenda.shared.auth import TokenInvalidoError, ValidadorToken

EMISSOR = "http://localhost:8180/realms/revenda"
AUDIENCIA = "revenda-api"
CLIENT_SWAGGER = "revenda-swagger"
KID = "chave-de-teste"


class ChavesFalsas:
    """`ProvedorChaves` em memória: substitui o JWKS do Keycloak nos testes."""

    def __init__(self, chaves: dict[str, Any]) -> None:
        self._chaves = chaves

    def chave_para(self, kid: str) -> Any:
        try:
            return self._chaves[kid]
        except KeyError:
            raise TokenInvalidoError("Chave de assinatura do token desconhecida.") from None


class EmissorTokens:
    def __init__(self) -> None:
        self.chave_privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.chave_publica = self.chave_privada.public_key()

    def validador(self) -> ValidadorToken:
        return ValidadorToken(
            ChavesFalsas({KID: self.chave_publica}),
            emissor=EMISSOR,
            audiencia=AUDIENCIA,
            azp_permitidos=[CLIENT_SWAGGER, "revenda-e2e"],
        )

    def emitir(
        self,
        *,
        sub: str | None = None,
        papeis: Iterable[str] = ("cliente",),
        expira_em_segundos: int = 300,
        kid: str = KID,
        chave: Any = None,
        algoritmo: str = "RS256",
        **sobrescritas: Any,
    ) -> str:
        agora = int(time.time())
        claims: dict[str, Any] = {
            "iss": EMISSOR,
            "aud": [AUDIENCIA, "account"],
            "azp": CLIENT_SWAGGER,
            "sub": sub or str(uuid.uuid4()),
            "iat": agora,
            "exp": agora + expira_em_segundos,
            "realm_access": {"roles": list(papeis)},
        }
        claims.update(sobrescritas)
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(
            claims, chave or self.chave_privada, algorithm=algoritmo, headers={"kid": kid}
        )

    def cabecalho(self, **kwargs: Any) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.emitir(**kwargs)}"}
