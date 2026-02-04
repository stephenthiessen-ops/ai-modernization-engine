import re
import requests
from bs4 import BeautifulSoup
from typing import List, Tuple, Optional
from config import MAX_MATCH_TEXT_CHARS

USER_AGENT = "Mozilla/5.0 (compatible; AIModernizationEngine/1.0; +https://example.com/bot)"

def _clean_whitespace(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def fetch_html(url: str, timeout: int = 20) -> str:
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return resp.text

def extract_text_blocks(html: str) -> Tuple[str, List[str], List[str]]:
    """
    Returns: (title, headings, paragraphs)
    """
    soup = BeautifulSoup(html, "lxml")

    # remove junk
    for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav", "aside"]):
        tag.decompose()

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    # Prefer <article>, fallback to body
    root = soup.find("article") or soup.body or soup

    headings = []
    for h in root.find_all(["h1", "h2", "h3"]):
        t = h.get_text(" ", strip=True)
        if t and len(t) <= 180:
            headings.append(t)

    paragraphs = []
    for p in root.find_all("p"):
        t = p.get_text(" ", strip=True)
        # Drop very short / boilerplate-ish fragments
        if t and len(t) >= 60:
            paragraphs.append(t)

    return title, headings, paragraphs

def build_excerpt(
    title: str,
    headings: List[str],
    paragraphs: List[str],
    keywords: List[str],
    max_chars: int = 12000,
) -> str:
    """
    Cost-control: we build a small excerpt with:
    - title
    - top headings (limited)
    - first few paragraphs
    - paragraphs that match keywords
    and cap total characters.
    """
    kw_lower = [k.lower() for k in keywords]
    selected = []

    # First N paragraphs
    first_n = paragraphs[:4]
    selected.extend(first_n)

    # Keyword-matching paragraphs
    for p in paragraphs[4:]:
        pl = p.lower()
        if any(k in pl for k in kw_lower):
            selected.append(p)
        if len(selected) >= 10:  # cap count
            break

    excerpt_parts = []
    if title:
        excerpt_parts.append(f"TITLE: {title}")
    if headings:
        excerpt_parts.append("HEADINGS:\n- " + "\n- ".join(headings[:8]))
    if selected:
        excerpt_parts.append("CONTENT:\n" + "\n\n".join(selected))

    excerpt = _clean_whitespace("\n\n".join(excerpt_parts))
    excerpt = excerpt[:min(max_chars, MAX_MATCH_TEXT_CHARS)]
    return excerpt
