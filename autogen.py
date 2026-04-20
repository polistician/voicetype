# autogen.py
"""Heuristic auto-generation of snippet metadata from body text.

Given a snippet body, produce a plausible {name, description, tags} draft
so the user doesn't start from an empty form. Pure heuristics — no LLM,
no network, ~1ms. User can (and should) edit the result.
"""
from __future__ import annotations

import re
from collections import Counter


_STOPWORDS = {
    "the", "and", "that", "this", "with", "from", "for", "your", "have",
    "but", "are", "not", "you", "was", "will", "can", "all", "any", "been",
    "would", "could", "should", "were", "their", "them", "they", "there",
    "these", "those", "which", "what", "when", "where", "then", "than",
    "into", "over", "also", "like", "just", "only", "some", "more", "most",
    "about", "after", "before", "because", "while", "here", "how", "our",
    "its", "out", "off", "too", "one", "two", "new", "get", "got",
}


def _strip_shell_prefix(s: str) -> str:
    return re.sub(r"^[❯>$#%\s]+", "", s).strip()


def generate(body: str) -> dict:
    """Return {name, description, tags} draft derived from body."""
    raw = body or ""
    clean = raw.strip()
    if not clean:
        return {"name": "Untitled", "description": "", "tags": ""}

    lines = [l.strip() for l in clean.splitlines() if l.strip()]
    first_line = _strip_shell_prefix(lines[0]) if lines else ""

    # Name: first line if short, else first 5-8 words.
    words = first_line.split()
    if len(first_line) <= 60 and first_line:
        name = first_line
    elif words:
        name = " ".join(words[:6])
    else:
        name = "Untitled"
    name = name[:80].rstrip(":;,. ")

    # Description: first sentence(s), capped at ~150 chars.
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    desc_parts: list[str] = []
    for s in sentences:
        if not s.strip():
            continue
        candidate = (" ".join(desc_parts + [s.strip()])).strip()
        if len(candidate) > 150 and desc_parts:
            break
        desc_parts.append(s.strip())
        if len(candidate) >= 80:
            break
    description = " ".join(desc_parts)[:200]
    # Avoid the description just echoing the name verbatim.
    if description.lower().startswith(name.lower()) and len(description) <= len(name) + 3:
        description = ""

    # Tags: most frequent non-stopword alpha tokens >=4 chars, top 3.
    tokens = re.findall(r"[A-Za-z][A-Za-z-]{3,}", clean)
    lowered = [t.lower() for t in tokens]
    counts = Counter(t for t in lowered if t not in _STOPWORDS)
    tags_list = [w for w, _ in counts.most_common(3)]
    tags = ",".join(tags_list)

    return {"name": name, "description": description, "tags": tags}
