"""Regras de dependência (RNF-11), verificadas pelo código-fonte, sem importar módulos.

Complementa os contratos do import-linter (`uv run lint-imports`) com uma checagem que roda
junto da suíte de testes.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "revenda"
FRAMEWORKS = (
    "fastapi",
    "starlette",
    "sqlalchemy",
    "pydantic",
    "pydantic_settings",
    "psycopg",
    "jwt",
)


def _importados(arquivo: Path) -> set[str]:
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
    nomes: set[str] = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            nomes.update(a.name for a in no.names)
        elif isinstance(no, ast.ImportFrom) and no.module and no.level == 0:
            nomes.add(no.module)
    return nomes


def _arquivos(*partes: str) -> list[Path]:
    arquivos = sorted((SRC.joinpath(*partes)).rglob("*.py"))
    assert arquivos, f"nenhum arquivo em {partes}"
    return arquivos


def _viola(importados: set[str], proibidos: tuple[str, ...]) -> list[str]:
    return sorted(i for i in importados for p in proibidos if i == p or i.startswith(p + "."))


@pytest.mark.parametrize("modulo", ["catalogo", "vendas"])
def test_dominio_nao_depende_de_frameworks_nem_de_outros_pacotes(modulo: str) -> None:
    for arquivo in _arquivos(modulo, "domain"):
        proibidos = (*FRAMEWORKS, "revenda.shared", f"revenda.{_outro(modulo)}")
        assert _viola(_importados(arquivo), proibidos) == [], arquivo


@pytest.mark.parametrize("modulo", ["catalogo", "vendas"])
def test_aplicacao_nao_depende_de_frameworks(modulo: str) -> None:
    for arquivo in _arquivos(modulo, "application"):
        proibidos = (
            *FRAMEWORKS,
            f"revenda.{modulo}.infrastructure",
            f"revenda.{modulo}.interfaces",
        )
        assert _viola(_importados(arquivo), proibidos) == [], arquivo


@pytest.mark.parametrize("modulo", ["catalogo", "vendas"])
def test_modulos_nao_se_importam(modulo: str) -> None:
    for arquivo in _arquivos(modulo):
        assert _viola(_importados(arquivo), (f"revenda.{_outro(modulo)}",)) == [], arquivo


def test_shared_nao_conhece_modulos_de_negocio() -> None:
    proibidos = ("revenda.catalogo", "revenda.vendas", "revenda.main", "revenda.composicao")
    for arquivo in _arquivos("shared"):
        assert _viola(_importados(arquivo), proibidos) == [], arquivo


def _outro(modulo: str) -> str:
    return "vendas" if modulo == "catalogo" else "catalogo"
