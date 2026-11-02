"""Turns raw horses / odds / tips into per-horse metrics and a model probability.

Pure functions only (lists of dicts in, dicts out) so they can be tested without MongoDB.
"""
from collections import defaultdict

FULL_BOOK_MIN_RUNNERS = 20

WEIGHTS = {"market": 0.5, "tips": 0.3, "form": 0.2}
FORM_WEIGHTS = {"recent": 0.30, "career": 0.15, "stamina": 0.20, "barrier": 0.15, "weight": 0.10, "track": 0.10}
FORM_SHARPNESS = 3

STAMINA_SCORE = {"proven": 1.0, "partial": 0.6, "unproven": 0.3}


def parse_form(form):
    """Last-start figures, oldest to newest. '0' = 10th or worse, 'x' = spell (ignored)."""
    runs = []
    for ch in form:
        if ch.isdigit():
            runs.append(10 if ch == "0" else int(ch))
    return runs


def recent_form_score(form):
    runs = parse_form(form)[-5:]
    if not runs:
        return 0.0
    weights = [5, 4, 3, 2, 1][: len(runs)]
    scores = [max(0.0, (10 - pos) / 9.0) for pos in reversed(runs)]
    return sum(w * s for w, s in zip(weights, scores)) / sum(weights)


def career_score(career):
    parts = [int(p) for p in career.split("-") if p != ""]
    starts = parts[0] if parts else 0
    if starts == 0:
        return 0.0
    wins = parts[1] if len(parts) > 1 else 0
    placings = sum(parts[1:4])
    # A 35% career strike rate is elite for a Cup stayer, so it maps to a full win score.
    return 0.6 * min(1.0, (wins / starts) / 0.35) + 0.4 * (placings / starts)


def barrier_score(barrier):
    if barrier <= 12:
        return 1.0
    if barrier <= 19:
        return 0.8
    return 0.3


def weight_score(weight):
    if weight <= 54.5:
        return 1.0
    if weight <= 56.5:
        return 0.8
    return 0.6


def track_score(wet_pref, track):
    """wet_pref: +1 likes rain, 0 neutral, -1 wants dry. track: good|soft|heavy."""
    severity = {"good": 0.0, "soft": 0.5, "heavy": 1.0}[track]
    return 0.5 + 0.5 * wet_pref * severity


def form_score(horse, track):
    parts = {
        "recent": recent_form_score(horse["last_form"]),
        "career": min(1.0, career_score(horse["career"])),
        "stamina": STAMINA_SCORE[horse["stamina"]],
        "barrier": barrier_score(horse["barrier"]),
        "weight": weight_score(horse["weight_kg"]),
        "track": track_score(horse["wet_track"], track),
    }
    total = sum(FORM_WEIGHTS[k] * v for k, v in parts.items())
    return total, parts


def group_snapshots(odds, market="win", current=True):
    books = defaultdict(dict)
    meta = {}
    for o in odds:
        if o["market"] != market or o["current"] != current:
            continue
        books[o["bookmaker"]][o["horse"]] = o["price"]
        meta[o["bookmaker"]] = {"region": o["region"], "captured_at": o["captured_at"], "source": o["source"], "url": o["url"]}
    return books, meta


def overround(prices):
    return sum(1.0 / p for p in prices.values())


def market_probabilities(books):
    """Average of margin-free implied probabilities across full-field books."""
    sums = defaultdict(float)
    full = [b for b, p in books.items() if len(p) >= FULL_BOOK_MIN_RUNNERS]
    for b in full:
        book = overround(books[b])
        for horse, price in books[b].items():
            sums[horse] += (1.0 / price) / book
    return {h: s / len(full) for h, s in sums.items()}, full


def tip_points(sel, points):
    if sel["kind"] == "ranked":
        return points["rank"].get(str(sel["rank"]), points["rank"]["default"])
    return points[sel["kind"]]


def tip_metrics(tips, names, points, tier_weight):
    out = {n: {"mentions": 0, "expert_mentions": 0, "top_picks": 0, "expert_top_picks": 0,
               "points": 0.0, "tipsters": []} for n in names}
    tipsters = set()
    for t in tips:
        if t["horse"] not in out:
            continue
        tipsters.add((t["tipster"], t["outlet"]))
        m = out[t["horse"]]
        m["mentions"] += 1
        m["tipsters"].append(t["tipster"])
        if t["tier"] == "expert":
            m["expert_mentions"] += 1
        if t["kind"] == "ranked" and t["rank"] == 1:
            m["top_picks"] += 1
            if t["tier"] == "expert":
                m["expert_top_picks"] += 1
        m["points"] += tip_points(t, points) * tier_weight[t["tier"]]
    total = sum(m["points"] for m in out.values()) or 1.0
    n_tipsters = len(tipsters) or 1
    for m in out.values():
        m["share"] = m["points"] / total
        m["coverage"] = len(set(m["tipsters"])) / n_tipsters
    return out, len(tipsters)


def kelly_fraction(p, odds):
    b = odds - 1.0
    return max(0.0, (p * odds - 1.0) / b) if b > 0 else 0.0


