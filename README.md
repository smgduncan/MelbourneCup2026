# MelbourneCup2026

A small Python + MongoDB app that builds a database of the 2026 Lexus Melbourne Cup field, compares bookmaker odds, measures tipster consensus, scores form, and writes a report with top picks, the best bookie for each horse, and a suggested betting strategy.

**Latest report:** [`reports/melbourne_cup_2026_report.md`](reports/melbourne_cup_2026_report.md)

## What's in the database

MongoDB database `melbourne_cup_2026`:

| Collection | Contents |
|---|---|
| `race` | Race details, track condition, scratchings and notes |
| `horses` | All 24 runners: saddlecloth, barrier, weight, jockey, trainer, last-5 form, career record, stamina, wet-track preference, lead-up summary |
| `bookmakers` | Each bookmaker and its region (AU / UK) |
| `odds` | One document per bookmaker x market x snapshot x horse, with source URL and timestamp. `current: false` marks older snapshots (used for market movers) |
| `tipsters`, `tips` | Each tipster/outlet and every selection (ranked, shortlist, each-way, roughie, place, exotic) |
| `metrics` | Computed per-horse metrics: market probability, tip share, form score, model probability, fair odds, best prices, value |
| `bookmaker_summary` | Overround and best-price counts per bookmaker |
| `plans` | The latest suggested staking plan |

The raw, source-attributed data lives in `data/field.json`, `data/odds.json` and `data/tips.json`. Seeding is repeatable.

## Data sources (captured Cup morning, 3 Nov 2026)

- **Field and form:** race.com.au, JustHorseRacing, ABC, Sportstralia, ESPN, Races.com.au, Nine (TAB form guide).
- **Odds:** TAB (Tue 10am, plus Mon 12:30pm for movement), Ladbrokes win and place (via Races.com.au), JustHorseRacing (MyBet/Multis), GoBet (indicative), bet365 UK, Sky Bet, Betfred, BetGoodwin, AK Bets, William Hill, Betfair, BoyleSports, Spreadex.
- **Tipsters:** SMH/The Age (Danny Russell, Peter Ryan), Nine/Wide World of Sports (Simon O'Donnell, Francesca Cumani, David Gately), Races.com.au, ESPN, GoBet, Betsy, The Telegraph (UK), The Independent (UK), and Nine's personality panel.
- **Not captured:** bet365 Australia (prices only show to logged-in users), TAB's live API (geo-blocked outside Australia), Sportsbet/Neds (JavaScript-only), Herald Sun/Daily Telegraph panels (paywalled).

## How the model works

- **Market (50%):** each full-field book's implied probabilities are normalised to remove the bookmaker margin, then averaged.
- **Tips (30%):** 1st pick = 4 points, 2nd = 3, 3rd = 2, other ranked = 1, shortlist = 2, each-way/roughie/place/exotic = 1. Celebrity panel picks count half. Picks of scratched horses are dropped.
- **Form (20%):** weighted recent figures, career win/place rate, stamina (proven at 2800m+), barrier (no winner from gate 20+ since 2015), weight band, and track preference vs the chosen track condition.
- **Value:** `model chance x best Australian price - 1`. Positive = overlay.
- **Staking:** quarter-Kelly on overlays in the top 8 (capped at 50% of budget; each-way at $10+), plus a top-4 trifecta box and a top-6 first-four box with flexi percentages.

## Quick start

```bash
# MongoDB Community (macOS)
brew tap mongodb/brew && brew install mongodb-community
brew services start mongodb/brew/mongodb-community

python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

.venv/bin/python -m mc2026 seed                    # load data/*.json into MongoDB
.venv/bin/python -m mc2026 top                     # print the model's top 10
.venv/bin/python -m mc2026 report --track soft --budget 100
```

Set `MC2026_MONGO_URI` / `MC2026_DB` to use a different MongoDB server or database.

## Web app and Atlas backend

The responsive frontend lives in `public/`. Vercel serves the Python endpoints in
`api/`, which read MongoDB Atlas using server-side `MC2026_MONGO_URI` and
`MC2026_DB` environment variables. Never put database credentials in frontend
files or commit `.env`.

**Refresh odds & tips** sends an uncached `POST /api/analysis`, re-reads the
latest saved odds and tips from Atlas, and recalculates the analysis. It does
not scrape bookmakers or publishers. Add updated source data to Atlas first;
refresh does not change source capture timestamps or imply that old data is live.
If a refresh fails, the page keeps its last loaded data and displays an error.
On initial API failure it falls back to the clearly labelled `public/data.json`.

Track and example budget controls recalculate the analysis. Odds can be sorted,
and the page includes tipster selections, runner form and an example staking plan.
Regenerate the offline fallback after updating data:

```bash
.venv/bin/python -m mc2026 export
```

### Refreshing prices before the jump

Bookmaker sites block automated scraping, so add fresh prices by hand or from a CSV (`horse,price`):

```bash
.venv/bin/python -m mc2026 add-odds --bookmaker TAB --price "Hopewell Rock=6.5" --price "Point Of Law=9"
.venv/bin/python -m mc2026 add-odds --bookmaker "bet365 (AU)" --csv bet365.csv
.venv/bin/python -m mc2026 report --track heavy
```

`add-odds` marks the bookmaker's previous snapshot as history, so the report always uses the latest prices. `seed` resets odds and tips to the JSON snapshot.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -v
node tests/test_frontend.js
```

## Responsible gambling

This is a fun analysis, not financial advice. The Melbourne Cup is a 24-runner handicap, and models and tipsters get it wrong often. Set a limit you're comfortable losing. Free, confidential support: Gambling Help Online, 1800 858 858, gamblinghelponline.org.au.
