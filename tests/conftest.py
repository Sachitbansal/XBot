import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL",
                                   "postgresql://xbot:xbot@localhost:5440/xbot_test")


@pytest.fixture
def conn(monkeypatch):
    """Connection to the test DB, wiped before each test."""
    monkeypatch.setattr(config, "DATABASE_URL", TEST_DATABASE_URL)
    import db
    try:
        c = db.connect()
    except Exception as e:
        pytest.skip(f"test DB unavailable: {e}")
    c.execute("TRUNCATE raw_items, item_scores, drafts, decisions, edit_pairs, post_performance CASCADE")
    c.commit()
    yield c
    c.close()
