import json
from pathlib import Path

from .db import ensure_indexes

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def load_json(name):
    with open(DATA_DIR / name, encoding="utf-8") as fh:
        return json.load(fh)


def seed(db):
    ensure_indexes(db)
    field = load_json("field.json")
    odds = load_json("odds.json")
    tips = load_json("tips.json")

    db.race.replace_one({"_id": "race"}, {"_id": "race", **field["race"]}, upsert=True)
    names = set()
    for horse in field["horses"]:
        names.add(horse["name"])
        db.horses.replace_one({"no": horse["no"]}, horse, upsert=True)

    db.bookmakers.delete_many({})
    db.odds.delete_many({})
    for snap in odds["snapshots"]:
        db.bookmakers.update_one(
            {"bookmaker": snap["bookmaker"]},
            {"$set": {"bookmaker": snap["bookmaker"], "region": snap["region"]}},
            upsert=True,
        )
        for horse, price in snap["prices"].items():
            if horse not in names:
                raise ValueError("Unknown horse in odds.json: %s" % horse)
            db.odds.insert_one({
                "bookmaker": snap["bookmaker"],
                "region": snap["region"],
                "market": snap["market"],
                "current": snap["current"],
                "captured_at": snap["captured_at"],
                "source": snap["source"],
                "url": snap["url"],
                "horse": horse,
                "price": float(price),
            })
    db.meta.replace_one(
        {"_id": "odds_not_captured"}, {"_id": "odds_not_captured", "items": odds.get("not_captured", [])}, upsert=True
    )

    db.tipsters.delete_many({})
    db.tips.delete_many({})
    scratched = []
    for t in tips["tipsters"]:
        db.tipsters.insert_one({k: v for k, v in t.items() if k != "selections"})
        for sel in t["selections"]:
            doc = {
                "tipster": t["tipster"],
                "outlet": t["outlet"],
                "outlet_type": t["outlet_type"],
                "tier": t["tier"],
                "horse": sel["horse"],
                "kind": sel["kind"],
                "rank": sel.get("rank"),
                "scratched": sel["horse"] not in names,
            }
            if doc["scratched"]:
                scratched.append("%s (%s)" % (sel["horse"], t["tipster"]))
            db.tips.insert_one(doc)
    db.meta.replace_one({"_id": "tip_config"}, {"_id": "tip_config", "points": tips["points"], "tier_weight": tips["tier_weight"]}, upsert=True)
    db.meta.replace_one({"_id": "tips_not_captured"}, {"_id": "tips_not_captured", "items": tips.get("not_captured", [])}, upsert=True)

    return {
        "horses": db.horses.count_documents({}),
        "odds": db.odds.count_documents({}),
        "bookmakers": db.bookmakers.count_documents({}),
        "tipsters": db.tipsters.count_documents({}),
        "tips": db.tips.count_documents({}),
        "scratched_tips": scratched,
    }


def add_odds(db, bookmaker, region, market, captured_at, prices, source="manual entry", url=""):
    """Record a new (current) price snapshot; older snapshots for the same bookmaker/market become history."""
    names = {h["name"] for h in db.horses.find({}, {"name": 1})}
    unknown = [h for h in prices if h not in names]
    if unknown:
        raise ValueError("Unknown horse(s): %s" % ", ".join(unknown))
    db.odds.update_many({"bookmaker": bookmaker, "market": market}, {"$set": {"current": False}})
    db.bookmakers.update_one({"bookmaker": bookmaker}, {"$set": {"bookmaker": bookmaker, "region": region}}, upsert=True)
    for horse, price in prices.items():
        db.odds.replace_one(
            {"bookmaker": bookmaker, "market": market, "captured_at": captured_at, "horse": horse},
            {"bookmaker": bookmaker, "region": region, "market": market, "current": True,
             "captured_at": captured_at, "source": source, "url": url, "horse": horse, "price": float(price)},
            upsert=True,
        )
    return len(prices)
