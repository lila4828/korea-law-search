import os
import sqlite3
from functools import lru_cache

DB_PATH = os.environ.get("DB_PATH", "data/medilaw.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


@lru_cache(maxsize=1)
def _shared_conn() -> sqlite3.Connection:
    return get_conn()


def db() -> sqlite3.Connection:
    return _shared_conn()
