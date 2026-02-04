import os
import json
from typing import List, Dict, Any
from openai import OpenAI
import tiktoken

from notion_client import query_unprocessed_research, update_research_page, get_prop_text, get_prop_url, get_prop_select
from extractor import fetch_html, extract_text_blocks, build_excerpt
from relevance import score_relevance
from config import KEYWORDS

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
MAX_INPUT_TOKENS = int(os.environ.get("MAX_INPUT_TOKENS", "2500"))
MAX_OUTPUT_TOKENS = int(os.environ.get("MAX_OUTPUT_TOKENS", "350"))

client = OpenAI()

def truncate_to_tokens(text: str, limit: int) -> str:
    enc = tiktoken.encoding_for_model(MODEL)
    toks = enc.encode(text)
    return enc.decode(toks[:limit])

def llm_summarize(title: str, url: str, excerpt: str) -> Dict[str, Any]:
    """
    Single call per article. Output is structured JSON to avoid parsing pain.
    """
    prompt = f"""
You are an executive research analyst specializing in Operational Modernization and AI Transformation.

Return ONLY valid JSON with keys:
- summary_bullets: array of 5 bullets (strings)
- key_claims: array of 3 claims (strings)
- tags: array of 3-6 tags (strings). Prefer: operating model, modernization, portfolio governance, workflow automation, platform engineering, AI transformation
- confidence: number 0-1 indicating how well the excerpt supports the claims

Constraints:
- Do NOT invent statistics.
- If the excerpt is insufficient, write conservative claims and lower confidence.

Article Title: {title}
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
            {"role": "system", "content": "You are precise, skeptical, and citation-conscious."},
            {"role": "user", "content": msg},
        ],
    )

    content = resp.choices[0].message.content.strip()
    return json.loads(content)

def run(batch_limit: int = 15):
    pages = query_unprocessed_research(limit=batch_limit)

    for page in pages:
        page_id = page["id"]
        title = get_prop_text(page, "Title")
        url = get_prop_url(page, "URL")
        source = get_prop_select(page, "Source")

        published_iso = None
        # Notion date property access (manual parse)
        try:
            p = page.get("properties", {}).get("Published Date", {})
            if p.get("type") == "date" and p.get("date"):
                published_iso = p["date"].get("start")
        except Exception:
            published_iso = None

        if not url:
            continue

        try:
            html = fetch_html(url)
            t2, headings, paragraphs = extract_text_blocks(html)
            effective_title = title or t2 or url
            excerpt = build_excerpt(effective_title, headings, paragraphs, KEYWORDS)

            # Smart scoring (cheap)
            score, matched = score_relevance(effective_title, excerpt, source, published_iso)

            # LLM summarization (1 call)
            out = llm_summarize(effective_title, url, excerpt)

            summary = "\n".join([f"- {b}" for b in out.get("summary_bullets", [])])[:1900]
            claims = "\n".join([f"- {c}" for c in out.get("key_claims", [])])[:1900]
            tags = out.get("tags", []) or matched[:6]

            # “Use in Draft” heuristic
            # Recommend: >=70 and confidence >=0.6
            confidence = float(out.get("confidence", 0.5))
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
            # Don’t mark processed on failure; let it retry next run
            print(f"[ERROR] {url} -> {e}")

if __name__ == "__main__":
    run()
