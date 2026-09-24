"""/post [topic]: make drafts right now instead of waiting for the hourly cycle.

No topic → best in-niche undrafted item from recent cycles (THRESHOLD ignored).
Topic    → best matching item in the DB; if none, live-search HN + GitHub for it,
           score the hits, and use the best one. Drafts are steered toward the topic.
"""
import logging

import config
import db
from fetchers import topic_search
from pipeline import dedupe, generate, score

log = logging.getLogger(__name__)


class NothingFound(Exception):
    pass


def _score_candidates(conn, items: list[dict]) -> None:
    system = score.system_prompt(conn)
    for item in items[: config.ON_DEMAND_MAX_SCORE]:
        try:
            score.score_item(conn, item, system)
            conn.commit()
        except Exception as e:
            conn.rollback()
            log.warning("on-demand scoring failed for %s: %s", item["title"][:60], e)


def _best(conn, topic: str | None) -> list[dict]:
    # An explicit topic is its own niche decision, so the relevance gate only applies without one.
    min_rel = 0 if topic else config.MIN_RELEVANCE_TO_DRAFT
    return db.best_undrafted_items(conn, min_rel, 1, config.ON_DEMAND_LOOKBACK_HOURS, topic)


def pick_item(conn, topic: str | None) -> dict:
    found = _best(conn, topic)
    if found:
        return found[0]
    if not topic:
        raise NothingFound("No undrafted in-niche items from recent cycles.")

    # Matching items fetched but not scored yet (e.g. beyond the per-cycle cap).
    _score_candidates(conn, db.unscored_topic_items(conn, topic, config.ON_DEMAND_MAX_SCORE,
                                                    config.ON_DEMAND_LOOKBACK_HOURS))
    found = _best(conn, topic)
    if found:
        return found[0]

    # Nothing local: search live, store, score.
    new_ids = dedupe.store_new(conn, topic_search.search(topic))
    conn.commit()
    _score_candidates(conn, db.get_raw_items_by_ids(conn, new_ids))
    found = _best(conn, topic)
    if found:
        return found[0]
    # Search hits don't always contain the topic words verbatim (e.g. repo descriptions):
    # fall back to the best-scored hit from the search itself.
    best = db.best_scored_among(conn, new_ids)
    if best:
        return best
    raise NothingFound(f"Couldn't find anything recent about “{topic}”.")


def make_post(conn, topic: str | None = None) -> dict:
    """Pick an item and generate drafts for it. Returns {item, draft_ids}. Raises NothingFound."""
    topic = (topic or "").strip() or None
    item = pick_item(conn, topic)
    ids = generate.generate_for_item(conn, item, focus=topic)
    conn.commit()
    if not ids:
        raise NothingFound(f"The model produced no usable drafts for “{item['title'][:80]}”. Try again.")
    return {"item": item, "draft_ids": ids}
