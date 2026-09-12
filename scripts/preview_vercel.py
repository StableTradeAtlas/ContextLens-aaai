"""Local parity preview of the static output plus stateless Vercel endpoints."""
from __future__ import annotations

import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CONTEXTLENS_RUNTIME_DIR", str(ROOT / "data" / "preview-runtime"))
from api.service import handler as APIHandler


class PreviewHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/"):
            APIHandler.handle_request(self)
        else:
            super().do_GET()

    def do_POST(self):
        APIHandler.handle_request(self)

    respond = APIHandler.respond
    log_message = APIHandler.log_message


if __name__ == "__main__":
    serve = partial(PreviewHandler, directory=str(ROOT / "dist"))
    print("Stateless preview: http://127.0.0.1:8766", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8766), serve).serve_forever()
