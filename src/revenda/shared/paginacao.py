"""Página de resultados devolvida pelos casos de uso de listagem."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

LIMITE_PADRAO = 20
LIMITE_MAXIMO = 100


@dataclass(frozen=True, slots=True)
class Pagina[T]:
    itens: Sequence[T]
    total: int
    limite: int
    deslocamento: int
