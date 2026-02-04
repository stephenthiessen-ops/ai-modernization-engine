"""
summarize_articles.py

Pipeline step:
- Query Notion Research Library for rows where Processed == False
- Fetch each URL
- Extract a small, keyword-aware excerpt (cost control)
- Score relevance locally (no extra LLM calls)
- Call OpenAI once per article to produce STRICT JSON (no parsing failures)
- Update the Notion row with Summary, Key Claims, Tags, Usefulness Score, Use in Draft, Processed

Required env vars:
- NOTION_TOKEN
- NOTION_RESEARCH_DB_ID
- OPENAI_API_KEY

Optional env vars:
- NOTION_QUEUE_DB_ID (not used in this script yet)
- OPENAI_MODEL (default: gpt-4o-mini)
- MAX_INPUT_TOKENS (default: 2500)
- MAX_OUTPUT_TOKENS (default: 350)
- BATCH_LIMIT (default: 15)
"""

import os
import json
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


# -----------------------
# Config (env controlled)
# -----------------------
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
MAX_INPUT_TOKENS = int(os.environ.get("MAX_INPUT_TOKENS", "2500"))
MAX_OUTPUT_TOKENS = int(os.environ.get("MAX_OUTPUT_TOKENS", "350"))
BATCH_LIMIT = int(os.environ.get("BATCH_LIMIT", "15"))

# Extraction sanity checks (avoid wasting calls on paywalls/blocked pages)
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


def llm_summarize_json(title: str, url: str, excerpt: str) -> Dict[str, Any]:
    """
    Uses OpenAI Responses API with JSON mode to guarantee valid JSON output.
    """
    prompt = f"""
You are an executive research analyst specializing in Operational Modernization and AI Transformation.

Return ONLY valid JSON with keys:
- summary_bullets: array of 5 bullets (strings)
- key_claims: array of 3 claims (strings)
- tags: array of 3-6 tags (strings). Prefer: operating model, modernization, portfolio governance, workflow automation, platform engineering, AI transformation, decision velocity, coordination debt
- confidence: number 0-1 indicating how well the excerpt supports the claims

Constraints:
- Do NOT invent statistics.
- If the excerpt is insufficient, write conservative claims and lower confidence.
- Keep each bullet/claim under 25 words.

Article Title: {title}
URL: {url}

EXCERPT:
{excerpt}
""".strip()

    msg = truncate_to_tokens(prompt, MAX_INPUT_TOKENS)

    resp = client.responses.create(
        model=MODEL,
        input=msg,
        temperature=0.2,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        response_format={"type": "json_object"},
    )

    raw = (resp.output_text or "").strip()
    if not raw:
        raise ValueError("Empty model response (output_text).")

    try:
        return json.loads(raw)
    except Exception:
        print("RAW MODEL OUTPUT (first 400 chars):", raw[:400])
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

        if not url:
            print(f"[SKIP] Missing URL for page_id={page_id}")
            continue

        try:
            # 1) Fetch + extract
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
                # Avoid wasting an LLM call on blocked/paywalled/JS-only pages
                raise ValueError(
                    f"Excerpt too short ({len(excerpt)} chars). Likely paywalled/blocked."
                )

            # 2) Local relevance scoring (free)
            score, matched = score_relevance(
                title=effective_title,
                excerpt=excerpt,
                source=source,
                published_iso=published_iso,
            )

            # 3) One LLM call for structured summary/claims/tags
            out = llm_summarize_json(effective_title, url, excerpt)

            summary_bullets = out.get("summary_bullets", []) or []
            key_claims = out.get("key_claims", []) or []
            tags = out.get("tags", []) or (matched[:6] if matched else [])
            confidence = float(out.get("confidence", 0.5))

            summary = "\n".join([f"- {b}" for b in summary_bullets])[:1900]
            claims = "\n".join([f"- {c}" for c in key_claims])[:1900]

            # 4) Decide whether it should be used in the weekly draft
            # Cost-efficient gating: combine local score + LLM confidence
            use_in_draft = bool(score >= 70.0 and confidence >= 0.6)

            # 5) Update Notion row
            update_research_page(
                page_id=page_id,
                summary=summary,
                key_claims=claims,
                tags=tags,
                usefulness_score=score,
                use_in_draft=use_in_draft,
                processed=True,
            )

            print(
                f"[OK] {effective_title[:70]} | score={score:.1f} conf={confidence:.2f} use={use_in_draft}"
            )

        except Exception as e:
            # Keep the row unprocessed so we can retry after fixes
            print(f"[ERROR] {url} -> {e}")


if __name__ == "__main__":
    run()
