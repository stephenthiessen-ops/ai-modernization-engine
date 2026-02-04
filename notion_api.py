"""
notion_api.py

IMPORTANT:
- This file name is intentionally NOT "notion_client.py" to avoid shadowing the
  pip package "notion_client" (from notion-client).

Provides:
- Create Research Library entries (RSS ingest)
- Query Research Library for summarization
- Update Research Library rows with summary/claims/tags/score flags
- Query top draft sources for weekly draft generation
- Create + update Content Queue pages
- Duplicate prevention (find existing Content Queue entry for a given Week Of)
- Append long content to a Content Queue page as Notion blocks (chunked)

Required env vars:
- NOTION_TOKEN
- NOTION_RESEARCH_DB_ID

Optional (required for weekly draft builder):
- NOTION_QUEUE_DB_ID
"""

import os
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta

from notion_client import Client


# -----------------------
# Environment / Client
# -----------------------
def _get_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val


NOTION_TOKEN = _get_env("NOTION_TOKEN")
NOTION_RESEARCH_DB_ID = _get_env("NOTION_RESEARCH_DB_ID")
NOTION_QUEUE_DB_ID = os.environ.get("NOTION_QUEUE_DB_ID", "")

notion = Client(auth=NOTION_TOKEN)


# -----------------------
# Research Library (RSS)
# -----------------------
def create_research_entry(
    title: str,
    url: str,
    source: str,
    published_date_iso: Optional[str] = None,
) -> None:
    """
    Create a new research row with minimal fields.
    """
    properties: Dict[str, Any] = {
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


def query_unprocessed_research(limit: int = 20) -> List[Dict[str, Any]]:
    """
    Pull rows where Processed == False.
    """
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
    """
    Update the research row with generated fields.
    Property names MUST match your Research Library database.
    """
    tag_objs = [{"name": t[:50]} for t in tags if t]

    props: Dict[str, Any] = {
        "Summary": {"rich_text": [{"text": {"content": (summary or "")[:2000]}}]},
        "Key Claims": {"rich_text": [{"text": {"content": (key_claims or "")[:2000]}}]},
        "Tags": {"multi_select": tag_objs},
        "Usefulness Score": {"number": float(usefulness_score)},
        "Use in Draft": {"checkbox": bool(use_in_draft)},
        "Processed": {"checkbox": bool(processed)},
    }

    notion.pages.update(page_id=page_id, properties=props)


# -----------------------
# Property helper getters
# -----------------------
def get_prop_text(page: Dict[str, Any], prop_name: str) -> str:
    props = page.get("properties", {})
    p = props.get(prop_name, {})

    if p.get("type") == "title":
        parts = p.get("title", [])
        return "".join([x.get("plain_text", "") for x in parts]).strip()

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


# ---------------------------------------------
# Research -> Weekly draft source selection
# ---------------------------------------------
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


# -----------------------
# Content Queue Helpers
# -----------------------
def find_content_queue_page_for_week(week_of_iso: str) -> Optional[str]:
    """
    Duplicate prevention:
    Returns page_id if a Content Queue entry already exists for the given Week Of date.
    """
    if not NOTION_QUEUE_DB_ID:
        raise RuntimeError("Missing NOTION_QUEUE_DB_ID env var / secret.")

    resp = notion.databases.query(
        database_id=NOTION_QUEUE_DB_ID,
        filter={"property": "Week Of", "date": {"equals": week_of_iso}},
        page_size=1,
    )
    results = resp.get("results", [])
    return results[0]["id"] if results else None


def create_content_queue_page(title: str, week_of_iso: str, topic: str, status: str = "Draft") -> str:
    """
    Create a new Content Queue page and return its page_id.
    Keeps properties small; large bodies are appended as blocks.
    """
    if not NOTION_QUEUE_DB_ID:
        raise RuntimeError("Missing NOTION_QUEUE_DB_ID env var / secret.")

    page = notion.pages.create(
        parent={"database_id": NOTION_QUEUE_DB_ID},
        properties={
            "Title": {"title": [{"text": {"content": title}}]},
            "Week Of": {"date": {"start": week_of_iso}},
            "Topic": {"select": {"name": topic}},
            "Status": {"select": {"name": status}},
        },
    )
    return page["id"]


def set_content_queue_properties(
    page_id: str,
    thesis_angle: str,
    long_form_draft: str = "",
    companion_posts: str = "",
    comment_prompts: str = "",
    sources: str = "",
) -> None:
    """
    Sets table-visible properties (snippets). Full content should still go in blocks.
    NOTE: These properties must exist in your Content Queue database with exact names:
      - Thesis Angle (rich_text)
      - Long-form Draft (rich_text)
      - Companion Posts (rich_text)
      - Comment Prompts (rich_text)
      - Sources (rich_text)
    """
    props = {
        "Thesis Angle": {"rich_text": [{"text": {"content": (thesis_angle or "")[:2000]}}]},
    }

    if long_form_draft:
        props["Long-form Draft"] = {"rich_text": [{"text": {"content": long_form_draft[:2000]}}]}
    if companion_posts:
        props["Companion Posts"] = {"rich_text": [{"text": {"content": companion_posts[:2000]}}]}
    if comment_prompts:
        props["Comment Prompts"] = {"rich_text": [{"text": {"content": comment_prompts[:2000]}}]}
    if sources:
        props["Sources"] = {"rich_text": [{"text": {"content": sources[:2000]}}]}

    notion.pages.update(page_id=page_id, properties=props)

# -----------------------
# Block append utilities
# -----------------------
def _chunk_text(text: str, max_len: int = 1800) -> List[str]:
    """
    Notion has practical limits for rich_text payload sizes per block.
    Chunk by paragraph, then hard-split if needed.
    """
    if not text:
        return [""]

    paras = [p.strip() for p in text.split("\n") if p.strip()]
    chunks: List[str] = []
    cur = ""

    for p in paras:
        # If the paragraph itself is massive, split it
        if len(p) > max_len:
            if cur:
                chunks.append(cur)
                cur = ""
            start = 0
            while start < len(p):
                chunks.append(p[start : start + max_len])
                start += max_len
            continue

        if len(cur) + len(p) + 1 <= max_len:
            cur = (cur + "\n" + p).strip()
        else:
            if cur:
                chunks.append(cur)
            cur = p

    if cur:
        chunks.append(cur)

    return chunks


def append_section(page_id: str, heading: str, body: str) -> None:
    """
    Appends:
    - Heading (H2)
    - Paragraph blocks (chunked)
    """
    children: List[Dict[str, Any]] = [
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": heading}}]},
        }
    ]

    for chunk in _chunk_text(body):
        children.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]},
            }
        )

    notion.blocks.children.append(block_id=page_id, children=children)
