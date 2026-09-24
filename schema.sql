-- X Content Agent schema (see SPEC.md §2). Idempotent: safe to re-run.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================
-- RAW ITEMS: everything pulled from sources, pre-dedup filter applied
-- ============================================
CREATE TABLE IF NOT EXISTS raw_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source          TEXT NOT NULL,           -- 'hackernews' | 'arxiv' | 'github_trending' | 'rss:<feed_name>' | 'x_search:<query>'
    source_url      TEXT NOT NULL,
    title           TEXT NOT NULL,
    raw_content     TEXT,                    -- excerpt/summary as pulled
    author          TEXT,                    -- original poster/account, if known — needed for quote-post drafts
    published_at    TIMESTAMPTZ,
    fetched_at      TIMESTAMPTZ DEFAULT now(),
    content_hash    TEXT UNIQUE NOT NULL,     -- sha256(title + source_url), used for dedup
    metadata        JSONB DEFAULT '{}'        -- source-specific extras: hn points, github stars, arxiv category, etc.
);

CREATE INDEX IF NOT EXISTS idx_raw_items_hash ON raw_items(content_hash);
CREATE INDEX IF NOT EXISTS idx_raw_items_fetched ON raw_items(fetched_at DESC);

-- ============================================
-- SCORES: LLM evaluation of each raw item
-- ============================================
CREATE TABLE IF NOT EXISTS item_scores (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    raw_item_id           UUID NOT NULL REFERENCES raw_items(id) ON DELETE CASCADE,
    virality_score        SMALLINT CHECK (virality_score BETWEEN 0 AND 10),
    novelty_score         SMALLINT CHECK (novelty_score BETWEEN 0 AND 10),
    technical_score       SMALLINT CHECK (technical_score BETWEEN 0 AND 10),
    relevance_score       SMALLINT CHECK (relevance_score BETWEEN 0 AND 10),
    discussion_score      SMALLINT CHECK (discussion_score BETWEEN 0 AND 10),
    composite_score       NUMERIC(4,2) NOT NULL,  -- weighted sum, computed at insert time (see weights below)
    cleared_threshold     BOOLEAN NOT NULL,        -- composite_score >= config.THRESHOLD at time of scoring
    scoring_model         TEXT NOT NULL,           -- e.g. 'qwen/qwen-2.5-72b-instruct'
    scored_at             TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_item_scores_raw_item ON item_scores(raw_item_id);
CREATE INDEX IF NOT EXISTS idx_item_scores_cleared ON item_scores(cleared_threshold) WHERE cleared_threshold = true;

-- Composite score weights (applied in score.py, not in SQL):
--   0.30 * virality + 0.25 * novelty + 0.20 * technical + 0.15 * relevance + 0.10 * discussion

-- ============================================
-- DRAFTS: AI-generated post candidates (only for items that cleared threshold)
-- ============================================
CREATE TABLE IF NOT EXISTS drafts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    raw_item_id         UUID REFERENCES raw_items(id) ON DELETE SET NULL,
    angle_type          TEXT NOT NULL,        -- 'technical_insight' | 'contrarian' | 'builder_pov' | 'short_punchy' | 'quote_post'
    ai_draft            TEXT NOT NULL,
    quote_target_url    TEXT,                 -- populated only for angle_type = 'quote_post'
    generation_model    TEXT NOT NULL,
    generated_at        TIMESTAMPTZ DEFAULT now(),
    sent_to_telegram_at TIMESTAMPTZ,
    telegram_message_id BIGINT                -- so bot replies can be matched back to this draft
);

CREATE INDEX IF NOT EXISTS idx_drafts_raw_item ON drafts(raw_item_id);

-- ============================================
-- DECISIONS: every accept / edit / reject, logged from day one
-- (This is the table that exists purely for future analysis — nothing
--  reads from it in v1, but every cycle must write to it.)
-- ============================================
CREATE TABLE IF NOT EXISTS decisions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id        UUID NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
    decision        TEXT NOT NULL CHECK (decision IN ('approved_as_is', 'edited', 'rejected')),
    decided_at      TIMESTAMPTZ DEFAULT now(),
    response_latency_seconds INT             -- time between sent_to_telegram_at and this decision — useful signal later
);

CREATE INDEX IF NOT EXISTS idx_decisions_draft ON decisions(draft_id);
CREATE INDEX IF NOT EXISTS idx_decisions_type ON decisions(decision);

-- ============================================
-- EDIT PAIRS: only populated when decision = 'edited' or 'approved_as_is'
-- This is the core signal for the future style/memory loop.
-- ============================================
CREATE TABLE IF NOT EXISTS edit_pairs (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id          UUID NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
    decision_id       UUID NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
    ai_draft          TEXT NOT NULL,          -- snapshot, denormalized
    final_version     TEXT NOT NULL,          -- what was actually posted (== ai_draft if approved_as_is)
    edit_distance     INT,                    -- word-level diff count, cheap to compute, no LLM call needed
    posted_at         TIMESTAMPTZ,
    created_at        TIMESTAMPTZ DEFAULT now()
);

-- Note: diff_summary (LLM-generated one-liner describing what changed) and
-- style_snapshots (periodic style-doc regeneration) are deferred to v2 —
-- schema for them can be added later without migrating existing tables.

-- ============================================
-- POST PERFORMANCE: v2, schema reserved but not built against in v1
-- ============================================
CREATE TABLE IF NOT EXISTS post_performance (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    edit_pair_id      UUID REFERENCES edit_pairs(id),
    x_post_id         TEXT,
    impressions       INT,
    likes             INT,
    replies           INT,
    bookmarks         INT,
    profile_visits    INT,
    checked_at        TIMESTAMPTZ DEFAULT now()
);

-- ============================================
-- SUGGESTIONS: free-text feedback sent via Telegram /suggest.
-- Injected into scoring + generation prompts. When they grow past
-- config.SUGGESTIONS_MAX_CHARS they're consolidated by an LLM into a
-- suggestion_summaries row; raw rows are kept forever for analysis.
-- ============================================
CREATE TABLE IF NOT EXISTS suggestion_summaries (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    summary         TEXT NOT NULL,
    model           TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS suggestions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    text            TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now(),
    summarized_into UUID REFERENCES suggestion_summaries(id)   -- NULL = not yet folded into a summary
);

CREATE INDEX IF NOT EXISTS idx_suggestions_unsummarized ON suggestions(created_at) WHERE summarized_into IS NULL;
