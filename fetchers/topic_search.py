"""Live topic search for /post <topic> when nothing in the DB matches. Free, no keys."""
import logging
from datetime import datetime, timedelta, timezone

import config
from fetchers import http_client, make_item

log = logging.getLogger(__name__)


def search_hn(topic: str) -> list[dict]:
    since = int((datetime.now(timezone.utc) - timedelta(days=config.TOPIC_SEARCH_DAYS)).timestamp())
    with http_client() as client:
        resp = client.get("https://hn.algolia.com/api/v1/search", params={
            "query": topic, "tags": "story", "hitsPerPage": config.TOPIC_SEARCH_RESULTS,
            "numericFilters": f"created_at_i>{since},points>{config.TOPIC_SEARCH_HN_MIN_POINTS}",
        })
        resp.raise_for_status()
    items = []
    for h in resp.json().get("hits", []):
        hn_url = f"https://news.ycombinator.com/item?id={h['objectID']}"
        items.append(make_item(
            "topic_search:hn", h.get("url") or hn_url, h.get("title") or "",
            raw_content=(h.get("story_text") or "")[:3000], author=h.get("author"),
            published_at=datetime.fromtimestamp(h["created_at_i"], tz=timezone.utc),
            metadata={"points": h.get("points"), "comments": h.get("num_comments"),
                      "hn_url": hn_url, "topic": topic},
        ))
    return items


def search_github(topic: str) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=config.TOPIC_SEARCH_DAYS * 4)).date()
    with http_client() as client:
        resp = client.get("https://api.github.com/search/repositories", params={
            "q": f"{topic} pushed:>{since}", "sort": "stars", "order": "desc",
            "per_page": config.TOPIC_SEARCH_RESULTS,
        })
        resp.raise_for_status()
    return [
        make_item(
            # "github_trending" source so repo framing + README enrichment apply
            "github_trending", r["html_url"], r["full_name"],
            raw_content=r.get("description"), author=r["owner"]["login"],
            metadata={"stars": r.get("stargazers_count"), "language": r.get("language"),
                      "topic": topic, "via": "topic_search"},
        )
        for r in resp.json().get("items", [])
    ]


def search(topic: str) -> list[dict]:
    items = []
    for fn in (search_hn, search_github):
        try:
            items += fn(topic)
        except Exception as e:
            log.warning("topic search %s(%r) failed: %s", fn.__name__, topic, e)
    return [i for i in items if i["title"]]
