"""Vercel Python function; also testable with Python's standard HTTP server."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler
import json
from urllib.parse import parse_qs, urlsplit

from app.vercel_api import dispatch

MAX_BODY = 24_000


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.handle_request()

    def do_POST(self) -> None:
        self.handle_request()

    def handle_request(self) -> None:
        parsed = urlsplit(self.path)
        # Vercel rewrites /api/:path* to this function and preserves the route here.
        routed = parse_qs(parsed.query).get("route", [""])[0]
        path = "/api/" + routed.lstrip("/") if routed else parsed.path
        payload = None
        if self.command == "POST":
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.respond(400, {"error": "Invalid content length."})
                return
            if length < 0 or length > MAX_BODY:
                self.respond(413, {"error": "Request too large."})
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeError):
                self.respond(400, {"error": "Invalid JSON."})
                return
        try:
            status, body = dispatch(self.command, path, payload)
        except Exception:
            # No raw query or credential is written to application logs.
            status, body = 500, {"error": "The bundled demo could not complete this request."}
        self.respond(status, body)

    def respond(self, status: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:
        return
