import os
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List

from openai import OpenAI
import tiktoken

from notion_api import (
    query_top_draft_sources,
    get_prop_text,
    get_prop_url,
    set_content_queue_properties,
    create_content_queue_page,
    append_section,
)

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
MAX_INPUT_TOKENS = int(os.environ.get("MAX_INPUT_TOKENS", "9000"))
MAX_OUTPUT_TOKENS = int(os.environ.get("MAX_OUTPUT_TOKENS", "3200"))
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "14"))
MAX_SOURCES = int(os.environ.get("MAX_SOURCES", "8"))

client = OpenAI()

def truncate_to_tokens(text: str, limit: int) -> str:
    enc = tiktoken.encoding_for_model(MODEL)
    toks = enc.encode(text)
    return enc.decode(toks[:limit])

def monday_week_of_iso(now_utc: datetime) -> str:
    # Monday of current week in UTC (works fine for Week Of label)
    monday = now_utc - timedelta(days=now_utc.weekday())
    return monday.date().isoformat()

def llm_build_weekly_package(sources: List[Dict[str, Any]]) -> Dict[str, Any]:
    compiled = []
    for s in sources:
        title = get_prop_text(s, "Title")
        url = get_prop_url(s, "URL")
        summary = get_prop_text(s, "Summary")
        claims = get_prop_text(s, "Key Claims")
        compiled.append({
            "title": title,
            "url": url,
            "summary": summary,
            "key_claims": claims,
        })

    prompt = f"""
Return ONLY valid JSON with keys:
- article_title: string
- thesis_angle: string (1-2 sentences)
- long_form_article: string (1000-1300 words)
- companion_posts: array of 3 strings (each 120-220 words, distinct angles)
- comment_prompts: array of 5 strings (each 1-2 sentences, high-signal questions)
- sources: array of objects: {{title, url}}

Tone:
- Operational modernization + AI transformation leader
- Keep "TPM" visible where relevant (execution systems, governance, cross-functional operating model)
Rules:
- Do NOT invent stats or citations.
- Only cite from the provided sources list.
- If a claim can’t be grounded, phrase it as opinion/interpretation.

Provided sources (use ONLY these URLs):
{json.dumps(compiled, ensure_ascii=False)}
""".strip()

    msg = truncate_to_tokens(prompt, MAX_INPUT_TOKENS)

    resp = client.chat.completions.create(
        model=MODEL,
        temperature=0.3,
        max_tokens=MAX_OUTPUT_TOKENS,
        messages=[
            {"role": "system", "content": "You are a precise operator. Output strict JSON only."},
            {"role": "user", "content": msg},
        ],
    )

    raw = (resp.choices[0].message.content or "").strip()
    # tolerate code fences
    if raw.startswith("```"):
        raw = raw.strip("`").replace("json", "", 1).strip()

    return json.loads(raw)

def format_sources(sources: List[Dict[str, str]]) -> str:
    lines = []
    for s in sources:
        t = (s.get("title") or "").strip()
        u = (s.get("url") or "").strip()
        if u:
            lines.append(f"- {t} — {u}" if t else f"- {u}")
    return "\n".join(lines).strip()

def main():
    now = datetime.now(timezone.utc)
    lookback = (now - timedelta(days=LOOKBACK_DAYS)).date().isoformat()
    week_of = monday_week_of_iso(now)

    items = query_top_draft_sources(lookback_iso=lookback, max_sources=MAX_SOURCES)

    if not items:
        print(f"No draft-ready sources found (Use in Draft = True) in last {LOOKBACK_DAYS} days.")
        return

    pkg = llm_build_weekly_package(items)

    article_title = pkg["article_title"].strip()
    thesis_angle = pkg["thesis_angle"].strip()
    long_form = pkg["long_form_article"].strip()
    companion_posts = "\n\n---\n\n".join([p.strip() for p in pkg.get("companion_posts", [])])
    comment_prompts = "\n".join([f"- {c.strip()}" for c in pkg.get("comment_prompts", [])])
    sources_text = format_sources(pkg.get("sources", []))

    # Create Content Queue page (properties short; content appended as blocks)
    page_id = create_content_queue_page(title=article_title, week_of_iso=week_of, status="Draft")
    set_content_queue_properties(page_id=page_id, thesis_angle=thesis_angle)

    append_section(page_id, "Long-form Article", long_form)
    append_section(page_id, "Companion Posts", companion_posts)
    append_section(page_id, "Comment Prompts", comment_prompts)
    append_section(page_id, "Sources", sources_text)

    print(f"[OK] Created Content Queue draft: {article_title}")

if __name__ == "__main__":
    main()
