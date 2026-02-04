import os
from typing import Optional
from notion_client import Client

def _get_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val

NOTION_TOKEN = _get_env("NOTION_TOKEN")
NOTION_RESEARCH_DB_ID = _get_env("NOTION_RESEARCH_DB_ID")
# Present for completeness; not used in this starter kit yet.
NOTION_QUEUE_DB_ID = os.environ.get("NOTION_QUEUE_DB_ID", "")

notion = Client(auth=NOTION_TOKEN)

def create_research_entry(
    title: str,
    url: str,
    source: str,
    published_date_iso: Optional[str] = None,
) -> None:
    properties = {
        "Title": {"title": [{"text": {"content": title}}]},
        "URL": {"url": url},
        "Source": {"select": {"name": (source[:100] if source else "Unknown")}},
        "Processed": {"checkbox": False},
        "Use in Draft": {"checkbox": False},
    }
    if published_date_iso:
        properties["Published Date"] = {"date": {"start": published_date_iso}}

    notion.pages.create(
        parent={"database_id": NOTION_RESEARCH_DB_ID},
        properties=properties,
    )
