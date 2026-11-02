from datetime import datetime


def money(v):
    return "-" if v is None else "$%.2f" % v


def pct(v, digits=1):
    return "-" if v is None else ("%." + str(digits) + "f%%") % (100 * v)


def books(names):
    return ", ".join(names) if names else "-"


def render(race, result, plan, tipsters, odds_gaps, tip_gaps, generated_at=None):
    metrics = result["metrics"]
    generated_at = generated_at or datetime.now().strftime("%Y-%m-%d %H:%M")
    out = []
    w = out.append

    w("# Melbourne Cup 2026 - Picks, Best Odds and Betting Strategy")
    w("")
    w("_%s, %s, %s, %dm. Generated %s. Track assumption for the model: **%s** (morning report: %s)._"
      % (race["name"], race["venue"], race["start_time"], race["distance_m"], generated_at,
         result["track"], race["track_condition_morning"]))
    w("")
    w("> **Prices move all morning.** Every price below has a timestamp and source. Check the live price with the bookmaker before you bet.")
    w("")

    w("## 1. Top picks")
    w("")
    w("The model blends three signals: **%d%% bookmaker market** (margin-free implied probability averaged across %d full-field books), "
      "**%d%% tipster consensus** (%d tipsters, experts weighted 2x celebrities) and **%d%% form** (recent figures, career strike rate, "
      "stamina, barrier, weight, track)."
      % (100 * result["weights"]["market"], len(result["full_books"]), 100 * result["weights"]["tips"],
         result["n_tipsters"], 100 * result["weights"]["form"]))
    w("")
    w("| Rank | No | Horse | Barrier | Kg | Model chance | Fair odds | Best AU price (bookie) | Value at best AU price | Tips (expert top picks) |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    for m in metrics[:10]:
        ev = m["ev_best_au"]
        w("| %d | %d | **%s** | %d | %.1f | %s | %s | %s (%s) | %s | %d (%d) |" % (
            m["model_rank"], m["no"], m["name"], m["barrier"], m["weight_kg"], pct(m["model_prob"]),
            money(m["fair_odds"]), money(m["best_au_price"]), books(m["best_au_bookmaker"]),
            ("+" if ev and ev > 0 else "") + pct(ev, 0) if ev is not None else "-",
            m["tip"]["mentions"], m["tip"]["expert_top_picks"]))
    w("")
    top = metrics[:4]
    w("**Top four in order:** " + ", ".join("%s (%d)" % (m["name"], m["no"]) for m in top) + ".")
    overlays = [m for m in metrics[:12] if m["ev_best_au"] and m["ev_best_au"] > 0]
    if overlays:
        w("")
        w("**Value (overlays)** - the model rates these more likely to win than the best Australian price implies: "
          + ", ".join("%s at %s" % (m["name"], money(m["best_au_price"])) for m in overlays) + ".")
    w("")

    w("## 2. Which bookies have the best odds")
    w("")
    w("### Best price per horse")
    w("")
    w("| No | Horse | TAB (Tue 10am) | Ladbrokes | bet365 (UK) | Best AU price | Best AU bookie | Best price anywhere | Ladbrokes place |")
    w("|---|---|---|---|---|---|---|---|---|")
    for m in sorted(metrics, key=lambda x: x["no"]):
        w("| %d | %s | %s | %s | %s | **%s** | %s | %s (%s) | %s |" % (
            m["no"], m["name"], money(m["tab_price"]), money(m["prices"].get("Ladbrokes")), money(m["bet365_price"]),
            money(m["best_au_price"]), books(m["best_au_bookmaker"]), money(m["best_price"]), books(m["best_bookmaker"]),
            money(m["ladbrokes_place"])))
    w("")
    w("### Bookmaker comparison")
    w("")
    w("A lower overround means a smaller bookmaker margin, so better value across the whole field. The top-8 price index compares the book's prices on the model's top 8 against the average price (above 1.00 is better than average).")
    w("")
    w("| Bookmaker | Region | Captured | Runners | Overround | Best price on (any) | Best AU price on | Top-8 price index |")
    w("|---|---|---|---|---|---|---|---|")
    for b in result["bookmakers"]:
        w("| %s | %s | %s | %d | %s | %d | %s | %s |" % (
            b["bookmaker"], b["region"], b["captured_at"].replace("T", " ")[:16], b["runners_priced"],
            pct(b["overround"] - 1) if b["overround"] else "partial",
            b["best_price_count"], b["best_au_price_count"] if b["region"] == "AU" else "-",
            "%.3f" % b["top8_price_index"] if b["top8_price_index"] else "-"))
    au = [b for b in result["bookmakers"] if b["region"] == "AU" and b["overround"]]
    if au:
        best = min(au, key=lambda b: b["overround"])
        w("")
        w("**Sharpest full Australian book:** %s (overround %s). Shop each horse individually, though; the best price per horse is in the table above."
          % (best["bookmaker"], pct(best["overround"] - 1)))
    if odds_gaps:
        w("")
        w("Not captured:")
        for g in odds_gaps:
            w("- **%s**: %s" % (g["bookmaker"], g["reason"]))
    w("")

    w("### Market movers (TAB, Monday 12:30pm to Tuesday 10am)")
    w("")
    movers = [m for m in metrics if m["tab_movement"] is not None and abs(m["tab_movement"]) >= 0.08]
    movers.sort(key=lambda m: m["tab_movement"], reverse=True)
    w("| Horse | Mon | Tue | Change in implied chance |")
    w("|---|---|---|---|")
    for m in movers:
        w("| %s | %s | %s | %s%s |" % (m["name"], money(m["tab_prev_price"]), money(m["tab_price"]),
                                     "+" if m["tab_movement"] > 0 else "", pct(m["tab_movement"], 0)))
    w("")

    w("## 3. Tipster consensus")
    w("")
    w("%d tipsters across Australian newspapers (SMH/The Age), Nine/Wide World of Sports, racing websites, ESPN, UK papers and Nine's personality panel. "
      "Points: 1st pick 4, 2nd 3, 3rd 2, other ranked 1, shortlist 2, each-way/roughie/place/exotic 1; celebrity panel weighted 0.5."
      % result["n_tipsters"])
    w("")
    w("| Horse | Mentions | Expert mentions | Top picks (expert) | Weighted points | Share of points | % of tipsters naming it |")
    w("|---|---|---|---|---|---|---|")
    for m in sorted(metrics, key=lambda x: x["tip"]["points"], reverse=True):
        t = m["tip"]
        if not t["mentions"]:
            continue
        w("| %s | %d | %d | %d (%d) | %.1f | %s | %s |" % (
            m["name"], t["mentions"], t["expert_mentions"], t["top_picks"], t["expert_top_picks"], t["points"],
            pct(t["share"]), pct(t["coverage"], 0)))
    w("")
    w("<details><summary>Every tipster's selections</summary>")
    w("")
    w("| Tipster | Outlet | Tier | Selections |")
    w("|---|---|---|---|")
    for t in tipsters:
        sels = []
        for s in t["selections"]:
            label = ("%d. " % s["rank"]) if s["kind"] == "ranked" else ""
            suffix = "" if s["kind"] == "ranked" else " (%s)" % s["kind"].replace("_", "-")
            sels.append(label + s["horse"] + suffix)
        w("| %s | [%s](%s) | %s | %s |" % (t["tipster"], t["outlet"], t["url"], t["tier"], "; ".join(sels)))
    w("")
    w("</details>")
    w("")
    if tip_gaps:
        for g in tip_gaps:
            w("- " + g)
        w("- Selections for the scratched Defiantly are excluded.")
        w("")

    w("## 4. Form snapshot")
    w("")
    w("| No | Horse | Last 5 | Career (st-1-2-3) | Stamina | Track pref | Form score |")
    w("|---|---|---|---|---|---|---|")
    for m in sorted(metrics, key=lambda x: x["form_score"], reverse=True):
        w("| %d | %s | %s | %s | %s | %s | %.2f |" % (
            m["no"], m["name"], m["horse"]["last_form"], m["horse"]["career"], m["horse"]["stamina"],
            {1: "wet ok", 0: "neutral", -1: "wants dry"}[m["horse"]["wet_track"]], m["form_score"]))
    w("")

    w("## 5. Suggested betting strategy (example $%d budget)" % plan["budget"])
    w("")
    w("Win bets are sized at quarter-Kelly against the model's chance, capped at half the budget, and placed at the best Australian price. "
      "Runners at $10 or longer are suggested each-way, since a 24-runner Cup pays places generously.")
    w("")
    w("| Bet | Horse | Stake | Price | Where | Ladbrokes place | Model chance | Edge |")
    w("|---|---|---|---|---|---|---|---|")
    for s in plan["singles"]:
        stake = ("$%d win + $%d place" % (s["unit"], s["unit"])) if s["bet"] == "Each-way" else "$%d" % s["unit"]
        w("| %s | %s (%d) | %s | %s | %s | %s | %s | %s |" % (
            s["bet"], s["name"], s["no"], stake, money(s["price"]), books(s["bookmaker"]),
            money(s["place_price"]), pct(s["model_prob"]), pct(s["ev"], 0) if s["ev"] is not None else "-"))
    w("")
    for e in plan["exotics"]:
        w("- **%s** %s: $%d for %d combinations = **%.1f%% flexi**." % (
            e["bet"], ", ".join("%d %s" % r for r in e["runners"]), e["stake"], e["combinations"], e["flexi_pct"]))
    w("")
    w("Total outlay: **$%d** of the $%d budget. The rest stays in reserve; only add to a runner if its price drifts past its fair odds in section 1."
      % (plan["total_staked"], plan["budget"]))
    w("")
    w("**How to use this:**")
    w("")
    w("1. Bet each horse with whichever bookie has the best price at the time; differences of $1-$3 are common on Cup Day.")
    w("2. Hopewell Rock and the wet-trackers (James J Braddock, Mr Monaco, So You Are) improve if more rain falls; Point Of Law, Trustyourinstinct, Goodie Two Shoes and Zahrann prefer it drier. Re-run with `--track heavy` or `--track good` once the final rating is announced.")
    w("3. Confirm Shockletz's rider (Harry Coffey's collarbone) before backing her.")
    w("4. Use bookmaker Cup Day promotions (money back for 2nd/3rd, best tote/best fixed) on the top two picks where available.")
    w("")

    w("## Caveats")
    w("")
    w("- The model probabilities are a structured opinion, not a guarantee. The Cup is a 24-runner handicap and favourites rarely win (the last winning favourite was Fiorente in 2013).")
    w("- UK bookmaker prices are shown for comparison only; they are not available to Australian customers.")
    w("- This is for entertainment. Set a limit and stick to it. Gambling Help Online: 1800 858 858 or gamblinghelponline.org.au.")
    w("")
    return "\n".join(out) + "\n"
