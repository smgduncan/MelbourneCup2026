import json
import math
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mc2026.db import get_db  # noqa: E402
from mc2026 import analysis  # noqa: E402
from mc2026.payload import TRACKS, build_payload  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = parse_qs(urlsplit(self.path).query)
        self._respond(params.get("track", ["soft"])[0], params.get("budget", ["100"])[0], fresh=False)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 4096:
                self._send_json(413, {"error": "request body too large"}, fresh=True)
                return
            raw = self.rfile.read(length) if length else b"{}"
            params = json.loads(raw.decode("utf-8"))
            if not isinstance(params, dict):
                raise ValueError("request body must be a JSON object")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            self._send_json(400, {"error": "invalid JSON request"}, fresh=True)
            return
        self._respond(params.get("track", "soft"), params.get("budget", 100), fresh=True)

    def _respond(self, track, budget, fresh):
        if not isinstance(track, str):
            self._send_json(400, {"error": "track or budget is out of range"}, fresh=True)
            return
        try:
            budget = float(budget)
        except (TypeError, ValueError):
            self._send_json(400, {"error": "track or budget is out of range"}, fresh=True)
            return
        if track not in TRACKS or not math.isfinite(budget) or not 1 <= budget <= 1000000:
            self._send_json(400, {"error": "track or budget is out of range"}, fresh=True)
            return
        try:
            result = build_payload(get_db(), default_track=track)
            result["plan"] = analysis.betting_plan(result["tracks"][track]["metrics"], budget=budget)
            self._send_json(200, result, fresh=fresh)
        except Exception as exc:  # keep credentials and stack traces out of the response
            self._send_json(503, {"error": "database unavailable", "type": type(exc).__name__}, fresh=True)

    def _send_json(self, status, body, fresh):
        data = json.dumps(body, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store" if fresh or status != 200 else "public, s-maxage=60, stale-while-revalidate=300")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
