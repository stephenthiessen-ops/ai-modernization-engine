# AI Modernization Engine (Option 2) — RSS → Notion (Research) → Notion (Draft Queue)

Cost-efficient pipeline to curate research and generate LinkedIn drafts around Operational Modernization + AI Transformation.

## What this repo includes
- RSS ingestion with optional keyword filtering
- Notion API client helpers
- GitHub Actions workflow (scheduled + manual)
- Local SQLite dedupe (URL-based)
- Safe secret handling via environment variables (no secrets in code)

## Prereqs
- Python 3.11+
- Notion Internal Integration token
- Notion database IDs for:
  - Research Library
  - Content Queue (draft queue)

## Environment Variables
Set these locally (or as GitHub Actions secrets):

- NOTION_TOKEN
- NOTION_RESEARCH_DB_ID
- NOTION_QUEUE_DB_ID

## Quickstart (local)
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export NOTION_TOKEN="secret_..."
export NOTION_RESEARCH_DB_ID="..."
export NOTION_QUEUE_DB_ID="..."

python ingest_sources.py
```

## Optional keyword filtering
Keyword filtering is controlled via `ENABLE_KEYWORD_FILTER` in `config.py`.
- If enabled: only RSS items whose title/summary match keywords are ingested to Notion.
- If disabled: all items within the recency window are ingested (still deduped).

## Notes
- This starter kit ONLY ingests RSS items into Notion Research Library.
- Next steps (not included here): extraction + summarization + weekly draft builder.
