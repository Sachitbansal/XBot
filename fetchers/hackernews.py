"""Hacker News via the Firebase API: top/new stories, filtered to tech-relevant."""
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import config
from fetchers import http_client, make_item

log = logging.getLogger(__name__)
API = "https://hacker-news.firebaseio.com/v0"


def is_tech_relevant(title: str) -> bool:
    t = title.lower()
    return any(re.search(rf"\b{re.escape(k)}\b", t) for k in config.HN_TECH_KEYWORDS)


def fetch() -> list[dict]:
    with http_client() as client:
        ids: list[int] = []
        for lst in config.HN_STORY_LISTS:
            ids += client.get(f"{API}/{lst}.json").json()[: config.HN_MAX_PER_LIST]
        ids = list(dict.fromkeys(ids))

        def get(i):
            try:
                return client.get(f"{API}/item/{i}.json").json()
            except Exception as e:
                log.warning("HN item %s failed: %s", i, e)
                return None

        with ThreadPoolExecutor(max_workers=10) as pool:
            stories = list(pool.map(get, ids))

    items = []
    for s in stories:
        if not s or s.get("type") != "story" or s.get("dead") or s.get("deleted"):
            continue
        title = s.get("title", "")
        if s.get("score", 0) < config.HN_MIN_POINTS:
            continue
        if config.HN_KEYWORD_FILTER and not is_tech_relevant(title):
            continue
        hn_url = f"https://news.ycombinator.com/item?id={s['id']}"
        items.append(make_item(
            "hackernews",
            s.get("url") or hn_url,
            title,
            raw_content=s.get("text"),
            author=s.get("by"),
            published_at=datetime.fromtimestamp(s["time"], tz=timezone.utc) if s.get("time") else None,
            metadata={"points": s.get("score"), "comments": s.get("descendants"),
                      "hn_url": hn_url},
        ))
    return items
