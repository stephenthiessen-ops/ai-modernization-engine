import feedparser
from rss_sources import RSS_FEEDS
from config import RECENCY_DAYS, ENABLE_KEYWORD_FILTER, KEYWORDS, DEDUPE_DB_PATH, MAX_MATCH_TEXT_CHARS
from notion_api import create_research_entry
from utils import init_dedupe_db, already_seen, mark_seen, parse_published, is_within_days, safe_text

def matches_keywords(title: str, summary: str) -> bool:
    haystack = (title + "\n" + summary).lower()
    return any(kw.lower() in haystack for kw in KEYWORDS)

def ingest():
    conn = init_dedupe_db(DEDUPE_DB_PATH)

    ingested = 0
    skipped_seen = 0
    skipped_old = 0
    skipped_kw = 0
    errors = 0

    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        feed_title = (feed.feed.get("title") or "Unknown").strip()

        for entry in feed.entries:
            url = entry.get("link")
            if not url:
                continue

            if already_seen(conn, url):
                skipped_seen += 1
                continue

            published_dt = parse_published(entry)
            if not is_within_days(published_dt, RECENCY_DAYS):
                skipped_old += 1
                continue

            title = (entry.get("title") or "").strip()
            summary = safe_text(entry.get("summary", "") or entry.get("description", "") or "", MAX_MATCH_TEXT_CHARS)

            if ENABLE_KEYWORD_FILTER and not matches_keywords(title, summary):
                skipped_kw += 1
                # mark seen to avoid reprocessing noise each run
                mark_seen(conn, url)
                continue

            try:
                create_research_entry(
                    title=title if title else url,
                    url=url,
                    source=feed_title,
                    published_date_iso=published_dt.isoformat() if published_dt else None,
                )
                ingested += 1
            except Exception as e:
                errors += 1
                print(f"[ERROR] Notion create failed for {url}: {e}")
                continue

            mark_seen(conn, url)

    print(f"Ingest complete. ingested={ingested} skipped_seen={skipped_seen} skipped_old={skipped_old} skipped_kw={skipped_kw} errors={errors}")

if __name__ == "__main__":
    ingest()
