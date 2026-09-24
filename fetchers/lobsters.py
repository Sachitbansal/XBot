"""Lobsters hottest stories (JSON, no key)."""
from datetime import datetime

import config
from fetchers import http_client, make_item


def fetch() -> list[dict]:
    with http_client() as client:
        resp = client.get("https://lobste.rs/hottest.json")
        resp.raise_for_status()

    items = []
    for s in resp.json():
        if s.get("score", 0) < config.LOBSTERS_MIN_SCORE:
            continue
        items.append(make_item(
            "lobsters",
            s.get("url") or s["comments_url"],
            s["title"],
            raw_content=s.get("description_plain"),
            author=s.get("submitter_user"),
            published_at=datetime.fromisoformat(s["created_at"]) if s.get("created_at") else None,
            metadata={"points": s.get("score"), "comments": s.get("comment_count"),
                      "tags": s.get("tags"), "lobsters_url": s.get("comments_url")},
        ))
    return items
