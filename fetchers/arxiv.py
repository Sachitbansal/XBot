"""arXiv API: newest papers in configured categories within the lookback window."""
import re
from datetime import datetime, timedelta, timezone

import feedparser

import config
from fetchers import http_client, make_item

API = "https://export.arxiv.org/api/query"


def fetch() -> list[dict]:
    query = " OR ".join(f"cat:{c}" for c in config.ARXIV_CATEGORIES)
    params = {"search_query": query, "sortBy": "submittedDate", "sortOrder": "descending",
              "max_results": config.ARXIV_MAX_RESULTS}
    with http_client() as client:
        resp = client.get(API, params=params)
        resp.raise_for_status()
    feed = feedparser.parse(resp.text)

    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.ARXIV_LOOKBACK_HOURS)
    items = []
    for e in feed.entries:
        published = datetime(*e.published_parsed[:6], tzinfo=timezone.utc) if e.get("published_parsed") else None
        if published and published < cutoff:
            continue
        # arXiv's listing lag means "last 24h" can be empty on weekends; that's fine.
        items.append(make_item(
            "arxiv",
            re.sub(r"v\d+$", "", e.link),  # strip version so v1/v2 dedupe
            " ".join(e.title.split()),
            raw_content=" ".join(e.get("summary", "").split()),
            author=", ".join(a.name for a in e.get("authors", [])[:5]) or None,
            published_at=published,
            metadata={"categories": [t["term"] for t in e.get("tags", [])],
                      "primary_category": e.get("arxiv_primary_category", {}).get("term")},
        ))
    return items
