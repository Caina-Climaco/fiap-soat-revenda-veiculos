"""Fixtures e apoio dos testes ponta a ponta (marcador ``e2e``).

Os testes rodam contra o ambiente implantado (kind): API em ``E2E_API_URL`` e
Keycloak em ``E2E_KEYCLOAK_URL`` (servico de identidade, outro repositorio). Tokens sao
obtidos do Keycloak real por password grant no client ``revenda-e2e`` e os clientes
compradores sao criados pela Admin REST API, simulando o autocadastro, com o client tecnico
``revenda-e2e-admin`` (client credentials; so gerencia usuarios do realm ``revenda``). Os
dois clients existem somente no ambiente local e fazem parte do contrato publicado pelo
repositorio fiap-soat-revenda-identidade. O admin do realm master nunca e usado aqui.

Dependencias: apenas ``pytest`` e ``httpx`` (``tests/e2e/requirements.txt``); este
modulo nao importa o pacote ``revenda``.

Variaveis de ambiente:

=========================  ===========  ==========================================
Variavel                   Obrigatoria  Uso
=========================  ===========  ==========================================
E2E_API_URL                nao          Base da API (padrao http://localhost:8080)
E2E_KEYCLOAK_URL           nao          Base do Keycloak (padrao http://localhost:8180)
E2E_GESTOR_PASSWORD        sim          Senha do usuario seed ``gestor.loja``
E2E_WEBHOOK_SECRET         sim          Valor do header ``X-Webhook-Secret``
E2E_KC_CLIENT_SECRET       sim          Segredo do client ``revenda-e2e-admin``
E2E_KC_CLIENT_ID           nao          Padrao ``revenda-e2e-admin``
E2E_GESTOR_USERNAME        nao          Padrao ``gestor.loja``
E2E_RESERVA_TTL_MINUTOS    nao          TTL esperado da reserva (padrao 30)
E2E_EXIGIR                 nao          ``1`` transforma variavel ausente em erro (CD)
=========================  ===========  ==========================================

Sem as variaveis obrigatorias, os testes sao pulados com uma mensagem clara
(exceto com ``E2E_EXIGIR=1``, usado no CD para nunca aprovar um deploy sem e2e).
"""

from __future__ import annotations

import os
import random
import secrets
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest

REALM = "revenda"
CLIENT_E2E = "revenda-e2e"
API_PREFIXO = "/api/v1"
PROBLEMA_PREFIXO = "urn:revenda:problema:"
VARIAVEIS_OBRIGATORIAS = (
    "E2E_GESTOR_PASSWORD",
    "E2E_WEBHOOK_SECRET",
    "E2E_KC_CLIENT_SECRET",
)
TIMEOUT = httpx.Timeout(20.0, connect=5.0)


# --------------------------------------------------------------------------- #
# Configuracao e pulo limpo sem ambiente
# --------------------------------------------------------------------------- #
def _variaveis_ausentes() -> list[str]:
    return [nome for nome in VARIAVEIS_OBRIGATORIAS if not os.environ.get(nome)]


