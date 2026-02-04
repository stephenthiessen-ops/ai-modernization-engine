"""
build_weekly_draft.py

Weekly Draft Builder
- Prevent duplicates: skip if a Content Queue entry already exists for the current Week Of
- Topic rotation: deterministic weekly topic based on ISO week number
- Pull top research items (Use in Draft == True, recent) and lightly bias toward topic affinity
- Generate a weekly LinkedIn draft package (long-form article + companion posts + comment prompts + sources)
- Write result to Notion Content Queue as a new page with appended blocks (chunked)

Required env vars:
- NOTION_TOKEN
- NOTION_RESEARCH_DB_ID
- NOTION_QUEUE_DB_ID
- OPENAI_API_KEY

Optional env vars:
- OPENAI_MODEL (default: gpt-4o-mini)
- MAX_INPUT_TOKENS (default: 9000)
- MAX_OUTPUT_TOKENS (default: 3200)
- LOOKBACK_DAYS (default: 14)
- MAX_SOURCES (default: 8)
"""

import os
import json
import re
import ast
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple

from openai import OpenAI
import tiktoken

from notion_api import (
    query_top_draft_sources,
    get_prop_text,
    get_prop_url,
    create_content_queue_page,
    set_content_queue_properties,
    append_section,
    find_content_queue_page_for_week,
)

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
MAX_INPUT_TOKENS = int(os.environ.get("MAX_INPUT_TOKENS", "9000"))
MAX_OUTPUT_TOKENS = int(os.environ.get("MAX_OUTPUT_TOKENS", "3200"))
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "14"))
MAX_SOURCES = int(os.environ.get("MAX_SOURCES", "8"))

client = OpenAI()

# ------------------------
# Topic rotation (editable)
# ------------------------
TOPIC_ROTATION: List[Dict[str, Any]] = [
    {
        "name": "Operating Model & Governance",
        "keywords": ["operating model", "governance", "portfolio", "prioritization", "decision rights", "alignment"],
        "angle": "How operating model clarity and governance mechanisms increase decision velocity and execution reliability.",
    },
    {
        "name": "AI-Enabled Program Management",
        "keywords": ["program management", "technical program management", "portfolio", "planning", "roadmap", "delivery", "execution systems", "AI"],
        "angle": "How AI augments TPM practice: signal synthesis, dependency management, risk surfacing, and narrative clarity.",
    },
    {
        "name": "Platform Engineering & Modernization",
        "keywords": ["platform", "platform engineering", "modernization", "architecture", "reliability", "observability", "internal developer platform"],
        "angle": "Modernization as an execution strategy: platforms, reliability, and enabling teams to ship safely at speed.",
    },
    {
        "name": "Workflow Automation & Agentic Ops",
        "keywords": ["automation", "agentic", "agents", "workflow", "orchestration", "ops", "productivity"],
        "angle": "From automation to agentic operations: where to draw boundaries, how to govern, and what to operationalize first.",
    },
    {
        "name": "Metrics, Signals & Decision Velocity",
        "keywords": ["metrics", "signals", "decision velocity", "observability", "measurement", "outcomes", "risk", "leading indicators"],
        "angle": "Using the right signals to manage coordination debt, improve prioritization, and accelerate decisions.",
    },
]


def truncate_to_tokens(text: str, limit: int) -> str:
    enc = tiktoken.encoding_for_model(MODEL)
    toks = enc.encode(text)
    return enc.decode(toks[:limit])


def monday_week_of_iso(now_utc: datetime) -> str:
    # Monday of current week in UTC (used for Week Of property)
    monday = now_utc - timedelta(days=now_utc.weekday())
    return monday.date().isoformat()


def pick_topic_for_week(week_of_iso: str) -> Dict[str, Any]:
    # Deterministic rotation by ISO week number
    dt = datetime.fromisoformat(week_of_iso).date()
    iso_week = dt.isocalendar().week
    idx = iso_week % len(TOPIC_ROTATION)
    return TOPIC_ROTATION[idx]


def extract_json(raw: str) -> Dict[str, Any]:
    """
    Robust extraction:
    1) Strip code fences
    2) Try strict json.loads
    3) Extract first {...} and try again
    4) Repair common JSON issues (trailing commas)
    5) Final fallback: parse as Python literal (single quotes, etc.)
    """
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Empty model response")

    # Strip code fences if present
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()

    # 1) strict parse
    try:
        return json.loads(raw)
    except Exception:
        pass

    # 2) first object
    m = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if not m:
        raise ValueError("No JSON object found in response")
    candidate = m.group(0)

    # 3) strict parse candidate
    try:
        return json.loads(candidate)
    except Exception:
        pass

    # 4) repair trailing commas
    repaired = re.sub(r",\s*([}\]])", r"\1", candidate)
    try:
        return json.loads(repaired)
    except Exception:
        pass

    # 5) python literal fallback
    obj = ast.literal_eval(repaired)
    if not isinstance(obj, dict):
        raise ValueError("Parsed object is not a dict")
    return obj


def score_source_for_topic(title: str, summary: str, claims: str, topic_keywords: List[str]) -> float:
    """
    Lightweight topical affinity score (free).
    """
    text = (title + "\n" + summary + "\n" + claims).lower()
    hits = sum(1 for kw in topic_keywords if kw.lower() in text)
    return float(hits)


