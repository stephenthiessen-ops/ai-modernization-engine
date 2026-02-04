from datetime import timedelta

# How far back to accept RSS items
RECENCY_DAYS = 14

# Optional keyword filtering toggle
ENABLE_KEYWORD_FILTER = True

# Keyword set tuned to Operational Modernization + AI Transformation
KEYWORDS = [
    # Operating model / governance
    "operating model",
    "governance",
    "portfolio governance",
    "decision rights",
    "decision velocity",
    "prioritization",
    "capital allocation",
    "resource allocation",
    "organizational design",
    "coordination debt",

    # Program / TPM elevation
    "program management",
    "technical program management",
    "portfolio management",
    "roadmap alignment",
    "cross-functional",
    "execution systems",
    "delivery system",
    "dependency management",

    # AI transformation
    "AI transformation",
    "AI strategy",
    "agentic",
    "automation",
    "workflow automation",
    "intelligent systems",
    "augmented decision-making",
    "AI operating model",

    # Platform modernization
    "platform engineering",
    "internal developer platform",
    "modernization",
    "cloud architecture",
    "reliability engineering",
    "observability",
    "platform governance",

    # Metrics / signals
    "metrics",
    "measurement",
    "leading indicators",
    "lagging indicators",
    "performance systems",
    "risk management",
    "feedback loops",

    # Change / transformation
    "change management",
    "transformation",
    "organizational transformation",
    "enterprise agility",
    "value stream",
]

# Dedupe DB path
DEDUPE_DB_PATH = "rss_seen.db"

# Safety: cap how long title+summary matching strings can be (RSS can be noisy)
MAX_MATCH_TEXT_CHARS = 4000
