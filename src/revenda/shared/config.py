"""Configuração por variáveis de ambiente (contrato da seção 14.1 do design brief)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

_DRIVER = "postgresql+psycopg"


class DatabaseSettings(BaseSettings):
    """Somente o necessário para conectar ao banco.

    Separada de `Settings` para que o Job de migração (Alembic) não precise das
    variáveis de OIDC nem do segredo do webhook.
    """

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    database_url: str | None = Field(default=None, description="Tem precedência sobre DB_*")
    db_host: str = "localhost"
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = "revenda"
    db_user: str = "revenda"
    db_password: SecretStr = SecretStr("")

    def url_banco(self) -> URL:
        if self.database_url:
            url = make_url(self.database_url)
            # Aceita "postgresql://" (formato comum em ferramentas) e força o driver psycopg 3.
            if url.drivername in ("postgresql", "postgres"):
                url = url.set(drivername=_DRIVER)
            return url
        return URL.create(
            drivername=_DRIVER,
            username=self.db_user,
            password=self.db_password.get_secret_value() or None,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )


class Settings(DatabaseSettings):
    oidc_issuer: str = "http://localhost:8180/realms/revenda"
    oidc_jwks_url: str | None = Field(
        default=None,
        description="Se ausente, derivado de OIDC_ISSUER (/protocol/openid-connect/certs)",
    )
    oidc_audience: str = "revenda-api"
    oidc_swagger_client_id: str = "revenda-swagger"
    oidc_azp_permitidos: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["revenda-swagger", "revenda-e2e"],
        description="Clients (claim azp) aceitos; opcional, lista separada por vírgulas",
    )
    webhook_secret: SecretStr = Field(min_length=16)
    reserva_ttl_minutos: int = Field(default=30, ge=1, le=24 * 60)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @field_validator("oidc_issuer")
    @classmethod
    def _sem_barra_final(cls, valor: str) -> str:
        return valor.rstrip("/")

    @field_validator("log_level", mode="before")
    @classmethod
    def _maiusculas(cls, valor: object) -> object:
        return valor.upper() if isinstance(valor, str) else valor

    @field_validator("oidc_azp_permitidos", mode="before")
    @classmethod
    def _lista_por_virgulas(cls, valor: object) -> object:
        if isinstance(valor, str):
            return [item.strip() for item in valor.split(",") if item.strip()]
        return valor

    @property
    def jwks_url(self) -> str:
        return self.oidc_jwks_url or f"{self.oidc_issuer}/protocol/openid-connect/certs"

    @property
    def url_autorizacao(self) -> str:
        return f"{self.oidc_issuer}/protocol/openid-connect/auth"

    @property
    def url_token(self) -> str:
        return f"{self.oidc_issuer}/protocol/openid-connect/token"
