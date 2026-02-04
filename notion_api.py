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

from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

def query_top_draft_sources(lookback_iso: str, max_sources: int = 8) -> List[Dict[str, Any]]:
    """
    Pull best research items for drafting:
    - Processed == True
    - Use in Draft == True
    - Published Date >= lookback_iso
    Sorted by Usefulness Score desc
    """
    resp = notion.databases.query(
        database_id=NOTION_RESEARCH_DB_ID,
        filter={
            "and": [
                {"property": "Processed", "checkbox": {"equals": True}},
                {"property": "Use in Draft", "checkbox": {"equals": True}},
                {"property": "Published Date", "date": {"on_or_after": lookback_iso}},
            ]
        },
        sorts=[{"property": "Usefulness Score", "direction": "descending"}],
        page_size=max_sources,
    )
    return resp.get("results", [])

def create_content_queue_page(title: str, week_of_iso: str, status: str = "Draft") -> str:
    """
    Create a new Content Queue page and return its page_id.
    Keep properties short; we’ll append large content as blocks.
    """
    if not NOTION_QUEUE_DB_ID:
        raise RuntimeError("Missing NOTION_QUEUE_DB_ID env var / secret.")

    page = notion.pages.create(
        parent={"database_id": NOTION_QUEUE_DB_ID},
        properties={
            "Title": {"title": [{"text": {"content": title}}]},
            "Week Of": {"date": {"start": week_of_iso}},
            "Status": {"select": {"name": status}},
        },
    )
    return page["id"]

def set_content_queue_properties(
    page_id: str,
    thesis_angle: str,
) -> None:
    notion.pages.update(
        page_id=page_id,
        properties={
            "Thesis Angle": {"rich_text": [{"text": {"content": thesis_angle[:2000]}}]},
        },
    )

def _chunk_text(text: str, max_len: int = 1800) -> List[str]:
    """
    Notion has practical limits on rich_text payload sizes per block.
    Chunk by paragraph first, then hard-split if needed.
    """
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    chunks: List[str] = []
    cur = ""

    for p in paras:
        if len(cur) + len(p) + 1 <= max_len:
            cur = (cur + "\n" + p).strip()
        else:
            if cur:
                chunks.append(cur)
            cur = p[:max_len]
            # if paragraph still too large, split
            while len(cur) > max_len:
                chunks.append(cur[:max_len])
                cur = cur[max_len:]
    if cur:
        chunks.append(cur)
    return chunks

def append_section(page_id: str, heading: str, body: str) -> None:
    """
    Appends:
    - Heading block
    - Paragraph blocks (chunked)
    """
    children = [{
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": heading}}]},
    }]

    for chunk in _chunk_text(body):
        children.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]},
        })

    notion.blocks.children.append(block_id=page_id, children=children)
