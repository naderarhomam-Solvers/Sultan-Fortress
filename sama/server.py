"""Local-only HTTP API + UI. Bound to 127.0.0.1, token-protected, Host-checked
(blocks other websites / DNS-rebinding from driving the agent)."""
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

UI = Path(__file__).parent / "ui" / "index.html"


def make_server(agent, safety, llm, port=0):
    token = secrets.token_urlsafe(24)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _host_ok(self):
            return self.headers.get("Host", "").split(":")[0] in ("127.0.0.1", "localhost")

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _auth(self):
            return self._host_ok() and secrets.compare_digest(self.headers.get("X-Token", ""), token)

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, {"error": "bad host"})
            if self.path == "/":
                html = UI.read_text(encoding="utf-8").replace("__TOKEN__", token)
                return self._send(200, html.encode(), "text/html")
            if self.path.startswith("/api/") and not self._auth():
                return self._send(403, {"error": "forbidden"})
            if self.path == "/api/state":
                return self._send(200, {"busy": agent.busy, "events": agent.events, "pending": safety.pending(),
                                        "llm": llm.available(), "model": agent.cfg.model, "mode": agent.cfg.mode})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._auth():
                return self._send(403, {"error": "forbidden"})
            n = int(self.headers.get("Content-Length", 0))
            if n > 100_000:
                return self._send(413, {"error": "too large"})
            body = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/api/task":
                text = str(body.get("text", "")).strip()
                return self._send(200, {"started": bool(text) and agent.start(text)})
            if self.path == "/api/approve":
                return self._send(200, {"ok": safety.answer(body.get("id"), body.get("ok"))})
            if self.path == "/api/stop":
                safety.stop_event.set()
                return self._send(200, {"ok": True})
            self._send(404, {"error": "not found"})

    return ThreadingHTTPServer(("127.0.0.1", port), H), token
