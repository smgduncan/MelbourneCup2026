"""Read narrowly supported public pages, validate, then atomically import to Atlas."""
import math
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from pymongo.errors import DuplicateKeyError

ODDS_URL = "https://www.races.com.au/melbourne-cup/melbourne-cup-odds/"
TIPS_URL = "https://www.gobet.com.au/horse-racing-tips/melbourne-cup-2026/"
MAX_BYTES = 2 * 1024 * 1024


class SourceError(ValueError):
    pass


class ReloadBusy(ValueError):
    pass


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_page(url):
    # Callers cannot supply URLs, headers or credentials. Fail closed on redirects.
    if url not in (ODDS_URL, TIPS_URL):
        raise SourceError("Unsupported provider URL")
    request = Request(url, headers={"User-Agent": "MelbourneCup2026/1.0 (public racing analysis)",
                                    "Accept": "text/html", "Cache-Control": "no-cache"})
    try:
        with build_opener(NoRedirects()).open(request, timeout=8) as response:
            if response.headers.get_content_type() != "text/html":
                raise SourceError("Provider did not return an HTML page")
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise SourceError("Provider page exceeds size limit")
            return body.decode(response.headers.get_content_charset() or "utf-8")
    except SourceError:
        raise
    except Exception:
        raise SourceError("Provider could not be reached; existing data was kept") from None


def normalise(name):
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise SourceError("Source timestamp must include its timezone")
    return parsed


def source_time(value, race_date):
    if value.date().isoformat() != race_date or value > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise SourceError("Provider timestamp is not for this race day")
    return value.isoformat(timespec="seconds")


def runner_lookup(horses):
    return {int(h["no"]): h["name"] for h in horses}


def runner_name(number, name, runners):
    canonical = runners.get(int(number))
    if not canonical or normalise(name) != normalise(canonical):
        raise SourceError("Provider runner does not match the saved field")
    return canonical


def valid_price(value):
    value = float(value)
    if not math.isfinite(value) or not 1 < value <= 10000:
        raise SourceError("Provider returned an invalid price")
    return value


def parse_races(html, horses, race_date):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    year = race_date[:4]
    if not re.search(r"Melbourne Cup\s+" + year, text, re.I) or not re.search(r"Flemington\s+R7", text, re.I):
        raise SourceError("Odds page is not the expected Melbourne Cup race")
    match = re.search(r"Data retrieved:\s*(\d{2}/\d{2}/\d{4}\s+\d{1,2}:\d{2}:\d{2}\s*[AP]M)\s*\(Australia/Brisbane\)", text, re.I)
    if not match:
        raise SourceError("Odds source capture timestamp was not found")
    captured = datetime.strptime(match[1], "%d/%m/%Y %I:%M:%S %p").replace(tzinfo=ZoneInfo("Australia/Brisbane"))
    captured_at = source_time(captured, race_date)
    runners = runner_lookup(horses)
    prices = {"win": {}, "place": {}}
    for row in soup.find_all("tr"):
        row_text = row.get_text(" ", strip=True)
        runner = re.search(r"(?:^|\s)(\d{1,2})\.\s*(.+?)\s*\(\d+\)", row_text)
        win = re.search(r"(\d+(?:\.\d+)?)\s*WIN\b", row_text, re.I)
        place = re.search(r"(\d+(?:\.\d+)?)\s*PLACE\b", row_text, re.I)
        if not runner or not win or not place:
            continue
        name = runner_name(runner[1], runner[2], runners)
        for market, value in (("win", win[1]), ("place", place[1])):
            price = valid_price(value)
            if name in prices[market] and prices[market][name] != price:
                raise SourceError("Conflicting prices for the same runner")
            prices[market][name] = price
    if any(set(book) != set(runners.values()) for book in prices.values()):
        raise SourceError("Odds page no longer contains the complete saved field")
    return [{"bookmaker": "Ladbrokes", "region": "AU", "market": market,
             "captured_at": captured_at, "source": "Races.com.au public Ladbrokes board",
             "url": ODDS_URL, "prices": book} for market, book in prices.items()]


def parse_gobet(html, horses, race_date):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.find("h1")
    if not title or not re.search(race_date[:4] + r"\s+Melbourne Cup", title.get_text(" ", strip=True), re.I):
        raise SourceError("Tips page is not the expected Melbourne Cup article")
    text = soup.get_text(" ", strip=True)
    match = re.search(r"Published:\s*[A-Za-z]{3}\s+(\d{1,2}\s+[A-Za-z]{3}\s+\d{4}\s+\d{1,2}:\d{2}\s*[ap]m)", text, re.I)
    if not match:
        raise SourceError("Tipster publication timestamp was not found")
    published = datetime.strptime(match[1].replace(" ", ""), "%d%b%Y%I:%M%p").replace(tzinfo=ZoneInfo("Australia/Sydney"))
    published_at = source_time(published, race_date)
    runners = runner_lookup(horses)
    selections = []
    for label, kind, rank in (("Best Bet", "ranked", 1), ("Best Each Way", "each_way", None),
                              ("Best Roughie", "roughie", None)):
        heading = next((h for h in soup.find_all(["h2", "h3"]) if h.get_text(" ", strip=True).casefold() == label.casefold()), None)
        next_heading = heading.find_next(["h2", "h3", "h4"]) if heading else None
        selection = re.fullmatch(r"#\s*(\d{1,2})\s+(.+?)\s*@\s*\$\s*[\d.]+",
                                 next_heading.get_text(" ", strip=True) if next_heading else "")
        if not selection:
            raise SourceError("Tipster selection headings have changed")
        name = runner_name(selection[1], selection[2], runners)
        selections.append({"horse": name, "kind": kind, "rank": rank, "scratched": False})
    return {"tipster": "Daryl Curnow", "outlet": "GoBet", "outlet_type": "Australian racing website",
            "tier": "expert", "published": race_date, "published_at": published_at,
            "url": TIPS_URL, "selections": selections}


