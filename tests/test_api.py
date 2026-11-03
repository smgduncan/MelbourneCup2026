import io
import json
import unittest
from unittest.mock import patch

from api.analysis import handler


class RefreshTests(unittest.TestCase):
    def request(self, method="POST", body=b"{}", path="/api/analysis"):
        instance = handler.__new__(handler)
        instance.path = path
        instance.headers = {"Content-Length": str(len(body))}
        instance.rfile = io.BytesIO(body)
        instance.wfile = io.BytesIO()
        headers = {}
        statuses = []
        instance.send_response = statuses.append
        instance.send_header = lambda key, value: headers.update({key: value})
        instance.end_headers = lambda: None
        getattr(instance, "do_" + method)()
        self.assertEqual(len(statuses), 1)
        return statuses[0], headers, json.loads(instance.wfile.getvalue())

    def test_refresh_reads_database_and_never_caches(self):
        payload = {"tracks": {"heavy": {"metrics": []}}}
        with patch("api.analysis.get_db", return_value="db"), \
                patch("api.analysis.build_payload", return_value=payload) as build, \
                patch("api.analysis.analysis.betting_plan", return_value={"budget": 321}):
            status, headers, data = self.request(body=b'{"track":"heavy","budget":321}')
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(data["plan"]["budget"], 321)
        build.assert_called_once_with("db", default_track="heavy")

    def test_get_keeps_short_shared_cache(self):
        with patch("api.analysis.get_db"), \
                patch("api.analysis.build_payload", return_value={"tracks": {"soft": {"metrics": []}}}), \
                patch("api.analysis.analysis.betting_plan", return_value={}):
            status, headers, _ = self.request(method="GET")
        self.assertEqual(status, 200)
        self.assertIn("s-maxage=60", headers["Cache-Control"])

    def test_invalid_input_does_not_touch_database(self):
        bodies = [b"{", b"[]", b'{"track":[]}', b'{"budget":"oops"}',
                  b'{"budget":null}', b'{"budget":-1}', b'{"budget":1e99}']
        for body in bodies:
            with self.subTest(body=body), patch("api.analysis.get_db") as db:
                status, headers, _ = self.request(body=body)
                self.assertEqual(status, 400)
                self.assertEqual(headers["Cache-Control"], "no-store")
                db.assert_not_called()

    def test_oversized_body_is_rejected(self):
        status, _, _ = self.request(body=b" " * 4097)
        self.assertEqual(status, 413)

    def test_database_error_does_not_leak_credentials(self):
        with patch("api.analysis.get_db", side_effect=RuntimeError("mongodb://secret")):
            status, headers, data = self.request()
        self.assertEqual(status, 503)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn("secret", json.dumps(data))
