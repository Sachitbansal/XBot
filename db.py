"""Postgres access. Raw SQL via psycopg3; every helper takes an open connection."""
import json
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

import config


def connect() -> psycopg.Connection:
    return psycopg.connect(config.DATABASE_URL, row_factory=dict_row)


# --- raw_items -------------------------------------------------------------

def existing_hashes(conn, hashes: list[str]) -> set[str]:
    if not hashes:
        return set()
    rows = conn.execute(
        "SELECT content_hash FROM raw_items WHERE content_hash = ANY(%s)", (hashes,)
    ).fetchall()
    return {r["content_hash"] for r in rows}


def insert_raw_item(conn, item: dict) -> str | None:
    """Insert one item. Returns new id, or None if the hash already existed."""
    row = conn.execute(
        """
        INSERT INTO raw_items (source, source_url, title, raw_content, author,
                               published_at, content_hash, metadata)
        VALUES (%(source)s, %(source_url)s, %(title)s, %(raw_content)s, %(author)s,
                %(published_at)s, %(content_hash)s, %(metadata)s)
        ON CONFLICT (content_hash) DO NOTHING
        RETURNING id
        """,
        {**item, "metadata": json.dumps(item.get("metadata") or {})},
    ).fetchone()
    return str(row["id"]) if row else None


def unscored_items(conn, limit: int, max_age_hours: int = 48) -> list[dict]:
    """Recent items with no score yet (new this cycle, or scoring failed last cycle)."""
    return conn.execute(
        """
        SELECT r.* FROM raw_items r
        LEFT JOIN item_scores s ON s.raw_item_id = r.id
        WHERE s.id IS NULL
          AND r.fetched_at > now() - make_interval(hours => %s)
        ORDER BY r.fetched_at DESC
        LIMIT %s
        """,
        (max_age_hours, limit),
    ).fetchall()


def get_raw_item(conn, raw_item_id) -> dict | None:
    return conn.execute("SELECT * FROM raw_items WHERE id = %s", (raw_item_id,)).fetchone()


# --- item_scores -----------------------------------------------------------

def insert_score(conn, raw_item_id, scores: dict, composite: float,
                 cleared: bool, model: str) -> str:
    row = conn.execute(
        """
        INSERT INTO item_scores (raw_item_id, virality_score, novelty_score, technical_score,
                                 relevance_score, discussion_score, composite_score,
                                 cleared_threshold, scoring_model)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (raw_item_id, scores["virality"], scores["novelty"], scores["technical"],
         scores["relevance"], scores["discussion"], composite, cleared, model),
    ).fetchone()
    return str(row["id"])


def items_awaiting_drafts(conn, threshold: float, min_relevance: int, limit: int,
                          max_age_hours: int = 48) -> list[dict]:
    """Recent in-niche items scoring >= threshold with no drafts yet, best first.

    Compares against the *current* threshold (not item_scores.cleared_threshold, which
    records the threshold at scoring time) so manual retuning applies to the backlog.
    """
    return conn.execute(
        """
        SELECT r.*, s.composite_score FROM raw_items r
        JOIN item_scores s ON s.raw_item_id = r.id AND s.composite_score >= %s
                              AND s.relevance_score >= %s
        WHERE NOT EXISTS (SELECT 1 FROM drafts d WHERE d.raw_item_id = r.id)
          AND r.fetched_at > now() - make_interval(hours => %s)
        ORDER BY s.composite_score DESC
        LIMIT %s
        """,
        (threshold, min_relevance, max_age_hours, limit),
    ).fetchall()


# --- drafts ----------------------------------------------------------------

def insert_draft(conn, raw_item_id, angle_type: str, text: str,
                 model: str, quote_target_url: str | None = None) -> str:
    row = conn.execute(
        """
        INSERT INTO drafts (raw_item_id, angle_type, ai_draft, quote_target_url, generation_model)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (raw_item_id, angle_type, text, quote_target_url, model),
    ).fetchone()
    return str(row["id"])


def unsent_drafts(conn, max_age_hours: int, limit: int, draft_ids: list | None = None) -> list[dict]:
    """Unsent drafts newer than max_age_hours, oldest first (stale ones are never sent).

    `draft_ids` restricts to specific drafts (on-demand /post delivers only its own).
    """
    return conn.execute(
        """
        SELECT d.*, r.title, r.source, r.source_url, r.author, s.*
        FROM drafts d
        LEFT JOIN raw_items r ON r.id = d.raw_item_id
        LEFT JOIN LATERAL (SELECT composite_score, virality_score, novelty_score, technical_score,
                                  relevance_score, discussion_score FROM item_scores
                           WHERE raw_item_id = d.raw_item_id
                           ORDER BY scored_at DESC LIMIT 1) s ON true
        WHERE d.sent_to_telegram_at IS NULL
          AND d.generated_at > now() - make_interval(hours => %s)
          AND (%s::uuid[] IS NULL OR d.id = ANY(%s::uuid[]))
        ORDER BY d.generated_at
        LIMIT %s
        """,
        (max_age_hours, draft_ids, draft_ids, limit),
    ).fetchall()


def mark_draft_sent(conn, draft_id, telegram_message_id: int | None) -> None:
    """Mark delivered for review. telegram_message_id is None for markdown output."""
    conn.execute(
        "UPDATE drafts SET sent_to_telegram_at = now(), telegram_message_id = %s WHERE id = %s",
        (telegram_message_id, draft_id),
    )


def get_draft(conn, draft_id) -> dict | None:
    return conn.execute("SELECT * FROM drafts WHERE id = %s", (draft_id,)).fetchone()