def analyse(horses, odds, tips, points, tier_weight, track="soft"):
    names = [h["name"] for h in horses]
    books, book_meta = group_snapshots(odds, "win", True)
    place_books, _ = group_snapshots(odds, "place", True)
    prev_books, _ = group_snapshots(odds, "win", False)
    market_p, full_books = market_probabilities(books)
    tipm, n_tipsters = tip_metrics(tips, names, points, tier_weight)

    raw_form = {}
    form_parts = {}
    for h in horses:
        raw_form[h["name"]], form_parts[h["name"]] = form_score(h, track)
    sharpened = {n: v ** FORM_SHARPNESS for n, v in raw_form.items()}
    s_total = sum(sharpened.values())
    form_p = {n: v / s_total for n, v in sharpened.items()}

    model = {n: WEIGHTS["market"] * market_p.get(n, 0) + WEIGHTS["tips"] * tipm[n]["share"] + WEIGHTS["form"] * form_p[n]
             for n in names}
    m_total = sum(model.values())
    model = {n: v / m_total for n, v in model.items()}

    metrics = []
    for h in horses:
        n = h["name"]
        prices = {b: p[n] for b, p in books.items() if n in p}
        au_prices = {b: p for b, p in prices.items() if book_meta[b]["region"] == "AU"}
        best_b, best_p = max(prices.items(), key=lambda kv: kv[1])
        best_au_b, best_au_p = max(au_prices.items(), key=lambda kv: kv[1]) if au_prices else (None, None)
        tab_now = books.get("TAB", {}).get(n)
        tab_prev = prev_books.get("TAB", {}).get(n)
        movement = None
        if tab_now and tab_prev:
            movement = (1 / tab_now - 1 / tab_prev) / (1 / tab_prev)
        p = model[n]
        metrics.append({
            "no": h["no"], "name": n, "barrier": h["barrier"], "weight_kg": h["weight_kg"],
            "jockey": h["jockey"], "trainer": h["trainer"],
            "prices": prices,
            "best_price": best_p, "best_bookmaker": [b for b, v in prices.items() if v == best_p],
            "best_au_price": best_au_p, "best_au_bookmaker": [b for b, v in au_prices.items() if v == best_au_p],
            "tab_price": tab_now, "tab_prev_price": tab_prev, "tab_movement": movement,
            "bet365_price": books.get("bet365 (UK)", {}).get(n),
            "ladbrokes_place": place_books.get("Ladbrokes", {}).get(n),
            "avg_price": sum(prices.values()) / len(prices),
            "market_prob": market_p.get(n, 0.0),
            "tip": tipm[n],
            "form_score": raw_form[n], "form_parts": form_parts[n], "form_prob": form_p[n],
            "model_prob": p,
            "fair_odds": 1.0 / p,
            "ev_best_au": (p * best_au_p - 1.0) if best_au_p else None,
            "kelly_au": kelly_fraction(p, best_au_p) if best_au_p else 0.0,
        })
    metrics.sort(key=lambda m: m["model_prob"], reverse=True)
    for i, m in enumerate(metrics, 1):
        m["model_rank"] = i

    bookmaker_summary = []
    for b, prices in books.items():
        best_count = sum(1 for m in metrics if b in m["best_bookmaker"])
        best_au_count = sum(1 for m in metrics if b in m["best_au_bookmaker"])
        top8 = [m for m in metrics[:8] if m["name"] in prices]
        rel = [prices[m["name"]] / m["avg_price"] for m in top8]
        bookmaker_summary.append({
            "bookmaker": b, "region": book_meta[b]["region"], "captured_at": book_meta[b]["captured_at"],
            "runners_priced": len(prices),
            "overround": overround(prices) if len(prices) >= FULL_BOOK_MIN_RUNNERS else None,
            "best_price_count": best_count, "best_au_price_count": best_au_count,
            "top8_price_index": (sum(rel) / len(rel)) if rel else None,
        })
    bookmaker_summary.sort(key=lambda s: (s["overround"] is None, s["overround"] or 0))

    return {"track": track, "metrics": metrics, "bookmakers": bookmaker_summary,
            "full_books": full_books, "n_tipsters": n_tipsters, "weights": WEIGHTS}


def betting_plan(metrics, budget=100.0, kelly_scale=0.25, win_cap=0.5):
    """Fractional-Kelly win/each-way bets on model overlays + exotic boxes on the top-rated runners."""
    candidates = [m for m in metrics[:8] if m["ev_best_au"] and m["ev_best_au"] > 0]
    raw = {m["name"]: m["kelly_au"] * kelly_scale * budget for m in candidates}
    total = sum(raw.values())
    scale = min(1.0, (win_cap * budget) / total) if total else 0
    singles = []
    def single(m, outlay):
        each_way = m["best_au_price"] >= 10
        unit = round(outlay / 2) if each_way else round(outlay)
        return {
            "name": m["name"], "no": m["no"], "bet": "Each-way" if each_way else "Win",
            "unit": unit, "cost": unit * 2 if each_way else unit,
            "price": m["best_au_price"], "bookmaker": m["best_au_bookmaker"],
            "place_price": m["ladbrokes_place"], "model_prob": m["model_prob"], "ev": m["ev_best_au"],
        }

    singles = [s for s in (single(m, raw[m["name"]] * scale) for m in candidates) if s["unit"] >= 2]
    if not singles:
        singles.append(single(metrics[0], 0.3 * budget))
    used = sum(s["cost"] for s in singles)
    remaining = budget - used
    tri_runners = metrics[:4]
    ff_runners = metrics[:6]
    tri_stake = round(min(0.2 * budget, remaining * 0.6))
    ff_stake = round(min(0.1 * budget, remaining - tri_stake))
    exotics = [
        {"bet": "Trifecta box", "runners": [(m["no"], m["name"]) for m in tri_runners], "combinations": 24,
         "stake": tri_stake, "flexi_pct": 100.0 * tri_stake / 24},
        {"bet": "First Four box", "runners": [(m["no"], m["name"]) for m in ff_runners], "combinations": 360,
         "stake": ff_stake, "flexi_pct": 100.0 * ff_stake / 360},
    ]
    return {"budget": budget, "singles": singles, "exotics": exotics,
            "total_staked": used + tri_stake + ff_stake}