def _mensagem_ausentes(ausentes: list[str]) -> str:
    return (
        "e2e requer o ambiente implantado e as variaveis de ambiente "
        f"{', '.join(ausentes)} (ver docs/09-testes.md, secao 9.3)"
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    ausentes = _variaveis_ausentes()
    if not ausentes:
        return
    if os.environ.get("E2E_EXIGIR") == "1":
        raise pytest.UsageError(_mensagem_ausentes(ausentes))
    marcador = pytest.mark.skip(reason=_mensagem_ausentes(ausentes))
    for item in items:
        if item.get_closest_marker("e2e") is not None:
            item.add_marker(marcador)


@dataclass(frozen=True)
class Config:
    api_url: str
    keycloak_url: str
    gestor_username: str
    gestor_password: str
    webhook_secret: str
    kc_client_id: str
    kc_client_secret: str
    reserva_ttl_minutos: int

    @classmethod
    def do_ambiente(cls) -> Config:
        ausentes = _variaveis_ausentes()
        if ausentes:
            pytest.skip(_mensagem_ausentes(ausentes))
        return cls(
            api_url=os.environ.get("E2E_API_URL", "http://localhost:8080").rstrip("/"),
            keycloak_url=os.environ.get("E2E_KEYCLOAK_URL", "http://localhost:8180").rstrip("/"),
            gestor_username=os.environ.get("E2E_GESTOR_USERNAME", "gestor.loja"),
            gestor_password=os.environ["E2E_GESTOR_PASSWORD"],
            webhook_secret=os.environ["E2E_WEBHOOK_SECRET"],
            kc_client_id=os.environ.get("E2E_KC_CLIENT_ID", "revenda-e2e-admin"),
            kc_client_secret=os.environ["E2E_KC_CLIENT_SECRET"],
            reserva_ttl_minutos=int(os.environ.get("E2E_RESERVA_TTL_MINUTOS", "30")),
        )


# --------------------------------------------------------------------------- #
# Utilitarios
# --------------------------------------------------------------------------- #
def gerar_cpf() -> str:
    """CPF com 11 digitos e digitos verificadores validos (dado ficticio de teste)."""
    base = [random.randint(0, 9) for _ in range(9)]
    while len(set(base)) == 1:
        base = [random.randint(0, 9) for _ in range(9)]
    for tamanho in (9, 10):
        soma = sum(d * p for d, p in zip(base[:tamanho], range(tamanho + 1, 1, -1), strict=True))
        resto = (soma * 10) % 11
        base.append(0 if resto == 10 else resto)
    return "".join(map(str, base))


def iso(valor: str) -> datetime:
    """Converte data ISO-8601 da API (sufixo Z) para datetime com fuso."""
    return datetime.fromisoformat(valor.replace("Z", "+00:00"))


def tipo_problema(resposta: httpx.Response) -> str:
    """Sufixo do ``type`` do problem+json (ex.: ``veiculo-indisponivel``)."""
    corpo = resposta.json()
    tipo = str(corpo.get("type", ""))
    return tipo.removeprefix(PROBLEMA_PREFIXO)


def assert_problema(resposta: httpx.Response, status: int, tipo: str | None = None) -> None:
    """Valida status, Content-Type RFC 9457 e, opcionalmente, o tipo do problema."""
    assert resposta.status_code == status, (
        f"esperado {status}, obtido {resposta.status_code}: {resposta.text[:500]}"
    )
    content_type = resposta.headers.get("content-type", "")
    assert content_type.startswith("application/problem+json"), content_type
    corpo = resposta.json()
    assert corpo.get("status") == status, corpo
    if tipo is not None:
        assert tipo_problema(resposta) == tipo, corpo


def assert_status(resposta: httpx.Response, status: int) -> Any:
    assert resposta.status_code == status, (
        f"{resposta.request.method} {resposta.request.url} -> esperado {status}, "
        f"obtido {resposta.status_code}: {resposta.text[:500]}"
    )
    return resposta.json() if resposta.content else None


@dataclass
class Token:
    valor: str
    expira_em: float

    def valido(self) -> bool:
        return time.monotonic() < self.expira_em - 15


@dataclass
class Usuario:
    username: str
    password: str
    keycloak_id: str | None = None
    _token: Token | None = field(default=None, repr=False)


# --------------------------------------------------------------------------- #
# Clientes HTTP: Keycloak e API
# --------------------------------------------------------------------------- #
class Keycloak:
    """Tokens (password grant) e administracao de usuarios de teste."""

    def __init__(self, cfg: Config, http: httpx.Client) -> None:
        self.cfg = cfg
        self.http = http
        self.criados: list[str] = []

    def _token_url(self, realm: str) -> str:
        return f"{self.cfg.keycloak_url}/realms/{realm}/protocol/openid-connect/token"

    def token(self, usuario: Usuario) -> str:
        if usuario._token is not None and usuario._token.valido():
            return usuario._token.valor
        resposta = self.http.post(
            self._token_url(REALM),
            data={
                "grant_type": "password",
                "client_id": CLIENT_E2E,
                "username": usuario.username,
                "password": usuario.password,
                "scope": "openid",
            },
        )
        assert resposta.status_code == 200, (
            f"falha ao obter token de '{usuario.username}' no client {CLIENT_E2E}: "
            f"{resposta.status_code} {resposta.text[:300]}"
        )
        corpo = resposta.json()
        usuario._token = Token(
            valor=corpo["access_token"],
            expira_em=time.monotonic() + float(corpo.get("expires_in", 60)),
        )
        return usuario._token.valor

    def _admin_headers(self) -> dict[str, str]:
        # Client credentials do client tecnico (papeis manage-users/view-users/query-users
        # do realm revenda): um token novo a cada operacao, sem cache.
        resposta = self.http.post(
            self._token_url(REALM),
            data={
                "grant_type": "client_credentials",
                "client_id": self.cfg.kc_client_id,
                "client_secret": self.cfg.kc_client_secret,
            },
        )
        assert resposta.status_code == 200, (
            f"falha ao obter token do client {self.cfg.kc_client_id}: "
            f"{resposta.status_code} {resposta.text[:300]}"
        )
        return {"Authorization": f"Bearer {resposta.json()['access_token']}"}

    def criar_cliente(self, rotulo: str) -> Usuario:
        """Cria um comprador no realm (equivale ao autocadastro: recebe o papel cliente)."""
        sufixo = uuid.uuid4().hex[:10]
        username = f"e2e-{rotulo}-{sufixo}".lower()
        email = f"{username}@e2e.revenda.local"
        senha = f"E2e!{secrets.token_urlsafe(12)}9aZ"
        resposta = self.http.post(
            f"{self.cfg.keycloak_url}/admin/realms/{REALM}/users",
            headers=self._admin_headers(),
            json={
                "username": username,
                "email": email,
                "emailVerified": True,
                "enabled": True,
                "firstName": "Cliente",
                "lastName": f"E2E {rotulo}",
                "attributes": {"cpf": [gerar_cpf()]},
                "requiredActions": [],
                "credentials": [{"type": "password", "value": senha, "temporary": False}],
            },
        )
        assert resposta.status_code == 201, (
            f"falha ao criar cliente de teste no Keycloak: {resposta.status_code} "
            f"{resposta.text[:300]}"
        )
        keycloak_id = resposta.headers.get("location", "").rstrip("/").rsplit("/", 1)[-1]
        self.criados.append(keycloak_id)
        return Usuario(username=username, password=senha, keycloak_id=keycloak_id)

    def remover_criados(self) -> list[str]:
        """Remove os usuarios criados nesta execucao; devolve os que falharam."""
        falhas: list[str] = []
        if not self.criados:
            return falhas
        try:
            headers = self._admin_headers()
        except (AssertionError, httpx.HTTPError):
            return list(self.criados)
        for keycloak_id in self.criados:
            try:
                resposta = self.http.delete(
                    f"{self.cfg.keycloak_url}/admin/realms/{REALM}/users/{keycloak_id}",
                    headers=headers,
                )
            except httpx.HTTPError:
                falhas.append(keycloak_id)
                continue
            if resposta.status_code not in (204, 404):
                falhas.append(keycloak_id)
        self.criados.clear()
        return falhas


class Api:
    """Operacoes da revenda-api usadas pelos cenarios (docs/05-api.md)."""

    def __init__(self, cfg: Config, http: httpx.Client, keycloak: Keycloak) -> None:
        self.cfg = cfg
        self.http = http
        self.kc = keycloak

    # ---- infraestrutura -------------------------------------------------- #
    def url(self, caminho: str) -> str:
        return f"{self.cfg.api_url}{caminho}"

    def auth(self, usuario: Usuario | None) -> dict[str, str]:
        if usuario is None:
            return {}
        return {"Authorization": f"Bearer {self.kc.token(usuario)}"}

    def get(self, caminho: str, usuario: Usuario | None = None, **kwargs: Any) -> httpx.Response:
        return self.http.get(self.url(caminho), headers=self.auth(usuario), **kwargs)

    def post(
        self, caminho: str, usuario: Usuario | None = None, json: Any = None, **kwargs: Any
    ) -> httpx.Response:
        return self.http.post(self.url(caminho), headers=self.auth(usuario), json=json, **kwargs)

    def patch(self, caminho: str, usuario: Usuario | None, json: Any) -> httpx.Response:
        return self.http.patch(self.url(caminho), headers=self.auth(usuario), json=json)

    # ---- catalogo -------------------------------------------------------- #
    def cadastrar_veiculo(
        self,
        gestor: Usuario,
        preco: str,
        marca: str = "Fiat",
        modelo: str = "Argo E2E",
        ano: int = 2022,
        cor: str = "Prata",
    ) -> dict[str, Any]:
        resposta = self.post(
            f"{API_PREFIXO}/veiculos",
            gestor,
            json={"marca": marca, "modelo": modelo, "ano": ano, "cor": cor, "preco": preco},
        )
        veiculo: dict[str, Any] = assert_status(resposta, 201)
        assert resposta.headers.get("location", "").endswith(f"/veiculos/{veiculo['id']}"), (
            resposta.headers
        )
        return veiculo

    def veiculo(self, veiculo_id: str) -> dict[str, Any]:
        resultado: dict[str, Any] = assert_status(
            self.get(f"{API_PREFIXO}/veiculos/{veiculo_id}"), 200
        )
        return resultado

    def listar_todos(self, caminho: str, usuario: Usuario | None = None) -> list[dict[str, Any]]:
        """Percorre todas as paginas (limite 100) de uma listagem paginada."""
        itens: list[dict[str, Any]] = []
        deslocamento = 0
        for _ in range(500):
            pagina = assert_status(
                self.get(caminho, usuario, params={"limite": 100, "deslocamento": deslocamento}),
                200,
            )
            assert set(pagina) >= {"itens", "total", "limite", "deslocamento"}, pagina
            itens.extend(pagina["itens"])
            deslocamento += len(pagina["itens"])
            if not pagina["itens"] or deslocamento >= pagina["total"]:
                break
        return itens

    def a_venda(self) -> list[dict[str, Any]]:
        return self.listar_todos(f"{API_PREFIXO}/veiculos/a-venda")

    def vendidos(self) -> list[dict[str, Any]]:
        return self.listar_todos(f"{API_PREFIXO}/veiculos/vendidos")

    # ---- vendas ---------------------------------------------------------- #
    def comprar(self, usuario: Usuario | None, veiculo_id: str) -> httpx.Response:
        return self.post(f"{API_PREFIXO}/vendas", usuario, json={"veiculo_id": veiculo_id})

    def comprar_ok(self, usuario: Usuario, veiculo_id: str) -> dict[str, Any]:
        venda: dict[str, Any] = assert_status(self.comprar(usuario, veiculo_id), 201)
        return venda

    def venda(self, usuario: Usuario, venda_id: str) -> httpx.Response:
        return self.get(f"{API_PREFIXO}/vendas/{venda_id}", usuario)

    def minhas(self, usuario: Usuario) -> list[dict[str, Any]]:
        return self.listar_todos(f"{API_PREFIXO}/vendas/minhas", usuario)

    def webhook(
        self, codigo_pagamento: str, status: str, headers: dict[str, str] | None = None
    ) -> httpx.Response:
        """Simula o gateway. Sem ``headers``, envia o segredo correto em X-Webhook-Secret."""
        if headers is None:
            headers = {"X-Webhook-Secret": self.cfg.webhook_secret}
        return self.http.post(
            self.url(f"{API_PREFIXO}/pagamentos/webhook"),
            headers=headers,
            json={"codigo_pagamento": codigo_pagamento, "status": status},
        )

    # ---- verificacoes (expostas aqui para os testes nao importarem o conftest) ---- #
    assert_status = staticmethod(assert_status)
    assert_problema = staticmethod(assert_problema)
    tipo_problema = staticmethod(tipo_problema)
    iso = staticmethod(iso)

    @staticmethod
    def posicoes(itens: list[dict[str, Any]], ids: list[str]) -> list[int]:
        """Indices dos ids na listagem (falha se algum nao estiver presente)."""
        indice = {item["id"]: i for i, item in enumerate(itens)}
        faltando = [i for i in ids if i not in indice]
        assert not faltando, f"veiculos ausentes da listagem: {faltando}"
        return [indice[i] for i in ids]

    @staticmethod
    def assert_ordenado_por_preco(itens: list[dict[str, Any]]) -> None:
        """A listagem inteira deve estar em ordem nao decrescente de preco."""
        precos = [Decimal(item["preco"]) for item in itens]
        for i in range(1, len(precos)):
            assert precos[i - 1] <= precos[i], (
                f"listagem fora de ordem na posicao {i}: {precos[i - 1]} > {precos[i]}"
            )

    @staticmethod
    def barrado_no_gateway(resposta: httpx.Response, status: int) -> None:
        """A resposta foi produzida pelo proprio Kong (nao chegou a API)."""
        assert resposta.status_code == status, (resposta.status_code, resposta.text[:300])
        servidor = resposta.headers.get("server", "").lower()
        assert servidor.startswith("kong"), f"esperada resposta do Kong, Server={servidor!r}"
        assert "x-kong-upstream-latency" not in resposta.headers, "a requisicao chegou a API"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def e2e_config() -> Config:
    return Config.do_ambiente()


@pytest.fixture(scope="session")
def http() -> Iterator[httpx.Client]:
    with httpx.Client(timeout=TIMEOUT, follow_redirects=False) as cliente:
        yield cliente


@pytest.fixture(scope="session")
def keycloak(e2e_config: Config, http: httpx.Client) -> Iterator[Keycloak]:
    kc = Keycloak(e2e_config, http)
    discovery = http.get(
        f"{e2e_config.keycloak_url}/realms/{REALM}/.well-known/openid-configuration"
    )
    assert discovery.status_code == 200, (
        f"Keycloak indisponivel em {e2e_config.keycloak_url}: {discovery.status_code}"
    )
    yield kc
    falhas = kc.remover_criados()
    if falhas:
        print(f"\n[e2e] aviso: usuarios de teste nao removidos do Keycloak: {falhas}")


@pytest.fixture(scope="session")
def api(e2e_config: Config, http: httpx.Client, keycloak: Keycloak) -> Api:
    pronto = http.get(f"{e2e_config.api_url}/health/ready")
    assert pronto.status_code == 200, (
        f"API nao esta pronta em {e2e_config.api_url}/health/ready: "
        f"{pronto.status_code} {pronto.text[:200]}"
    )
    return Api(e2e_config, http, keycloak)


@pytest.fixture(scope="session")
def via_gateway(e2e_config: Config, http: httpx.Client) -> bool:
    """A API esta atras do API Gateway (Kong, ADR-015)?

    ``E2E_GATEWAY=1`` (CD) torna o gateway obrigatorio; sem a variavel, detecta pelo
    cabecalho ``Via`` que o Kong acrescenta nas respostas que ele encaminha.
    """
    if os.environ.get("E2E_GATEWAY") == "1":
        return True
    resposta = http.get(f"{e2e_config.api_url}/health/live")
    return "kong" in resposta.headers.get("via", "").lower()


@pytest.fixture(scope="session")
def gestor(e2e_config: Config) -> Usuario:
    return Usuario(username=e2e_config.gestor_username, password=e2e_config.gestor_password)


@pytest.fixture(scope="session")
def cliente_a(keycloak: Keycloak) -> Usuario:
    return keycloak.criar_cliente("a")


@pytest.fixture(scope="session")
def cliente_b(keycloak: Keycloak) -> Usuario:
    return keycloak.criar_cliente("b")


@pytest.fixture(scope="session")
def execucao() -> str:
    """Identificador curto desta execucao, usado nos modelos dos veiculos criados."""
    return uuid.uuid4().hex[:8]


class Precos:
    """Precos distintivos por execucao: mesmo valor inteiro com centavos aleatorios."""

    def __init__(self) -> None:
        self.centavos = random.randint(1, 98)
        self.usados: set[str] = set()

    def __call__(self, reais: int | str) -> str:
        inteiro = int(reais)
        valor = f"{inteiro}.{self.centavos:02d}"
        while valor in self.usados:
            inteiro += 1
            valor = f"{inteiro}.{self.centavos:02d}"
        self.usados.add(valor)
        return valor


@pytest.fixture(scope="session")
def preco() -> Precos:
    return Precos()