def collect(horses, race_date):
    with ThreadPoolExecutor(max_workers=2) as executor:
        odds = executor.submit(fetch_page, ODDS_URL)
        tips = executor.submit(fetch_page, TIPS_URL)
        return {"snapshots": parse_races(odds.result(), horses, race_date),
                "tipster": parse_gobet(tips.result(), horses, race_date)}


def save_import(db, batch, checked_at):
    """Keep other providers untouched; roll all changes back on any write failure."""
    def write(session):
        updated = []
        for snapshot in batch["snapshots"]:
            query = {"bookmaker": snapshot["bookmaker"], "market": snapshot["market"]}
            existing = list(db.odds.find({**query, "current": True}, session=session))
            if existing and max(timestamp(o["captured_at"]) for o in existing) > timestamp(snapshot["captured_at"]):
                continue  # never replace newer manually entered prices with an older page
            same_time = [o for o in existing if timestamp(o["captured_at"]) == timestamp(snapshot["captured_at"])]
            if same_time:
                if {o["horse"]: o["price"] for o in same_time} != snapshot["prices"]:
                    raise SourceError("Source prices changed without a new capture timestamp")
                continue
            db.odds.update_many(query, {"$set": {"current": False}}, session=session)
            for horse, price in snapshot["prices"].items():
                document = {k: v for k, v in snapshot.items() if k != "prices"}
                document.update(horse=horse, price=price, current=True, fetched_at=checked_at)
                db.odds.replace_one({**query, "captured_at": snapshot["captured_at"], "horse": horse},
                                    document, upsert=True, session=session)
            db.bookmakers.update_one({"bookmaker": snapshot["bookmaker"]},
                                     {"$set": {"region": snapshot["region"]}}, upsert=True, session=session)
            updated.append("Ladbrokes " + snapshot["market"])
        tipster = batch["tipster"]
        identity = {"tipster": tipster["tipster"], "outlet": tipster["outlet"]}
        old = db.tipsters.find_one(identity, session=session)
        if not old or not old.get("published_at") or timestamp(old["published_at"]) <= timestamp(tipster["published_at"]):
            old_tips = list(db.tips.find(identity, {"_id": 0}, session=session))
            new_tips = [{**identity, "tier": tipster["tier"], "outlet_type": tipster["outlet_type"],
                         **s} for s in tipster["selections"]]
            fields = ("horse", "kind", "rank", "scratched")
            signature = lambda tips: sorted((str(tuple(t.get(k) for k in fields)) for t in tips))
            if signature(old_tips) != signature(new_tips):
                if old_tips:
                    db.tip_history.insert_one({**identity, "archived_at": checked_at,
                                               "selections": old_tips}, session=session)
                db.tips.delete_many(identity, session=session)
                db.tips.insert_many(new_tips, session=session)
                updated.append("GoBet selections")
            db.tipsters.replace_one(identity, {k: v for k, v in tipster.items() if k != "selections"},
                                    upsert=True, session=session)
        status = {"checked_at": checked_at, "updated": updated,
                  "sources": [{"name": "Ladbrokes via Races.com.au", "url": ODDS_URL,
                               "source_at": batch["snapshots"][0]["captured_at"]},
                              {"name": "GoBet best bet / each-way / roughie", "url": TIPS_URL,
                               "source_at": tipster["published_at"]}],
                  "note": "Only these sources were checked. Other bookmakers and tipsters were not updated."}
        db.meta.replace_one({"_id": "provider_reload"}, {"_id": "provider_reload", **status},
                            upsert=True, session=session)
        return status

    with db.client.start_session() as session:
        return session.with_transaction(write)


def reload_providers(db):
    now = datetime.now(timezone.utc)
    try:
        result = db.meta.update_one({"_id": "provider_reload_cooldown",
                                     "next_allowed_at": {"$lte": now}},
                                    {"$set": {"next_allowed_at": now + timedelta(seconds=60)}}, upsert=True)
    except DuplicateKeyError:
        raise ReloadBusy("A reload was started recently. Try again in 60 seconds.") from None
    if not result.matched_count and not result.upserted_id:
        raise ReloadBusy("A reload is already running")
    race = db.race.find_one({"_id": "race"})
    if not race or race.get("date") != "2026-11-03":
        raise SourceError("Saved race does not match the supported Melbourne Cup")
    horses = list(db.horses.find({}, {"_id": 0}))
    batch = collect(horses, race["date"])
    return save_import(db, batch, now.isoformat(timespec="seconds"))
