"""Faux serveur HTTP pour les tests du lanceur : répond 200 et un corps fixe sur tous les chemins.

python3 fake_server.py PORT [CORPS]
"""

import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def make_handler(body: bytes) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    return Handler


def serve(port: int, body: str) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(body.encode()))


if __name__ == "__main__":
    serve(int(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "ok").serve_forever()
