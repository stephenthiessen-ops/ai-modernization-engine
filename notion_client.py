import os
from typing import Optional, List, Dict, Any
from notion_client import Client

def _get_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val

NOTION_TOKEN = _get_env("NOTION_TOKEN")
NOTION_RESEARCH_DB_ID = _get_env("NOTION_RESEARCH_DB_ID")
NOTION_QUEUE_DB_ID = os.environ.get("NOTION_QUEUE_DB_ID", "")

notion = Client(auth=NOTION_TOKEN)

def create_research_entry(title: str, url: str, source: str, published_date_iso: Optional[str] = None) -> None:
    properties = {
        "Title": {"title": [{"text": {"content": title}}]},
        "URL": {"url": url},
        "Source": {"select": {"name": (source[:100] if source else "Unknown")}},
        "Processed": {"checkbox": False},
        "Use in Draft": {"checkbox": False},
    }
    if published_date_iso:
        properties["Published Date"] = {"date": {"start": published_date_iso}}

    notion.pages.create(parent={"database_id": NOTION_RESEARCH_DB_ID}, properties=properties)

def query_unprocessed_research(limit: int = 20) -> List[Dict[str, Any]]:
    resp = notion.databases.query(
        database_id=NOTION_RESEARCH_DB_ID,
        filter={"property": "Processed", "checkbox": {"equals": False}},
        page_size=limit,
    )
    return resp.get("results", [])

def update_research_page(
    page_id: str,
    summary: str,
    key_claims: str,
    tags: List[str],
    usefulness_score: float,
    use_in_draft: bool,
    processed: bool = True,
) -> None:
    # Multi-select tags: create names
    tag_objs = [{"name": t[:50]} for t in tags if t]

    props = {
        "Summary": {"rich_text": [{"text": {"content": summary[:2000]}}]},
        "Key Claims": {"rich_text": [{"text": {"content": key_claims[:2000]}}]},
        "Tags": {"multi_select": tag_objs},
        "Usefulness Score": {"number": float(usefulness_score)},
        "Use in Draft": {"checkbox": bool(use_in_draft)},
        "Processed": {"checkbox": bool(processed)},
    }

    notion.pages.update(page_id=page_id, properties=props)

def get_prop_text(page: Dict[str, Any], prop_name: str) -> str:
    props = page.get("properties", {})
    p = props.get(prop_name, {})
    # Title
    if p.get("type") == "title":
        parts = p.get("title", [])
        return "".join([x.get("plain_text", "") for x in parts]).strip()
    # Rich text
    if p.get("type") == "rich_text":
        parts = p.get("rich_text", [])
        return "".join([x.get("plain_text", "") for x in parts]).strip()
    return ""

def get_prop_url(page: Dict[str, Any], prop_name: str) -> str:
    p = page.get("properties", {}).get(prop_name, {})
    if p.get("type") == "url":
        return p.get("url") or ""
    return ""

def get_prop_select(page: Dict[str, Any], prop_name: str) -> str:
    p = page.get("properties", {}).get(prop_name, {})
    if p.get("type") == "select" and p.get("select"):
        return p["select"].get("name") or ""
    return ""
