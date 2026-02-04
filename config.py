from datetime import timedelta

# How far back to accept RSS items
RECENCY_DAYS = 14

# Optional keyword filtering toggle
ENABLE_KEYWORD_FILTER = True

# Keyword set tuned to Operational Modernization + AI Transformation
KEYWORDS = [
    "operating model",
    "operational modernization",
    "modernization",
    "transformation",
    "ai transformation",
    "portfolio",
    "portfolio governance",
    "governance",
    "execution systems",
    "workflow",
    "automation",
    "agentic",
    "platform engineering",
    "coordination debt",
    "decision velocity",
    "signal",
]

# Dedupe DB path
DEDUPE_DB_PATH = "rss_seen.db"

# Safety: cap how long title+summary matching strings can be (RSS can be noisy)
MAX_MATCH_TEXT_CHARS = 4000