# --- decisions / edit_pairs -----------------------------------------------

def draft_has_decision(conn, draft_id) -> bool:
    return conn.execute(
        "SELECT 1 FROM decisions WHERE draft_id = %s LIMIT 1", (draft_id,)
    ).fetchone() is not None


def record_decision(conn, draft: dict, decision: str,
                    final_version: str | None = None,
                    edit_distance: int | None = None) -> str:
    """Write decisions row (+ edit_pairs row for approved/edited) in the caller's transaction."""
    now = datetime.now(timezone.utc)
    sent = draft.get("sent_to_telegram_at")
    latency = int((now - sent).total_seconds()) if sent else None

    row = conn.execute(
        """
        INSERT INTO decisions (draft_id, decision, decided_at, response_latency_seconds)
        VALUES (%s, %s, %s, %s) RETURNING id
        """,
        (draft["id"], decision, now, latency),
    ).fetchone()
    decision_id = str(row["id"])

    if decision in ("approved_as_is", "edited"):
        conn.execute(
            """
            INSERT INTO edit_pairs (draft_id, decision_id, ai_draft, final_version, edit_distance)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (draft["id"], decision_id, draft["ai_draft"], final_version, edit_distance),
        )
    return decision_id


def get_draft_by_message_id(conn, telegram_message_id: int) -> dict | None:
    return conn.execute(
        "SELECT * FROM drafts WHERE telegram_message_id = %s", (telegram_message_id,)
    ).fetchone()


def undecided_drafts(conn) -> list[dict]:
    """Delivered drafts with no decision yet, grouped by item (for review.py)."""
    return conn.execute(
        """
        SELECT d.*, r.title, r.source_url FROM drafts d
        LEFT JOIN raw_items r ON r.id = d.raw_item_id
        WHERE d.sent_to_telegram_at IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM decisions x WHERE x.draft_id = d.id)
        ORDER BY d.generated_at, d.raw_item_id, d.angle_type
        """
    ).fetchall()


# --- suggestions -----------------------------------------------------------

def insert_suggestion(conn, text: str) -> str:
    row = conn.execute("INSERT INTO suggestions (text) VALUES (%s) RETURNING id", (text,)).fetchone()
    return str(row["id"])


def latest_suggestion_summary(conn) -> dict | None:
    return conn.execute(
        "SELECT * FROM suggestion_summaries ORDER BY created_at DESC LIMIT 1"
    ).fetchone()


def unsummarized_suggestions(conn) -> list[dict]:
    return conn.execute(
        "SELECT * FROM suggestions WHERE summarized_into IS NULL ORDER BY created_at"
    ).fetchall()


def insert_suggestion_summary(conn, summary: str, model: str, folded_ids: list) -> str:
    row = conn.execute(
        "INSERT INTO suggestion_summaries (summary, model) VALUES (%s, %s) RETURNING id",
        (summary, model),
    ).fetchone()
    conn.execute("UPDATE suggestions SET summarized_into = %s WHERE id = ANY(%s)",
                 (row["id"], folded_ids))
    return str(row["id"])


# --- on-demand posts -------------------------------------------------------

def best_undrafted_items(conn, min_relevance: int, limit: int, max_age_hours: int = 48,
                         topic: str | None = None) -> list[dict]:
    """Best-scoring recent in-niche items with no drafts, ignoring THRESHOLD.

    With `topic`, only items whose title/content full-text-match it.
    """
    topic_sql = ("AND to_tsvector('english', r.title || ' ' || coalesce(r.raw_content, '')) "
                 "@@ plainto_tsquery('english', %(topic)s)") if topic else ""
    return conn.execute(
        f"""
        SELECT r.*, s.composite_score FROM raw_items r
        JOIN item_scores s ON s.raw_item_id = r.id AND s.relevance_score >= %(rel)s
        WHERE NOT EXISTS (SELECT 1 FROM drafts d WHERE d.raw_item_id = r.id)
          AND r.fetched_at > now() - make_interval(hours => %(age)s)
          {topic_sql}
        ORDER BY s.composite_score DESC
        LIMIT %(limit)s
        """,
        {"rel": min_relevance, "age": max_age_hours, "limit": limit, "topic": topic},
    ).fetchall()


def unscored_topic_items(conn, topic: str, limit: int, max_age_hours: int = 48) -> list[dict]:
    return conn.execute(
        """
        SELECT r.* FROM raw_items r
        WHERE NOT EXISTS (SELECT 1 FROM item_scores s WHERE s.raw_item_id = r.id)
          AND r.fetched_at > now() - make_interval(hours => %s)
          AND to_tsvector('english', r.title || ' ' || coalesce(r.raw_content, ''))
              @@ plainto_tsquery('english', %s)
        ORDER BY r.fetched_at DESC
        LIMIT %s
        """,
        (max_age_hours, topic, limit),
    ).fetchall()


def get_raw_items_by_ids(conn, ids: list) -> list[dict]:
    return conn.execute("SELECT * FROM raw_items WHERE id = ANY(%s::uuid[])", (ids,)).fetchall()


def best_scored_among(conn, ids: list) -> dict | None:
    if not ids:
        return None
    return conn.execute(
        """
        SELECT r.*, s.composite_score FROM raw_items r
        JOIN item_scores s ON s.raw_item_id = r.id
        WHERE r.id = ANY(%s::uuid[])
          AND NOT EXISTS (SELECT 1 FROM drafts d WHERE d.raw_item_id = r.id)
        ORDER BY s.composite_score DESC LIMIT 1
        """,
        (ids,),
    ).fetchone()
