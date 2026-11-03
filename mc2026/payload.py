"""Builds the analysis payload served by the API and written by `mc2026 export`."""
from datetime import datetime

from . import analysis

TRACKS = ("good", "soft", "heavy")


def load_inputs(db):
    horses = list(db.horses.find({}, {"_id": 0}).sort("no", 1))
    odds = list(db.odds.find({}, {"_id": 0}))
    tips = list(db.tips.find({"scratched": False}, {"_id": 0}))
    cfg = db.meta.find_one({"_id": "tip_config"})
    return horses, odds, tips, cfg


def run(db, track, persist=False, inputs=None):
    horses, odds, tips, cfg = inputs or load_inputs(db)
    result = analysis.analyse(horses, odds, tips, cfg["points"], cfg["tier_weight"], track=track)
    by_name = {h["name"]: h for h in horses}
    for m in result["metrics"]:
        m["horse"] = by_name[m["name"]]
    if persist:
        db.metrics.delete_many({})
        db.metrics.insert_many([{k: v for k, v in m.items() if k != "horse"} for m in result["metrics"]])
        db.bookmaker_summary.delete_many({})
        db.bookmaker_summary.insert_many([dict(b) for b in result["bookmakers"]])
    return result


def tipsters_with_selections(db):
    tipsters = list(db.tipsters.find({}, {"_id": 0}).sort("_id", 1))
    sels = {}
    for t in db.tips.find({}).sort("_id", 1):
        sels.setdefault((t["tipster"], t["outlet"]), []).append(
            {"horse": t["horse"], "kind": t["kind"], "rank": t.get("rank"), "scratched": t.get("scratched", False)})
    for t in tipsters:
        t["selections"] = sels.get((t["tipster"], t["outlet"]), [])
    return tipsters


def build_payload(db, default_track="soft"):
    inputs = load_inputs(db)
    tracks = {}
    for track in TRACKS:
        r = run(db, track, inputs=inputs)
        tracks[track] = {k: r[k] for k in ("metrics", "bookmakers", "full_books", "n_tipsters")}
    meta = {d["_id"]: d.get("items", []) for d in db.meta.find({"_id": {"$in": ["odds_not_captured", "tips_not_captured"]}})}
    latest = max((o["captured_at"] for o in inputs[1]), default=None)
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "latest_price_at": latest,
        "default_track": default_track,
        "race": db.race.find_one({"_id": "race"}, {"_id": 0}),
        "weights": analysis.WEIGHTS,
        "tracks": tracks,
        "odds": inputs[1],
        "tipsters": tipsters_with_selections(db),
        "odds_not_captured": meta.get("odds_not_captured", []),
        "tips_not_captured": meta.get("tips_not_captured", []),
        "plan": analysis.betting_plan(tracks[default_track]["metrics"], budget=100.0),
    }
