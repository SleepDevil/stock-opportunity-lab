from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse


INDEX_HTML = Path(__file__).resolve().parent / "frontend" / "dist" / "index.html"


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._serve_index()

    def do_HEAD(self):
        self._serve_index(head_only=True)

    def _serve_index(self, head_only: bool = False) -> None:
        path = urlparse(self.path).path
        if Path(path).suffix:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        try:
            body = INDEX_HTML.read_bytes()
        except FileNotFoundError:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Missing frontend index")
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head_only:
            self.wfile.write(body)
