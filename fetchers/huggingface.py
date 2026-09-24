"""Hugging Face: curated daily papers and trending models."""
from datetime import datetime, timedelta, timezone

import config
from fetchers import http_client, make_item

API = "https://huggingface.co/api"


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def fetch_papers() -> list[dict]:
    with http_client() as client:
        resp = client.get(f"{API}/daily_papers", params={"limit": 100})
        resp.raise_for_status()
    entries = sorted(resp.json(), key=lambda e: e["paper"].get("upvotes", 0), reverse=True)

    items = []
    for e in entries[: config.HF_PAPERS_MAX]:
        p = e["paper"]
        items.append(make_item(
            "hf_papers",
            # Same URL shape as the arXiv fetcher so the same paper dedupes across sources.
            f"https://arxiv.org/abs/{p['id']}",
            p.get("title") or e.get("title", ""),
            raw_content=" ".join((p.get("summary") or "").split()),
            author=", ".join(a["name"] for a in p.get("authors", [])[:5]) or None,
            published_at=_dt(p.get("publishedAt")),
            metadata={"upvotes": p.get("upvotes"), "comments": e.get("numComments"),
                      "hf_url": f"https://huggingface.co/papers/{p['id']}"},
        ))
    return items


def fetch_models() -> list[dict]:
    with http_client() as client:
        resp = client.get(f"{API}/models", params={"sort": "trendingScore", "limit": config.HF_MODELS_MAX})
        resp.raise_for_status()

    cutoff = datetime.now(timezone.utc) - timedelta(days=config.HF_MODELS_MAX_AGE_DAYS)
    items = []
    for m in resp.json():
        created = _dt(m.get("createdAt"))
        if created and created < cutoff:
            continue
        tags = [t for t in m.get("tags", []) if not t.startswith(("region:", "endpoints_"))]
        items.append(make_item(
            "hf_models",
            f"https://huggingface.co/{m['id']}",
            m["id"],
            raw_content=f"Trending Hugging Face model. Task: {m.get('pipeline_tag') or 'n/a'}. "
                        f"Tags: {', '.join(tags[:15])}",
            author=m.get("author"),
            published_at=created,
            metadata={"likes": m.get("likes"), "downloads": m.get("downloads"),
                      "trending_score": m.get("trendingScore"),
                      "library": m.get("library_name")},
        ))
    return items
