"""dev.to top articles of the last day (public API, no key)."""
from datetime import datetime

import config
from fetchers import http_client, make_item


def fetch() -> list[dict]:
    with http_client() as client:
        resp = client.get("https://dev.to/api/articles", params={"top": 1, "per_page": config.DEVTO_MAX})
        resp.raise_for_status()

    items = []
    for a in resp.json():
        if a.get("public_reactions_count", 0) < config.DEVTO_MIN_REACTIONS:
            continue
        items.append(make_item(
            "devto",
            a["url"],
            a["title"],
            raw_content=a.get("description"),
            author=(a.get("user") or {}).get("username"),
            published_at=datetime.fromisoformat(a["published_at"].replace("Z", "+00:00"))
            if a.get("published_at") else None,
            metadata={"reactions": a.get("public_reactions_count"),
                      "comments": a.get("comments_count"), "tags": a.get("tag_list")},
        ))
    return items
