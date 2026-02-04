from datetime import datetime, timezone
from typing import List, Tuple
from config import KEYWORDS

# Optional: source quality weighting (tune as you like)
SOURCE_WEIGHTS = {
    "Harvard Business Review": 1.2,
    "MIT Sloan Management Review": 1.2,
    "McKinsey": 1.15,
    "InfoQ": 1.1,
    "Thoughtworks": 1.1,
    "CNCF": 1.05,
    "Atlassian": 1.05,
    "AWS": 1.0,
    "Google": 1.0,
    "Microsoft": 1.0,
}

def score_relevance(title: str, excerpt: str, source: str, published_iso: str | None) -> Tuple[float, List[str]]:
    """
    Returns (score_0_100, matched_keywords)
    No LLM call: cheap + deterministic.
    """
    text = (title + "\n" + excerpt).lower()

    matched = []
    for kw in KEYWORDS:
        if kw.lower() in text:
            matched.append(kw)

    # Base score from keyword matches (diminishing returns)
    kw_score = min(60.0, 8.0 * len(set(matched)))

    # Recency score (0–25)
    recency_score = 0.0
    if published_iso:
        try:
            pub = datetime.fromisoformat(published_iso.replace("Z", "+00:00"))
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - pub).days
            # 0 days => 25, 14 days => ~10, 30+ => 0
            recency_score = max(0.0, 25.0 * (1.0 - min(age_days, 30) / 30.0))
        except Exception:
            recency_score = 8.0  # fallback

    # Source multiplier (0.9–1.2 typical)
    mult = 1.0
    for k, w in SOURCE_WEIGHTS.items():
        if k.lower() in (source or "").lower():
            mult = w
            break

    raw = (kw_score + recency_score) * mult
    score = max(0.0, min(100.0, raw))
    return score, matched
