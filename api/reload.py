import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mc2026.db import get_db  # noqa: E402
from mc2026.providers import ReloadBusy, SourceError, reload_providers  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._send(405, {"error": "Use POST to reload providers"})

    def do_POST(self):
        key = os.environ.get("MC2026_RELOAD_KEY", "")
        if not 32 <= len(key) <= 256:
            self._send(503, {"error": "Provider reload is disabled until an admin key is configured"})
            return
        supplied = self.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied.encode("utf-8"), ("Bearer " + key).encode("utf-8")):
            self._send(401, {"error": "Invalid admin reload key"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 256:
                self._send(413, {"error": "Request is too large"})
                return
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                self._send(415, {"error": "Expected application/json"})
                return
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict) or set(body) != {"confirm"} or body["confirm"] is not True:
                raise ValueError()
        except (ValueError, UnicodeDecodeError):
            self._send(400, {"error": "Confirm the provider import before continuing"})
            return
        try:
            result = reload_providers(get_db())
        except ReloadBusy as error:
            self._send(429, {"error": str(error)})
        except SourceError as error:
            self._send(502, {"error": str(error)})
        except Exception:
            self._send(503, {"error": "Atlas import could not be confirmed. Refresh saved data before retrying."})
        else:
            self._send(200, result)

    def _send(self, status, body):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        if status == 405:
            self.send_header("Allow", "POST")
        self.end_headers()
        self.wfile.write(data)
