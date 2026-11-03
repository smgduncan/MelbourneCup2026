import os
from pathlib import Path
from urllib.parse import urlsplit

from pymongo import ASCENDING, MongoClient


def _load_dotenv():
    env = Path(__file__).resolve().parent.parent / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv()

MONGO_URI = os.environ.get("MC2026_MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("MC2026_DB", "melbourne_cup_2026")

_client = None


def safe_uri():
    """Connection target without credentials, for logging."""
    return urlsplit(MONGO_URI).hostname or MONGO_URI


def get_db():
    # Reused across invocations so warm serverless functions skip the TLS/SRV handshake.
    global _client
    if _client is None:
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000)
        _client.admin.command("ping")
    return _client[DB_NAME]


def ensure_indexes(db):
    db.horses.create_index([("no", ASCENDING)], unique=True)
    db.horses.create_index([("name", ASCENDING)], unique=True)
    db.odds.create_index(
        [("bookmaker", ASCENDING), ("market", ASCENDING), ("captured_at", ASCENDING), ("horse", ASCENDING)],
        unique=True,
    )
    db.odds.create_index([("horse", ASCENDING), ("current", ASCENDING)])
    db.tipsters.create_index([("tipster", ASCENDING), ("outlet", ASCENDING)], unique=True)
    db.tips.create_index([("tipster", ASCENDING), ("outlet", ASCENDING), ("horse", ASCENDING), ("kind", ASCENDING)], unique=True)
    db.metrics.create_index([("name", ASCENDING)], unique=True)
