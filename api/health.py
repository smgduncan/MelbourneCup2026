import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mc2026.db import DB_NAME, get_db  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            db = get_db()
            body = {"ok": True, "database": DB_NAME, "horses": db.horses.count_documents({}),
                    "odds": db.odds.count_documents({}), "tips": db.tips.count_documents({})}
            status = 200
        except Exception as exc:
            body, status = {"ok": False, "type": type(exc).__name__}, 503
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)
