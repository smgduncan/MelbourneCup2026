import io
import json
import unittest
from unittest.mock import MagicMock, patch

from api.reload import handler
from mc2026 import providers

HORSES = [{"no": 1, "name": "Runner One"}, {"no": 2, "name": "Knight's Choice"}]
ODDS_HTML = """<h1>Melbourne Cup 2026 Odds</h1><p>Flemington R7</p>
<table><tr><td>1. Runner One (3)</td><td>9.00WIN 3.50PLACE</td></tr>
<tr><td>2. Knight’s Choice (2)</td><td>51.00 WIN 12.00 PLACE</td></tr></table>
<p>Data retrieved: 03/11/2026 09:30:03 AM (Australia/Brisbane)</p>"""
TIPS_HTML = """<h1>2026 Melbourne Cup Best Bets</h1><p>Published: Tue 3 Nov 2026 7:41am</p>
<h2>Best Bet</h2><h3>#1 Runner One @ $9.00</h3>
<h2>Best Each Way</h2><h3>#2 Knight's Choice @ $51.00</h3>
<h2>Best Roughie</h2><h3>#2 Knight's Choice @ $51.00</h3>"""


class ParserTests(unittest.TestCase):
    def test_complete_odds_and_source_timezone(self):
        snapshots = providers.parse_races(ODDS_HTML, HORSES, "2026-11-03")
        self.assertEqual(len(snapshots), 2)
        self.assertEqual(snapshots[0]["prices"]["Knight's Choice"], 51)
        self.assertEqual(snapshots[0]["captured_at"], "2026-11-03T09:30:03+10:00")

    def test_rejects_wrong_race_missing_runner_bad_price_or_timestamp(self):
        cases = [ODDS_HTML.replace("2026", "2025"), ODDS_HTML.replace("Knight’s Choice", "Unknown"),
                 ODDS_HTML.replace("51.00 WIN", "0.00 WIN"),
                 ODDS_HTML.replace("Data retrieved:", "Unknown:"),
                 ODDS_HTML.replace("<td>51.00 WIN 12.00 PLACE</td>", "")]
        for html in cases:
            with self.subTest(html=html), self.assertRaises(providers.SourceError):
                providers.parse_races(html, HORSES, "2026-11-03")

    def test_extracts_only_explicit_tip_categories(self):
        tipster = providers.parse_gobet(TIPS_HTML, HORSES, "2026-11-03")
        self.assertEqual([s["kind"] for s in tipster["selections"]], ["ranked", "each_way", "roughie"])
        self.assertEqual(tipster["published_at"], "2026-11-03T07:41:00+11:00")

    def test_changed_tips_layout_fails_closed(self):
        with self.assertRaises(providers.SourceError):
            providers.parse_gobet(TIPS_HTML.replace("Best Roughie", "Something else"), HORSES, "2026-11-03")

    def test_fetch_does_not_accept_user_supplied_urls(self):
        with patch("mc2026.providers.build_opener") as opener, self.assertRaises(providers.SourceError):
            providers.fetch_page("http://127.0.0.1/")
        opener.assert_not_called()

    def test_redirects_are_not_followed(self):
        self.assertIsNone(providers.NoRedirects().redirect_request(None, None, 302, "", {}, "http://127.0.0.1/"))

    def test_parser_failure_never_calls_save(self):
        db = MagicMock()
        db.meta.update_one.return_value.matched_count = 1
        db.race.find_one.return_value = {"date": "2026-11-03"}
        with patch("mc2026.providers.collect", side_effect=providers.SourceError("bad data")), \
                patch("mc2026.providers.save_import") as save, self.assertRaises(providers.SourceError):
            providers.reload_providers(db)
        save.assert_not_called()

    def test_database_cooldown_blocks_duplicate_import(self):
        db = MagicMock()
        db.meta.update_one.side_effect = providers.DuplicateKeyError("duplicate")
        with patch("mc2026.providers.collect") as collect, self.assertRaises(providers.ReloadBusy):
            providers.reload_providers(db)
        collect.assert_not_called()


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.db.client.start_session.return_value.__enter__.return_value.with_transaction.side_effect = lambda fn: fn("session")
        self.snapshots = providers.parse_races(ODDS_HTML, HORSES, "2026-11-03")
        self.tipster = providers.parse_gobet(TIPS_HTML, HORSES, "2026-11-03")
        self.batch = {"snapshots": self.snapshots, "tipster": self.tipster}
        self.db.tipsters.find_one.return_value = None
        self.db.tips.find.return_value = []
        self.db.odds.find.return_value = []

    def test_import_targets_only_supported_sources_and_preserves_history(self):
        old = {"horse": "Runner One", "kind": "shortlist", "rank": None, "scratched": False}
        self.db.tips.find.return_value = [old]
        result = providers.save_import(self.db, self.batch, "checked")
        self.assertEqual(len(result["updated"]), 3)
        self.assertEqual(self.db.odds.replace_one.call_count, 4)
        self.assertTrue(all(call.args[0]["bookmaker"] == "Ladbrokes" for call in self.db.odds.update_many.call_args_list))
        self.assertEqual(self.db.tips.delete_many.call_args.args[0], {"tipster": "Daryl Curnow", "outlet": "GoBet"})
        self.db.tip_history.insert_one.assert_called_once()
        self.db.odds.delete_many.assert_not_called()
        self.assertEqual(self.db.odds.replace_one.call_args.kwargs["session"], "session")

    def test_source_timestamp_equal_in_different_timezone_is_idempotent(self):
        existing = [{"horse": name, "price": value, "captured_at": "2026-11-03T10:30:03+11:00"}
                    for name, value in self.snapshots[0]["prices"].items()]
        self.db.odds.find.side_effect = [existing, []]
        providers.save_import(self.db, self.batch, "checked")
        self.assertEqual(self.db.odds.update_many.call_count, 1)
        self.assertEqual(self.db.odds.update_many.call_args.args[0]["market"], "place")

    def test_newer_saved_prices_are_not_overwritten(self):
        self.db.odds.find.return_value = [{"horse": "Runner One", "price": 5, "captured_at": "2026-11-03T12:00:00+11:00"}]
        providers.save_import(self.db, self.batch, "checked")
        self.db.odds.update_many.assert_not_called()
        self.db.odds.replace_one.assert_not_called()

    def test_conflicting_same_timestamp_aborts_transaction(self):
        self.db.odds.find.return_value = [{"horse": "Runner One", "price": 5, "captured_at": "2026-11-03T10:30:03+11:00"}]
        with self.assertRaises(providers.SourceError):
            providers.save_import(self.db, self.batch, "checked")
        self.db.odds.update_many.assert_not_called()
        self.db.meta.replace_one.assert_not_called()


