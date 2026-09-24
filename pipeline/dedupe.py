"""Exact dedup: content_hash = sha256(normalize(title) + normalize(url)). No fuzzy matching in v1."""
import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import db

TRACKING_PARAMS = re.compile(r"^(utm_|ref$|ref_src$|source$|fbclid$|gclid$)")


def normalize_title(title: str) -> str:
    t = re.sub(r"[^\w\s]", "", title.lower())
    return " ".join(t.split())


def normalize_url(url: str) -> str:
    """Drop tracking params, fragments, trailing slash; lowercase host."""
    parts = urlsplit(url.strip())
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not TRACKING_PARAMS.match(k)])
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), query, ""))


def content_hash(title: str, url: str) -> str:
    return hashlib.sha256((normalize_title(title) + normalize_url(url)).encode()).hexdigest()


def dedupe(conn, items: list[dict]) -> list[dict]:
    """Attach content_hash and drop items already in the DB or repeated within this batch."""
    unique: dict[str, dict] = {}
    for item in items:
        h = content_hash(item["title"], item["source_url"])
        unique.setdefault(h, {**item, "content_hash": h})
    seen = db.existing_hashes(conn, list(unique))
    return [item for h, item in unique.items() if h not in seen]


def store_new(conn, items: list[dict]) -> list[str]:
    """Dedupe then insert. Returns ids of newly inserted raw_items."""
    ids = []
    for item in dedupe(conn, items):
        new_id = db.insert_raw_item(conn, item)
        if new_id:
            ids.append(new_id)
    return ids
