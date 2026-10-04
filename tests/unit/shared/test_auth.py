"""Validação de JWT (RS256, iss, aud, azp, exp, sub) e cache do JWKS com recarga limitada."""

from __future__ import annotations

import json
import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from apoio.tokens import KID, EmissorTokens
from revenda.shared.auth import ProvedorJwks, TokenInvalidoError


@pytest.fixture(scope="module")
def emissor() -> EmissorTokens:
    return EmissorTokens()


def test_token_valido_gera_principal(emissor: EmissorTokens) -> None:
    token = emissor.emitir(sub="abc-123", papeis=["cliente", "offline_access"])
    principal = emissor.validador().validar(token)
    assert principal.sub == "abc-123"
    assert principal.eh_cliente
    assert not principal.eh_gestor
    assert "offline_access" in principal.papeis


def test_papeis_ausentes_ou_malformados_viram_conjunto_vazio(emissor: EmissorTokens) -> None:
    validador = emissor.validador()
    assert validador.validar(emissor.emitir(realm_access=None)).papeis == frozenset()
    assert validador.validar(emissor.emitir(realm_access={"roles": "gestor"})).papeis == frozenset()
    papeis = validador.validar(emissor.emitir(realm_access={"roles": ["gestor", 7]})).papeis
    assert papeis == frozenset({"gestor"})


def test_tolerancia_de_relogio_de_30_segundos(emissor: EmissorTokens) -> None:
    validador = emissor.validador()
    assert validador.validar(emissor.emitir(expira_em_segundos=-20)).sub
    with pytest.raises(TokenInvalidoError, match="expirado"):
        validador.validar(emissor.emitir(expira_em_segundos=-40))


def _hs256(emissor: EmissorTokens) -> str:
    return jwt.encode(
        {"sub": "x"}, "segredo-simetrico" * 4, algorithm="HS256", headers={"kid": KID}
    )


def _none(emissor: EmissorTokens) -> str:
    cabecalho = {"alg": "none", "typ": "JWT", "kid": KID}
    partes = [
        jwt.utils.base64url_encode(json.dumps(p).encode()).decode()
        for p in (cabecalho, {"sub": "x"})
    ]
    return ".".join([*partes, ""])


CASOS_INVALIDOS: dict[str, Any] = {
    "emissor errado": lambda e: e.emitir(iss="http://outro/realms/revenda"),
    "audiencia errada": lambda e: e.emitir(aud="outra-api"),
    "sem audiencia": lambda e: e.emitir(aud=None),
    "azp nao autorizado": lambda e: e.emitir(azp="client-qualquer"),
    "sub vazio": lambda e: e.emitir(sub=" "),
    "sem exp": lambda e: e.emitir(exp=None),
    "kid desconhecido": lambda e: e.emitir(kid="outra-chave"),
    "assinado por outra chave": lambda e: e.emitir(
        chave=rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ),
    "hs256": _hs256,
    "alg none": _none,
    "lixo": lambda e: "nao.e.jwt",
    "sem kid": lambda e: jwt.encode({"sub": "x"}, e.chave_privada, algorithm="RS256"),
    "nbf no futuro": lambda e: e.emitir(nbf=int(time.time()) + 600),
}


@pytest.mark.parametrize("caso", sorted(CASOS_INVALIDOS))
def test_tokens_invalidos_sao_recusados(emissor: EmissorTokens, caso: str) -> None:
    token = CASOS_INVALIDOS[caso](emissor)
    with pytest.raises(TokenInvalidoError):
        emissor.validador().validar(token)


class ClienteJwksFalso:
    """Substitui o PyJWKClient: cacheia como ele, conta as buscas e simula rotação de chaves."""

    def __init__(self, *chaves: Any) -> None:
        self.buscas: list[bool] = []
        self.falhar = False
        self._cache: jwt.PyJWKSet | None = None
        self.definir(*chaves)

    def definir(self, *chaves: tuple[str, Any]) -> None:
        jwks = []
        for kid, publica in chaves:
            jwk = RSAAlgorithm.to_jwk(publica, as_dict=True)
            jwks.append({**jwk, "kid": kid, "use": "sig", "alg": "RS256"})
        self.publicado = jwt.PyJWKSet.from_dict({"keys": jwks})

    def get_jwk_set(self, refresh: bool = False) -> jwt.PyJWKSet:
        self.buscas.append(refresh)
        if self.falhar:
            raise jwt.PyJWKClientConnectionError("Keycloak fora do ar")
        if refresh or self._cache is None:
            self._cache = self.publicado
        return self._cache


def test_provedor_jwks_recarrega_kid_novo_no_maximo_uma_vez_por_intervalo(
    emissor: EmissorTokens,
) -> None:
    relogio = [1000.0]
    cliente = ClienteJwksFalso(("antiga", emissor.chave_publica))
    provedor = ProvedorJwks(
        "http://kc/certs",
        cliente=cliente,  # type: ignore[arg-type]
        intervalo_recarga=60,
        monotonic=lambda: relogio[0],
    )
    assert provedor.chave_para("antiga") is not None
    assert cliente.buscas == [False]

    # Rotação de chaves: o kid novo força uma recarga imediata.
    cliente.definir(("antiga", emissor.chave_publica), (KID, emissor.chave_publica))
    assert provedor.chave_para(KID) is not None
    assert cliente.buscas == [False, False, True]

    # kid inexistente dentro do intervalo: não recarrega de novo (proteção contra DoS).
    with pytest.raises(TokenInvalidoError, match="desconhecida"):
        provedor.chave_para("aleatorio")
    assert cliente.buscas.count(True) == 1

    relogio[0] += 61
    with pytest.raises(TokenInvalidoError):
        provedor.chave_para("aleatorio")
    assert cliente.buscas.count(True) == 2


def test_provedor_jwks_indisponivel(emissor: EmissorTokens) -> None:
    cliente = ClienteJwksFalso(("k", emissor.chave_publica))
    cliente.falhar = True
    provedor = ProvedorJwks("http://kc/certs", cliente=cliente)  # type: ignore[arg-type]
    with pytest.raises(TokenInvalidoError, match="Não foi possível validar"):
        provedor.chave_para("k")


def test_provedor_jwks_padrao_usa_pyjwkclient() -> None:
    provedor = ProvedorJwks("http://keycloak.invalid/certs")
    assert isinstance(provedor._cliente, jwt.PyJWKClient)
