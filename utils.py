import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional
from datetime import datetime, timezone

def init_dedupe_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS seen_urls (
            url TEXT PRIMARY KEY,
            first_seen_utc TEXT NOT NULL
        )"""
    )
    conn.commit()
    return conn

def already_seen(conn: sqlite3.Connection, url: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM seen_urls WHERE url = ?", (url,))
    return cur.fetchone() is not None

def mark_seen(conn: sqlite3.Connection, url: str) -> None:
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO seen_urls(url, first_seen_utc) VALUES (?, ?)",
        (url, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()

def parse_published(entry) -> Optional[datetime]:
    published = entry.get("published_parsed") or entry.get("updated_parsed")
    if not published:
        return None
    return datetime(*published[:6], tzinfo=timezone.utc)

def is_within_days(dt: Optional[datetime], days: int) -> bool:
    if dt is None:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return dt >= cutoff

def safe_text(val: str, max_chars: int) -> str:
    if not val:
        return ""
    val = str(val).strip()
    return val[:max_chars]
