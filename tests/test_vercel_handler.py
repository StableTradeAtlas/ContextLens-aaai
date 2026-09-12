"""Exercise the HTTP handler through Vercel's method-dispatch wrapper."""
from __future__ import annotations

from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread

from api.service import handler


class RuntimeBase(BaseHTTPRequestHandler):
    pass


class RuntimeHandler(RuntimeBase, handler):
    # Vercel defines this method on its subclass before calling do_GET/do_POST:
    # https://github.com/vercel/vercel/blob/main/python/vercel-runtime/src/vercel_runtime/vc_init.py
    def handle_request(self):
        getattr(self, "do_" + self.command)()


@contextmanager
def request(method, path, payload=None, raw=None):
    server = ThreadingHTTPServer(("127.0.0.1", 0), RuntimeHandler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    connection = HTTPConnection(*server.server_address, timeout=5)
    try:
        body = raw if raw is not None else (
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if payload is not None else None
        )
        connection.request(method, path, body, {"Content-Type": "application/json"})
        response = connection.getresponse()
        yield response, json.loads(response.read())
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_runtime_wrapper_health_returns_json():
    for path in ("/api/health", "/api/service?route=health"):
        with request("GET", path) as (response, body):
            assert response.status == 200
            assert response.headers["Content-Type"].startswith("application/json")
            assert response.headers["Cache-Control"] == "no-store"
            assert body["ok"] and body["official_records"] == 154


def test_runtime_wrapper_completes_chinese_and_english_investigations():
    for address in ("外滩20号", "20 The Bund"):
        payload = {"address": address, "era_hint": "1930年代"}
        with request("POST", "/api/service?route=place%2Fresolve", payload) as (response, body):
            assert response.status == 200
            assert body["status"] == "resolved"
            payload["candidate"] = body["candidates"][0]
        with request("POST", "/api/service?route=investigations", payload) as (response, body):
            assert response.status == 200 and body["status"] == "complete"
            assert body["result"]["evidence"]


def test_runtime_wrapper_invalid_json_returns_json_error():
    with request("POST", "/api/service?route=place%2Fresolve", raw=b"invalid") as (response, body):
        assert response.status == 400
        assert body["error"] == "Invalid JSON."


def test_runtime_wrapper_unknown_route_returns_json_error():
    with request("GET", "/api/service?route=missing") as (response, body):
        assert response.status == 404 and body["error"]
