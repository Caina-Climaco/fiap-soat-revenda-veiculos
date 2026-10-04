"""Fixture do cenário de Vendas em memória (ver apoio/cenario.py)."""

from __future__ import annotations

import pytest

from apoio.cenario import Cenario, novo_cenario


@pytest.fixture
def cenario() -> Cenario:
    return novo_cenario()
