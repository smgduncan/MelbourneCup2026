import unittest

from mc2026 import analysis


def horse(name, no, **kw):
    base = {"name": name, "no": no, "barrier": 5, "weight_kg": 54.0, "jockey": "J", "trainer": "T",
            "last_form": "21111", "career": "10-3-2-1", "stamina": "proven", "wet_track": 0}
    base.update(kw)
    return base


def odds_doc(book, horse, price, region="AU", current=True, market="win"):
    return {"bookmaker": book, "horse": horse, "price": price, "region": region, "current": current,
            "market": market, "captured_at": "2026-11-03T10:00:00+11:00", "source": "test", "url": ""}


POINTS = {"rank": {"1": 4, "2": 3, "3": 2, "default": 1}, "shortlist": 2, "each_way": 1, "roughie": 1, "place": 1, "exotic": 1}
TIERS = {"expert": 1.0, "celebrity": 0.5}


class FormTests(unittest.TestCase):
    def test_parse_form_handles_spells_and_tenth_plus(self):
        self.assertEqual(analysis.parse_form("1x0 3"), [1, 10, 3])

    def test_recent_form_rewards_latest_win(self):
        self.assertGreater(analysis.recent_form_score("90001"), analysis.recent_form_score("10009"))

    def test_track_preference(self):
        self.assertEqual(analysis.track_score(1, "good"), 0.5)
        self.assertEqual(analysis.track_score(1, "heavy"), 1.0)
        self.assertEqual(analysis.track_score(-1, "heavy"), 0.0)


class MarketTests(unittest.TestCase):
    def test_market_probabilities_remove_margin(self):
        names = ["H%d" % i for i in range(20)]
        books = {"A": {n: 10.0 for n in names}}
        probs, full = analysis.market_probabilities(books)
        self.assertEqual(full, ["A"])
        self.assertAlmostEqual(sum(probs.values()), 1.0)

    def test_partial_books_excluded_from_market(self):
        names = ["H%d" % i for i in range(20)]
        books = {"A": {n: 10.0 for n in names}, "B": {"H0": 2.0}}
        _, full = analysis.market_probabilities(books)
        self.assertEqual(full, ["A"])


class AnalyseTests(unittest.TestCase):
    def setUp(self):
        self.horses = [horse("H%d" % i, i + 1) for i in range(20)]
        self.horses[0]["last_form"] = "11111"
        self.odds = [odds_doc("TAB", h["name"], 5.0 if h["no"] == 1 else 30.0) for h in self.horses]
        self.odds.append(odds_doc("UKBook", "H0", 9.0, region="UK"))
        self.odds.append(odds_doc("Ladbrokes", "H0", 6.0))
        self.tips = [{"tipster": "A", "outlet": "X", "tier": "expert", "horse": "H0", "kind": "ranked", "rank": 1}]

    def test_model_probabilities_sum_to_one(self):
        r = analysis.analyse(self.horses, self.odds, self.tips, POINTS, TIERS)
        self.assertAlmostEqual(sum(m["model_prob"] for m in r["metrics"]), 1.0)
        self.assertEqual(r["metrics"][0]["name"], "H0")

    def test_best_au_price_ignores_uk_books(self):
        r = analysis.analyse(self.horses, self.odds, self.tips, POINTS, TIERS)
        h0 = next(m for m in r["metrics"] if m["name"] == "H0")
        self.assertEqual(h0["best_price"], 9.0)
        self.assertEqual(h0["best_au_price"], 6.0)
        self.assertEqual(h0["best_au_bookmaker"], ["Ladbrokes"])

    def test_betting_plan_stays_within_budget(self):
        r = analysis.analyse(self.horses, self.odds, self.tips, POINTS, TIERS)
        plan = analysis.betting_plan(r["metrics"], budget=100)
        self.assertLessEqual(plan["total_staked"], 100)
        self.assertEqual(plan["exotics"][0]["combinations"], 24)

    def test_kelly_is_zero_without_edge(self):
        self.assertEqual(analysis.kelly_fraction(0.1, 5.0), 0.0)
        self.assertGreater(analysis.kelly_fraction(0.3, 5.0), 0.0)


if __name__ == "__main__":
    unittest.main()
