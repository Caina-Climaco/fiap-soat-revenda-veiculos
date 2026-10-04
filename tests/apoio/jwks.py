"""Servidor JWKS falso: publica a chave pública de teste por HTTP, como o Keycloak.

Nos testes de integração a aplicação é montada pelo caminho de produção (`criar_app` sem
validador injetado), então o `ProvedorJwks` usa um `PyJWKClient` de verdade apontado para
este servidor local. Assim a busca, o cache e a seleção da chave por `kid` são exercitados
sem Keycloak real.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from jwt.algorithms import RSAAlgorithm

CAMINHO_CERTS = "/realms/revenda/protocol/openid-connect/certs"


class ServidorJwks:
    def __init__(self, chaves: dict[str, Any]) -> None:
        self.buscas = 0
        self._corpo = json.dumps(
            {
                "keys": [
                    {**RSAAlgorithm.to_jwk(publica, as_dict=True), "kid": kid}
                    | {"use": "sig", "alg": "RS256"}
                    for kid, publica in chaves.items()
                ]
            }
        ).encode()
        servidor = self

        class Tratador(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path != CAMINHO_CERTS:
                    self.send_error(404)
                    return
                servidor.buscas += 1
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(servidor._corpo)))
                self.end_headers()
                self.wfile.write(servidor._corpo)

            def log_message(self, format: str, *args: Any) -> None:
                return  # silencioso nos testes

        self._http = ThreadingHTTPServer(("127.0.0.1", 0), Tratador)
        self._thread = threading.Thread(target=self._http.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, porta = self._http.server_address[:2]
        return f"http://{host!s}:{porta}{CAMINHO_CERTS}"

    @contextmanager
    def rodando(self) -> Iterator[ServidorJwks]:
        self._thread.start()
        try:
            yield self
        finally:
            self._http.shutdown()
            self._http.server_close()
