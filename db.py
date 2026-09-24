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


def items_awaiting_drafts(conn, threshold: float, limit: int, max_age_hours: int = 48) -> list[dict]:
    """Recent items scoring >= threshold with no drafts yet, best first.

    Compares against the *current* threshold (not item_scores.cleared_threshold, which
    records the threshold at scoring time) so manual retuning applies to the backlog.
    """
    return conn.execute(
        """
        SELECT r.*, s.composite_score FROM raw_items r
        JOIN item_scores s ON s.raw_item_id = r.id AND s.composite_score >= %s
        WHERE NOT EXISTS (SELECT 1 FROM drafts d WHERE d.raw_item_id = r.id)
          AND r.fetched_at > now() - make_interval(hours => %s)
        ORDER BY s.composite_score DESC
        LIMIT %s
        """,
        (threshold, max_age_hours, limit),
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


def unsent_drafts(conn, max_age_hours: int, limit: int) -> list[dict]:
    """Unsent drafts newer than max_age_hours, oldest first (stale ones are never sent)."""
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
        ORDER BY d.generated_at
        LIMIT %s
        """,
        (max_age_hours, limit),
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
