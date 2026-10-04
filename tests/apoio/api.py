"""Atalhos HTTP para os testes de API (TestClient), na linguagem do roteiro de testes."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.testclient import TestClient
from httpx import Response

from apoio.tokens import EmissorTokens

SEGREDO_WEBHOOK = "segredo-do-webhook-de-teste-0123456789"
PROBLEM_JSON = "application/problem+json"


class Api:
    def __init__(self, cliente: TestClient, emissor: EmissorTokens) -> None:
        self.http = cliente
        self.emissor = emissor
        self.gestor = emissor.cabecalho(sub=str(uuid.uuid4()), papeis=["gestor"])

    # ------------------------------------------------------------ identidades
    def novo_cliente(self, sub: str | None = None) -> dict[str, str]:
        return self.emissor.cabecalho(sub=sub or str(uuid.uuid4()), papeis=["cliente"])

    # ------------------------------------------------------------ catálogo
    def cadastrar(
        self,
        marca: str = "Fiat",
        modelo: str = "Argo",
        ano: int = 2022,
        cor: str = "Prata",
        preco: str = "72000.00",
        *,
        status_esperado: int = 201,
    ) -> dict[str, Any]:
        resposta = self.http.post(
            "/api/v1/veiculos",
            json={"marca": marca, "modelo": modelo, "ano": ano, "cor": cor, "preco": preco},
            headers=self.gestor,
        )
        assert resposta.status_code == status_esperado, resposta.text
        corpo: dict[str, Any] = resposta.json()
        return corpo

    def veiculo(self, veiculo_id: str) -> dict[str, Any]:
        resposta = self.http.get(f"/api/v1/veiculos/{veiculo_id}")
        assert resposta.status_code == 200, resposta.text
        corpo: dict[str, Any] = resposta.json()
        return corpo

    def a_venda(self, **params: int) -> dict[str, Any]:
        resposta = self.http.get("/api/v1/veiculos/a-venda", params=params)
        assert resposta.status_code == 200, resposta.text
        corpo: dict[str, Any] = resposta.json()
        return corpo

    def vendidos(self, **params: int) -> dict[str, Any]:
        resposta = self.http.get("/api/v1/veiculos/vendidos", params=params)
        assert resposta.status_code == 200, resposta.text
        corpo: dict[str, Any] = resposta.json()
        return corpo

    # ------------------------------------------------------------ vendas
    def comprar(self, veiculo_id: str, cabecalho: dict[str, str] | None) -> Response:
        return self.http.post(
            "/api/v1/vendas", json={"veiculo_id": veiculo_id}, headers=cabecalho or {}
        )

    def compra_ok(self, veiculo_id: str, cabecalho: dict[str, str]) -> dict[str, Any]:
        resposta = self.comprar(veiculo_id, cabecalho)
        assert resposta.status_code == 201, resposta.text
        corpo: dict[str, Any] = resposta.json()
        return corpo

    def venda(self, venda_id: str, cabecalho: dict[str, str]) -> Response:
        return self.http.get(f"/api/v1/vendas/{venda_id}", headers=cabecalho)

    def webhook(
        self, codigo: str, status: str, *, segredo: str | None = SEGREDO_WEBHOOK
    ) -> Response:
        cabecalhos = {} if segredo is None else {"X-Webhook-Secret": segredo}
        return self.http.post(
            "/api/v1/pagamentos/webhook",
            json={"codigo_pagamento": codigo, "status": status},
            headers=cabecalhos,
        )

    def vendas_do_gestor(self, **params: Any) -> dict[str, Any]:
        resposta = self.http.get("/api/v1/vendas", params=params, headers=self.gestor)
        assert resposta.status_code == 200, resposta.text
        corpo: dict[str, Any] = resposta.json()
        return corpo


def tipo_problema(resposta: Response) -> str:
    assert resposta.headers["content-type"].startswith(PROBLEM_JSON), resposta.text
    tipo: str = resposta.json()["type"]
    return tipo.removeprefix("urn:revenda:problema:")
