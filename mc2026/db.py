import os

from pymongo import ASCENDING, MongoClient

MONGO_URI = os.environ.get("MC2026_MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("MC2026_DB", "melbourne_cup_2026")


def get_db():
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    client.admin.command("ping")
    return client[DB_NAME]


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
