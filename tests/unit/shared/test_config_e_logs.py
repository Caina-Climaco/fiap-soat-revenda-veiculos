"""Configuração (seção 14.1 do brief), logs JSON e relógio."""

from __future__ import annotations

import io
import json
import logging
import sys
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from revenda.shared.clock import RelogioFixo, RelogioSistema
from revenda.shared.config import DatabaseSettings, Settings
from revenda.shared.eventos import PublicadorEventosLog
from revenda.shared.logging import FormatadorJson, configurar_logs, request_id_atual

VARIAVEIS = (
    "DATABASE_URL",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "OIDC_ISSUER",
    "OIDC_JWKS_URL",
    "OIDC_AUDIENCE",
    "OIDC_SWAGGER_CLIENT_ID",
    "WEBHOOK_SECRET",
    "RESERVA_TTL_MINUTOS",
    "LOG_LEVEL",
)


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch: pytest.MonkeyPatch) -> None:
    for nome in VARIAVEIS:
        monkeypatch.delenv(nome, raising=False)


def test_settings_le_variaveis_do_contrato(monkeypatch: pytest.MonkeyPatch) -> None:
    valores = {
        "DB_HOST": "revenda-db.revenda.svc.cluster.local",
        "DB_PORT": "5432",
        "DB_NAME": "revenda",
        "DB_USER": "revenda",
        "DB_PASSWORD": "s3nh@:/x",
        "OIDC_ISSUER": "http://localhost:8180/realms/revenda/",
        "OIDC_JWKS_URL": "http://keycloak.identidade.svc.cluster.local:8080/realms/revenda/protocol/openid-connect/certs",
        "OIDC_AUDIENCE": "revenda-api",
        "OIDC_SWAGGER_CLIENT_ID": "revenda-swagger",
        "WEBHOOK_SECRET": "x" * 32,
        "RESERVA_TTL_MINUTOS": "15",
        "LOG_LEVEL": "debug",
    }
    for nome, valor in valores.items():
        monkeypatch.setenv(nome, valor)
    settings = Settings()
    url = settings.url_banco()
    assert url.drivername == "postgresql+psycopg"
    assert url.host == "revenda-db.revenda.svc.cluster.local"
    assert url.password == "s3nh@:/x"
    assert settings.oidc_issuer == "http://localhost:8180/realms/revenda"
    assert settings.jwks_url.startswith("http://keycloak.identidade")
    assert settings.url_autorizacao.endswith("/realms/revenda/protocol/openid-connect/auth")
    assert settings.url_token.endswith("/realms/revenda/protocol/openid-connect/token")
    assert settings.reserva_ttl_minutos == 15
    assert settings.log_level == "DEBUG"
    assert settings.oidc_azp_permitidos == ["revenda-swagger", "revenda-e2e"]


def test_database_url_tem_precedencia_e_forca_psycopg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:1/b")
    monkeypatch.setenv("DB_HOST", "ignorado")
    url = DatabaseSettings().url_banco()
    assert (url.drivername, url.host, url.port, url.database) == ("postgresql+psycopg", "h", 1, "b")


def test_jwks_derivado_do_issuer_e_azp_por_virgulas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEBHOOK_SECRET", "y" * 20)
    monkeypatch.setenv("OIDC_AZP_PERMITIDOS", "a, b,,c")
    settings = Settings()
    assert settings.jwks_url == (
        "http://localhost:8180/realms/revenda/protocol/openid-connect/certs"
    )
    assert settings.oidc_azp_permitidos == ["a", "b", "c"]


def test_webhook_secret_e_obrigatorio_e_forte() -> None:
    with pytest.raises(ValidationError):
        Settings()
    with pytest.raises(ValidationError):
        Settings(webhook_secret="curto")


def test_formatador_json_inclui_request_id_e_campos() -> None:
    registro = logging.LogRecord("revenda.teste", logging.INFO, __file__, 1, "olá %s", ("x",), None)
    registro.campos = {"evento": "VendaEfetivada"}
    registro.extra_livre = 7
    registro.color_message = "\x1b[36mcolorido\x1b[0m"  # anexado pelo uvicorn
    token = request_id_atual.set("req-1")
    try:
        saida = json.loads(FormatadorJson().format(registro))
    finally:
        request_id_atual.reset(token)
    assert saida["mensagem"] == "olá x"
    assert saida["request_id"] == "req-1"
    assert saida["evento"] == "VendaEfetivada"
    assert saida["extra_livre"] == 7
    assert saida["nivel"] == "INFO"
    assert "color_message" not in saida


def test_formatador_json_registra_excecao() -> None:
    try:
        raise RuntimeError("falhou")
    except RuntimeError:
        registro = logging.LogRecord("x", logging.ERROR, __file__, 1, "erro", (), sys.exc_info())
    saida = json.loads(FormatadorJson().format(registro))
    assert "RuntimeError: falhou" in saida["excecao"]


def test_configurar_logs_e_publicador_de_eventos() -> None:
    configurar_logs("INFO")
    raiz = logging.getLogger()
    buffer = io.StringIO()
    raiz.handlers[0].setStream(buffer)  # type: ignore[attr-defined]

    class Evento:
        nome = "VeiculoCadastrado"

        def como_dict(self) -> dict[str, str]:
            return {"veiculo_id": "v1"}

    PublicadorEventosLog().publicar([Evento()])
    linha = json.loads(buffer.getvalue().strip())
    assert linha["evento"] == "VeiculoCadastrado"
    assert linha["veiculo_id"] == "v1"
    assert logging.getLogger("uvicorn.access").disabled


def test_relogios() -> None:
    assert RelogioSistema().agora().tzinfo is UTC
    relogio = RelogioFixo(datetime(2026, 1, 1, tzinfo=UTC))
    relogio.avancar(timedelta(minutes=5))
    assert relogio.agora() == datetime(2026, 1, 1, 0, 5, tzinfo=UTC)
    relogio.definir(datetime(2027, 1, 1, tzinfo=UTC))
    assert relogio.agora().year == 2027
    with pytest.raises(ValueError, match="timezone"):
        RelogioFixo(datetime(2026, 1, 1))