def llm_build_weekly_package(topic: Dict[str, Any], sources: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    One LLM call for the whole weekly package.
    Uses only Title/URL/Summary/Key Claims (cheap + citeable).
    """
    compiled: List[Dict[str, str]] = []
    for s in sources:
        compiled.append(
            {
                "title": get_prop_text(s, "Title"),
                "url": get_prop_url(s, "URL"),
                "summary": get_prop_text(s, "Summary"),
                "key_claims": get_prop_text(s, "Key Claims"),
            }
        )

    prompt = f"""
Return ONLY valid JSON with keys:
- article_title: string
- thesis_angle: string (1-2 sentences)
- long_form_article: string (1000-1300 words)
- companion_posts: array of 3 strings (each 120-220 words, distinct angles)
- comment_prompts: array of 5 strings (each 1-2 sentences, high-signal questions)
- sources: array of objects: {{title, url}}

Topic for this week: {topic["name"]}
Thesis guidance: {topic["angle"]}

Tone:
- Operational modernization + AI transformation leader
- Keep "TPM" visible where relevant (execution systems, governance, cross-functional operating model)

Rules:
- Do NOT invent stats or citations.
- Only cite from the provided sources list (URLs below).
- If a claim can’t be grounded, phrase it as opinion/interpretation.
- Include a short “What this means for TPMs” section in the long-form article.
- No markdown fences. No backticks. JSON only.

Provided sources (use ONLY these URLs):
{json.dumps(compiled, ensure_ascii=False)}
""".strip()

    msg = truncate_to_tokens(prompt, MAX_INPUT_TOKENS)

    resp = client.chat.completions.create(
        model=MODEL,
        temperature=0.3,
        max_tokens=MAX_OUTPUT_TOKENS,
        messages=[
            {"role": "system", "content": "You output strict JSON only."},
            {"role": "user", "content": msg},
        ],
    )

    raw = (resp.choices[0].message.content or "").strip()
    try:
        return extract_json(raw)
    except Exception:
        print("RAW MODEL OUTPUT (first 1200 chars):", raw[:1200])
        raise


def format_sources(sources: List[Dict[str, str]]) -> str:
    lines: List[str] = []
    for s in sources:
        t = (s.get("title") or "").strip()
        u = (s.get("url") or "").strip()
        if u:
            lines.append(f"- {t} — {u}" if t else f"- {u}")
    return "\n".join(lines).strip()


def main() -> None:
    now = datetime.now(timezone.utc)
    week_of = monday_week_of_iso(now)

    # -------------------------
    # Duplicate prevention
    # -------------------------
    existing = find_content_queue_page_for_week(week_of)
    if existing:
        print(f"[SKIP] Draft already exists for week_of={week_of}. page_id={existing}")
        return

    # Topic rotation
    topic = pick_topic_for_week(week_of)
    print(f"[INFO] Weekly topic: {topic['name']} (week_of={week_of})")

    # Pull candidates from Research Library
    lookback = (now - timedelta(days=LOOKBACK_DAYS)).date().isoformat()
    candidates = query_top_draft_sources(lookback_iso=lookback, max_sources=max(20, MAX_SOURCES * 3))

    if not candidates:
        print(f"[SKIP] No draft-ready sources found (Use in Draft = True) in last {LOOKBACK_DAYS} days.")
        return

    # Light topical re-ranking: bias selection toward current topic while respecting usefulness score
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for c in candidates:
        t = get_prop_text(c, "Title")
        s = get_prop_text(c, "Summary")
        k = get_prop_text(c, "Key Claims")
        affinity = score_source_for_topic(t, s, k, topic["keywords"])

        # Pull usefulness score from Notion property (number)
        try:
            us = c["properties"]["Usefulness Score"]["number"] or 0.0
        except Exception:
            us = 0.0

        # Combined score: keep usefulness dominant, but topic affinity gives a nudge
        combined = (us * 1.0) + (affinity * 5.0)
        scored.append((combined, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    selected = [c for _, c in scored[:MAX_SOURCES]]

    # LLM build
    pkg = llm_build_weekly_package(topic, selected)

    article_title = pkg["article_title"].strip()
    thesis_angle = pkg["thesis_angle"].strip()
    long_form = pkg["long_form_article"].strip()
    companion_posts = "\n\n---\n\n".join([p.strip() for p in pkg.get("companion_posts", [])])
    comment_prompts = "\n".join([f"- {c.strip()}" for c in pkg.get("comment_prompts", [])])
    sources_text = format_sources(pkg.get("sources", []))

    # Create Content Queue page + append sections as blocks
    page_id = create_content_queue_page(
        title=article_title,
        week_of_iso=week_of,
        topic=topic["name"],
        status="Draft",
    )

    set_content_queue_properties(page_id=page_id, thesis_angle=thesis_angle)

    append_section(page_id, "Weekly Topic", topic["name"])
    append_section(page_id, "Thesis Angle", thesis_angle)
    append_section(page_id, "Long-form Article", long_form)
    append_section(page_id, "Companion Posts", companion_posts)
    append_section(page_id, "Comment Prompts", comment_prompts)
    append_section(page_id, "Sources", sources_text)

    print(f"[OK] Created Content Queue draft for week_of={week_of}: {article_title}")


if __name__ == "__main__":
    main()
