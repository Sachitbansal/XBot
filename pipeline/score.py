"""Score items 0-10 on five axes via the LLM; composite + threshold computed in Python."""
import json
import logging

import config
import db
import llm

log = logging.getLogger(__name__)

# LLM JSON key -> internal/db axis name
AXES = {
    "virality": "virality",
    "novelty": "novelty",
    "technical_value": "technical",
    "relevance": "relevance",
    "discussion_potential": "discussion",
}

SYSTEM = f"""You rate news items for a tech creator on X deciding what's worth posting about.
Audience: {config.AUDIENCE}.

Score each axis as an integer 0-10. Be harsh: most items are 3-6. Reserve 8+ for things
people in this audience will genuinely be talking about today.
- virality: likelihood this spreads widely on X right now
- novelty: genuinely new (new release, result, idea) vs rehash / incremental
- technical_value: substance a builder can learn from or act on
- relevance: fit for the audience above
- discussion_potential: invites takes, debate, replies

Respond with JSON only: {{"virality": n, "novelty": n, "technical_value": n, "relevance": n, "discussion_potential": n}}"""


def build_prompt(item: dict) -> str:
    content = (item.get("raw_content") or "")[: config.SCORE_CONTENT_CHARS]
    meta = item.get("metadata") or {}
    return (
        f"Source: {item['source']}\n"
        f"Title: {item['title']}\n"
        f"URL: {item['source_url']}\n"
        f"Author: {item.get('author') or 'unknown'}\n"
        f"Signals: {json.dumps(meta, default=str)}\n"
        f"Content: {content or '(none)'}"
    )


def parse_scores(raw: dict) -> dict:
    """Map LLM keys to axis names, coerce to ints clamped to 0-10. Raises KeyError if an axis is missing."""
    return {axis: max(0, min(10, round(float(raw[key])))) for key, axis in AXES.items()}


def composite(scores: dict) -> float:
    return round(sum(config.SCORE_WEIGHTS[a] * scores[a] for a in config.SCORE_WEIGHTS), 2)


def score_item(conn, item: dict) -> dict:
    """Score one item and persist. Returns {composite, cleared, scores}."""
    raw, model = llm.score(SYSTEM, build_prompt(item))
    scores = parse_scores(raw)
    comp = composite(scores)
    cleared = comp >= config.THRESHOLD
    db.insert_score(conn, item["id"], scores, comp, cleared, model)
    return {"composite": comp, "cleared": cleared, "scores": scores}


def score_pending(conn) -> dict:
    """Score every unscored recent item (capped). Commits per item so failures don't lose work."""
    items = db.unscored_items(conn, config.MAX_ITEMS_TO_SCORE_PER_CYCLE)
    stats = {"scored": 0, "cleared": 0, "failed": 0}
    for item in items:
        try:
            result = score_item(conn, item)
            conn.commit()
        except Exception as e:
            conn.rollback()
            stats["failed"] += 1
            log.warning("scoring failed for %s (%s): %s", item["id"], item["title"][:60], e)
            continue
        stats["scored"] += 1
        stats["cleared"] += result["cleared"]
        log.info("%.2f %s %s", result["composite"], "✓" if result["cleared"] else " ", item["title"][:80])
    return stats
