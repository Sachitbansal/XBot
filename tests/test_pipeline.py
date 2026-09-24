import db
from fetchers import make_item
from fetchers.x_trending_search import X_POST_RE
from pipeline import decide, dedupe, generate, score


# --- pure functions --------------------------------------------------------

def test_normalize_and_hash():
    assert dedupe.normalize_title("  Hello, World!! ") == "hello world"
    assert dedupe.normalize_url("https://Ex.com/a/?utm_source=x&id=1#frag") == "https://ex.com/a?id=1"
    assert dedupe.content_hash("Hello World", "https://ex.com/a/") == \
        dedupe.content_hash("hello, world!", "https://ex.com/a?utm_medium=rss")


def test_parse_scores_and_composite():
    s = score.parse_scores({"virality": 12, "novelty": "7", "technical_value": 6.6,
                            "relevance": -1, "discussion_potential": 5})
    assert s == {"virality": 10, "novelty": 7, "technical": 7, "relevance": 0, "discussion": 5}
    assert score.composite({k: 10 for k in s}) == 10.0
    assert score.composite({"virality": 8, "novelty": 8, "technical": 8,
                            "relevance": 8, "discussion": 8}) == 8.0


def test_word_edit_distance():
    assert decide.word_edit_distance("a b c", "a b c") == 0
    assert decide.word_edit_distance("a b c", "a x c") == 1
    assert decide.word_edit_distance("a b c", "a c") == 1
    assert decide.word_edit_distance("", "a b") == 2


def test_quote_post_angle_gating():
    plain = {"metadata": {}, "author": "someone"}
    x_post = {"metadata": {"x_post_url": "https://x.com/u/status/1"}, "author": "@u"}
    assert "quote_post" not in generate.angles_for(plain)
    assert "quote_post" in generate.angles_for(x_post)


def test_x_post_regex():
    m = X_POST_RE.match("https://twitter.com/karpathy/status/12345?s=20")
    assert m and m.group(1) == "karpathy" and m.group(2) == "12345"
    assert not X_POST_RE.match("https://x.com/karpathy")


# --- DB-backed ------------------------------------------------------------

def _item(title="Some Title", url="https://ex.com/a"):
    return make_item("hackernews", url, title, raw_content="body", metadata={"points": 100})


def test_store_new_dedupes(conn):
    ids = dedupe.store_new(conn, [_item(), _item("some title!"), _item("Other")])
    assert len(ids) == 2  # second is a normalized dup of first
    assert dedupe.store_new(conn, [_item()]) == []


def _draft(conn):
    [raw_id] = dedupe.store_new(conn, [_item()])
    draft_id = db.insert_draft(conn, raw_id, "short_punchy", "one two three", "test-model")
    db.mark_draft_sent(conn, draft_id, 42)
    conn.commit()
    return draft_id


def _rows(conn, table, draft_id):
    return conn.execute(f"SELECT * FROM {table} WHERE draft_id = %s", (draft_id,)).fetchall()


def test_approve_writes_decision_and_edit_pair(conn):
    d = _draft(conn)
    decide.decide(conn, d, "approved_as_is")
    [dec] = _rows(conn, "decisions", d)
    [pair] = _rows(conn, "edit_pairs", d)
    assert dec["decision"] == "approved_as_is" and dec["response_latency_seconds"] is not None
    assert pair["final_version"] == pair["ai_draft"] == "one two three"
    assert pair["edit_distance"] == 0


def test_edit_writes_final_version(conn):
    d = _draft(conn)
    decide.decide(conn, d, "edited", "one TWO three four")
    [pair] = _rows(conn, "edit_pairs", d)
    assert pair["final_version"] == "one TWO three four" and pair["edit_distance"] == 2
    assert _rows(conn, "decisions", d)[0]["decision"] == "edited"


def test_reject_has_no_edit_pair_and_no_double_decision(conn):
    d = _draft(conn)
    decide.decide(conn, d, "rejected")
    assert _rows(conn, "edit_pairs", d) == []
    try:
        decide.decide(conn, d, "approved_as_is")
        raise AssertionError("expected AlreadyDecided")
    except decide.AlreadyDecided:
        pass


def test_awaiting_drafts_only_cleared_and_undrafted(conn):
    a, b = dedupe.store_new(conn, [_item("A"), _item("B")])
    scores = {"virality": 9, "novelty": 9, "technical": 9, "relevance": 9, "discussion": 9}
    db.insert_score(conn, a, scores, 9.0, True, "m")
    db.insert_score(conn, b, scores, 3.0, False, "m")
    assert [str(r["id"]) for r in db.items_awaiting_drafts(conn, 10)] == [a]
    db.insert_draft(conn, a, "contrarian", "x", "m")
    assert db.items_awaiting_drafts(conn, 10) == []
    assert db.unscored_items(conn, 10) == []


def test_unsent_drafts_respects_age_and_cap(conn):
    [raw_id] = dedupe.store_new(conn, [_item()])
    for i in range(3):
        db.insert_draft(conn, raw_id, "contrarian", f"d{i}", "m")
    old = db.insert_draft(conn, raw_id, "contrarian", "old", "m")
    conn.execute("UPDATE drafts SET generated_at = now() - interval '2 days' WHERE id = %s", (old,))
    assert len(db.unsent_drafts(conn, 12, 10)) == 3
    assert len(db.unsent_drafts(conn, 12, 2)) == 2
