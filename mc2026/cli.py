import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

from . import analysis, payload, report, seed as seeding
from .db import DB_NAME, get_db, safe_uri

ROOT = Path(__file__).resolve().parent.parent


def run_analysis(db, track):
    return payload.run(db, track, persist=True)


def cmd_seed(args):
    db = get_db()
    summary = seeding.seed(db)
    print("Seeded %s/%s:" % (safe_uri(), DB_NAME))
    for k, v in summary.items():
        print("  %s: %s" % (k, v))


def cmd_report(args):
    db = get_db()
    result = run_analysis(db, args.track)
    plan = analysis.betting_plan(result["metrics"], budget=args.budget)
    db.plans.replace_one({"_id": "latest"}, {"_id": "latest", "track": args.track, **json.loads(json.dumps(plan))}, upsert=True)
    race = db.race.find_one({"_id": "race"})
    tipsters = payload.tipsters_with_selections(db)
    odds_gaps = (db.meta.find_one({"_id": "odds_not_captured"}) or {}).get("items", [])
    tip_gaps = (db.meta.find_one({"_id": "tips_not_captured"}) or {}).get("items", [])
    md = report.render(race, result, plan, tipsters, odds_gaps, tip_gaps)
    out = Path(args.out) if args.out else ROOT / "reports" / "melbourne_cup_2026_report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print("Report written to %s" % out)
    print("Top picks: " + ", ".join("%d. %s (%.1f%%)" % (m["model_rank"], m["name"], 100 * m["model_prob"]) for m in result["metrics"][:4]))


def cmd_top(args):
    db = get_db()
    result = run_analysis(db, args.track)
    print("%-4s %-3s %-20s %8s %8s %8s %8s  %s" % ("Rank", "No", "Horse", "Model", "Market", "Tips", "Form", "Best AU price"))
    for m in result["metrics"][: args.n]:
        print("%-4d %-3d %-20s %7.1f%% %7.1f%% %7.1f%% %7.1f%%  $%.2f (%s)" % (
            m["model_rank"], m["no"], m["name"], 100 * m["model_prob"], 100 * m["market_prob"],
            100 * m["tip"]["share"], 100 * m["form_prob"], m["best_au_price"] or 0, ", ".join(m["best_au_bookmaker"])))


def cmd_export(args):
    db = get_db()
    data = payload.build_payload(db, default_track=args.track)
    out = Path(args.out) if args.out else ROOT / "public" / "data.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
    print("Exported %d horses x %d track conditions to %s" % (len(data["tracks"]["soft"]["metrics"]), len(data["tracks"]), out))


def cmd_add_odds(args):
    db = get_db()
    prices = {}
    if args.csv:
        with open(args.csv, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                prices[row["horse"].strip()] = float(row["price"])
    for item in args.price or []:
        horse, price = item.rsplit("=", 1)
        prices[horse.strip()] = float(price)
    if not prices:
        sys.exit("No prices given. Use --price 'Horse=8.5' or --csv file.csv")
    captured = args.captured_at or datetime.now().astimezone().isoformat(timespec="seconds")
    n = seeding.add_odds(db, args.bookmaker, args.region, args.market, captured, prices, source=args.source)
    print("Recorded %d %s prices for %s at %s" % (n, args.market, args.bookmaker, captured))


def main(argv=None):
    p = argparse.ArgumentParser(prog="mc2026", description="Melbourne Cup 2026 odds, tips and form analyser")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("seed", help="Load data/*.json into MongoDB (replaces odds and tips)")
    s.set_defaults(func=cmd_seed)

    for name, func, helptext in (("report", cmd_report, "Analyse and write the Markdown report"),
                                 ("top", cmd_top, "Print the model's top picks")):
        r = sub.add_parser(name, help=helptext)
        r.add_argument("--track", choices=["good", "soft", "heavy"], default="soft")
        if name == "report":
            r.add_argument("--budget", type=float, default=100.0)
            r.add_argument("--out")
        else:
            r.add_argument("-n", type=int, default=10)
        r.set_defaults(func=func)

    e = sub.add_parser("export", help="Export analysis for all track conditions to public/data.json (offline fallback for the website)")
    e.add_argument("--track", choices=["good", "soft", "heavy"], default="soft")
    e.add_argument("--out")
    e.set_defaults(func=cmd_export)

    a = sub.add_parser("add-odds", help="Record a fresh price snapshot for a bookmaker")
    a.add_argument("--bookmaker", required=True)
    a.add_argument("--region", default="AU")
    a.add_argument("--market", choices=["win", "place"], default="win")
    a.add_argument("--price", action="append", help="'Horse Name=8.5' (repeatable)")
    a.add_argument("--csv", help="CSV with columns horse,price")
    a.add_argument("--captured-at")
    a.add_argument("--source", default="manual entry")
    a.set_defaults(func=cmd_add_odds)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
