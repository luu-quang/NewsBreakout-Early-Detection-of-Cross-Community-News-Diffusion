"""Text and URL normalization utilities for duplicate and syndication detection."""

from __future__ import annotations

import html
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from typing import Set, List


# Standard tracking parameters to strip from URLs
TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "fbclid",
    "gclid",
    "ref",
    "source",
    "from",
    "v",
    "spm",
}

# Common Vietnamese publisher suffix/branding patterns in titles
PUBLISHER_SUFFIX_PATTERN = re.compile(
    r"\s*[-|–_]\s*(?:báo\s+)?(?:"
    r"lao\s+động|vnexpress|tuổi\s+trẻ(?:\s+online)?|thanh\s+niên|dân\s+trí|"
    r"vietnamnet|nhân\s+dân|tiền\s+phong|cand|sggp|vtv(?:\s+news)?|vov(?:\s+live)?|"
    r"vtc\s+news|vietnamplus|bnews|pháp\s+luật(?:\s+tphcm)?|plo"
    r")\s*.*$",
    flags=re.IGNORECASE,
)

# Common HTML entities / non-breaking space
HTML_ENTITIES_PATTERN = re.compile(r"&(?:apos|quot|amp|lt|gt|nbsp|#39|#34);", flags=re.IGNORECASE)


def normalize_url(url: str | None) -> str:
    """Normalize a web URL to canonical form for duplicate detection."""
    if not url or not isinstance(url, str):
        return ""
    url = url.strip()
    if not url:
        return ""

    parsed = urlparse(url)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()

    # Strip default ports and 'www.' prefix
    if netloc.startswith("www."):
        netloc = netloc[4:]
    if ":" in netloc:
        host, port = netloc.split(":", 1)
        if (scheme == "http" and port == "80") or (scheme == "https" and port == "443"):
            netloc = host

    # Normalize path: collapse multi-slashes, strip trailing slash except root
    path = re.sub(r"/{2,}", "/", parsed.path)
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]

    # Filter tracking query parameters and sort remaining parameters
    if parsed.query:
        query_pairs = parse_qsl(parsed.query, keep_blank_values=False)
        filtered_pairs = sorted(
            (k.lower(), v) for k, v in query_pairs if k.lower() not in TRACKING_PARAMS
        )
        new_query = urlencode(filtered_pairs)
    else:
        new_query = ""

    # Fragments are stripped as they refer to in-page anchors
    return urlunparse((scheme, netloc, path, "", new_query, ""))


def normalize_text(text: str | None, *, strip_branding: bool = True) -> str:
    """Normalize text into canonical lowercase NFC form with punctuation normalized."""
    if not text or not isinstance(text, str):
        return ""

    # Unescape HTML entities first
    text = html.unescape(text)
    text = HTML_ENTITIES_PATTERN.sub(" ", text)

    # Unicode NFC normalization
    text = unicodedata.normalize("NFC", text).strip().lower()

    # Strip publisher branding/suffix if requested
    if strip_branding:
        text = PUBLISHER_SUFFIX_PATTERN.sub("", text)

    # Replace punctuation and control chars with single whitespace
    text = re.sub(r"[^\w\s]", " ", text)
    # Collapse multiple whitespace
    return " ".join(text.split())


def get_tokens(text: str) -> List[str]:
    """Tokenize normalized text by whitespace."""
    return text.split() if text else []


def get_token_sort_string(text: str) -> str:
    """Return token-sorted string for order-agnostic matching."""
    tokens = get_tokens(text)
    return " ".join(sorted(tokens))


def get_word_ngrams(tokens: List[str], n: int = 3) -> Set[str]:
    """Generate set of word n-grams (shingles) from a token list."""
    if not tokens:
        return set()
    if len(tokens) < n:
        return {" ".join(tokens)}
    return {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def calculate_containment(set_a: Set[str], set_b: Set[str]) -> float:
    """Calculate directional containment ratio: |A ∩ B| / min(|A|, |B|)."""
    if not set_a or not set_b:
        return 0.0
    intersection_size = len(set_a & set_b)
    min_size = min(len(set_a), len(set_b))
    return intersection_size / min_size if min_size > 0 else 0.0


def calculate_jaccard(set_a: Set[str], set_b: Set[str]) -> float:
    """Calculate Jaccard similarity: |A ∩ B| / |A ∪ B|."""
    if not set_a or not set_b:
        return 0.0
    intersection_size = len(set_a & set_b)
    union_size = len(set_a | set_b)
    return intersection_size / union_size if union_size > 0 else 0.0
