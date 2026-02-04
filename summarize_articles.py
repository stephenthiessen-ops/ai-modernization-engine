"""
summarize_articles.py

- Queries Notion Research Library for rows where Processed == False
- Fetches each URL and extracts a small excerpt (cost control)
- Scores relevance locally (no extra LLM calls)
- Calls OpenAI Chat Completions ONCE per article to produce JSON
- Updates Notion with Summary, Key Claims, Tags, Usefulness Score, Use in Draft, Processed

Env vars required:
- NOTION_TOKEN
- NOTION_RESEARCH_DB_ID
- OPENAI_API_KEY

Optional:
- OPENAI_MODEL (default: gpt-4o-mini)
- MAX_INPUT_TOKENS (default: 2500)
- MAX_OUTPUT_TOKENS (default: 350)
- BATCH_LIMIT (default: 15)
"""

import os
import json
import re
from typing import List, Dict, Any, Optional

from openai import OpenAI
import tiktoken

from notion_api import (
    query_unprocessed_research,
    update_research_page,
    get_prop_text,
    get_prop_url,
    get_prop_select,
)
from extractor import fetch_html, extract_text_blocks, build_excerpt
from relevance import score_relevance
from config import KEYWORDS

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
MAX_INPUT_TOKENS = int(os.environ.get("MAX_INPUT_TOKENS", "2500"))
MAX_OUTPUT_TOKENS = int(os.environ.get("MAX_OUTPUT_TOKENS", "350"))
BATCH_LIMIT = int(os.environ.get("BATCH_LIMIT", "15"))
MIN_EXCERPT_CHARS = int(os.environ.get("MIN_EXCERPT_CHARS", "500"))

client = OpenAI()


def truncate_to_tokens(text: str, limit: int) -> str:
    enc = tiktoken.encoding_for_model(MODEL)
    toks = enc.encode(text)
    return enc.decode(toks[:limit])


def get_published_iso(page: Dict[str, Any]) -> Optional[str]:
    try:
        p = page.get("properties", {}).get("Published Date", {})
        if p.get("type") == "date" and p.get("date"):
            return p["date"].get("start")
    except Exception:
        return None
    return None


def _extract_json(raw: str) -> Dict[str, Any]:
    """
    Robust JSON extraction:
    - handles code fences
    - handles leading/trailing text
    - extracts first {...} object found
    """
    if not raw:
        raise ValueError("Empty model response")

    raw = raw.strip()

    # Strip ```json ... ``` fences
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()

    # If the whole thing is JSON, parse directly
    try:
        return json.loads(raw)
    except Exception:
        pass

    # Fallback: find first JSON object in text
    m = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if not m:
        raise ValueError("No JSON object found in response")

    candidate = m.group(0)
    return json.loads(candidate)


def llm_summarize_json(title: str, url: str, excerpt: str) -> Dict[str, Any]:
    """
    Uses Chat Completions. We instruct 'JSON only' and then robustly extract JSON.
    """
    prompt = f"""
Return ONLY valid JSON with keys:
- summary_bullets: array of 5 strings
- key_claims: array of 3 strings
- tags: array of 3-6 strings
- confidence: number between 0 and 1

Rules:
- Do NOT invent statistics.
- If excerpt is insufficient, write conservative claims and lower confidence.
- Keep each bullet/claim under 25 words.
- No markdown. No commentary. JSON only.

Title: {title}
URL: {url}

EXCERPT:
{excerpt}
""".strip()

    msg = truncate_to_tokens(prompt, MAX_INPUT_TOKENS)

    resp = client.chat.completions.create(
        model=MODEL,
        temperature=0.2,
        max_tokens=MAX_OUTPUT_TOKENS,
        messages=[
            {"role": "system", "content": "You output strict JSON only."},
            {"role": "user", "content": msg},
        ],
    )

    raw = (resp.choices[0].message.content or "").strip()
    try:
        return _extract_json(raw)
    except Exception:
        print("RAW MODEL OUTPUT (first 500 chars):", raw[:500])
        raise


def run(batch_limit: int = BATCH_LIMIT) -> None:
    pages = query_unprocessed_research(limit=batch_limit)

    if not pages:
        print("No unprocessed research rows found. Nothing to do.")
        return

    for page in pages:
        page_id = page["id"]
        title = get_prop_text(page, "Title")
        url = get_prop_url(page, "URL")
        source = get_prop_select(page, "Source")
        published_iso = get_published_iso(page)

        # Skip / optionally mark processed if URL is missing
        if not url:
            print(f"[SKIP] Missing URL for page_id={page_id} (marking processed)")
            update_research_page(
                page_id=page_id,
                summary="(No URL found; skipped.)",
                key_claims="",
                tags=[],
                usefulness_score=0.0,
                use_in_draft=False,
                processed=True,
            )
            continue

        try:
            html = fetch_html(url)
            page_title, headings, paragraphs = extract_text_blocks(html)

            effective_title = title or page_title or url
            excerpt = build_excerpt(
                title=effective_title,
                headings=headings,
                paragraphs=paragraphs,
                keywords=KEYWORDS,
            )

            if len(excerpt) < MIN_EXCERPT_CHARS:
                raise ValueError(f"Excerpt too short ({len(excerpt)} chars). Likely paywalled/blocked.")

            # Local score (free)
            score, matched = score_relevance(
                title=effective_title,
                excerpt=excerpt,
                source=source,
                published_iso=published_iso,
            )

            # LLM summary (1 call)
            out = llm_summarize_json(effective_title, url, excerpt)

            summary_bullets = out.get("summary_bullets", []) or []
            key_claims = out.get("key_claims", []) or []
            tags = out.get("tags", []) or (matched[:6] if matched else [])
            confidence = float(out.get("confidence", 0.5))

            summary = "\n".join([f"- {b}" for b in summary_bullets])[:1900]
            claims = "\n".join([f"- {c}" for c in key_claims])[:1900]

            use_in_draft = bool(score >= 70.0 and confidence >= 0.6)

            update_research_page(
                page_id=page_id,
                summary=summary,
                key_claims=claims,
                tags=tags,
                usefulness_score=score,
                use_in_draft=use_in_draft,
                processed=True,
            )

            print(f"[OK] {effective_title[:70]} | score={score:.1f} conf={confidence:.2f} use={use_in_draft}")

        except Exception as e:
            print(f"Error:  {url} -> {e}")


if __name__ == "__main__":
    run()