class ReloadAPITests(unittest.TestCase):
    KEY = "test-admin-key-not-real-" + "x" * 32

    def request(self, token=None, body=b'{"confirm":true}', method="POST"):
        instance = handler.__new__(handler)
        instance.headers = {"Authorization": "Bearer " + (token if token is not None else self.KEY),
                            "Content-Type": "application/json", "Content-Length": str(len(body))}
        instance.rfile, instance.wfile = io.BytesIO(body), io.BytesIO()
        statuses, headers = [], {}
        instance.send_response = statuses.append
        instance.send_header = lambda key, value: headers.update({key: value})
        instance.end_headers = lambda: None
        getattr(instance, "do_" + method)()
        self.assertEqual(len(statuses), 1)
        self.assertEqual(headers["Cache-Control"], "no-store")
        return statuses[0], json.loads(instance.wfile.getvalue())

    @patch.dict("os.environ", {"MC2026_RELOAD_KEY": KEY})
    def test_unauthorised_never_reads_or_writes_database(self):
        with patch("api.reload.get_db") as db:
            self.assertEqual(self.request(token="wrong")[0], 401)
        db.assert_not_called()

    @patch.dict("os.environ", {"MC2026_RELOAD_KEY": ""})
    def test_disabled_without_key(self):
        with patch("api.reload.get_db") as db:
            self.assertEqual(self.request()[0], 503)
        db.assert_not_called()

    @patch.dict("os.environ", {"MC2026_RELOAD_KEY": KEY})
    def test_get_cannot_trigger_writes(self):
        with patch("api.reload.get_db") as db:
            self.assertEqual(self.request(method="GET")[0], 405)
        db.assert_not_called()

    @patch.dict("os.environ", {"MC2026_RELOAD_KEY": KEY})
    def test_requires_explicit_confirmation_and_bounded_body(self):
        for body, status in [(b"{}", 400), (b"{", 400), (b'{"confirm":1}', 400),
                             (b'{"confirm":true,"url":"http://localhost"}', 400), (b"x" * 257, 413)]:
            with self.subTest(body=body), patch("api.reload.get_db") as db:
                self.assertEqual(self.request(body=body)[0], status)
            db.assert_not_called()

    @patch.dict("os.environ", {"MC2026_RELOAD_KEY": KEY})
    def test_success_and_safe_provider_failure(self):
        with patch("api.reload.get_db"), patch("api.reload.reload_providers", return_value={"updated": []}):
            self.assertEqual(self.request()[0], 200)
        with patch("api.reload.get_db"), patch("api.reload.reload_providers", side_effect=RuntimeError("secret")):
            status, result = self.request()
        self.assertEqual(status, 503)
        self.assertNotIn("secret", json.dumps(result))

    @patch.dict("os.environ", {"MC2026_RELOAD_KEY": KEY})
    def test_cooldown_returns_429(self):
        with patch("api.reload.get_db"), patch("api.reload.reload_providers", side_effect=providers.ReloadBusy("Try later")):
            self.assertEqual(self.request()[0], 429)
