"""One fetch → dedupe → score → generate → send cycle. Safe to run repeatedly from cron.

All state lives in Postgres; a Postgres advisory lock stops overlapping runs if a
cycle ever takes longer than the cron interval.
"""
import logging
import sys
import time

import config
import db
from fetchers import get_fetchers
from pipeline import dedupe, generate, score, send

log = logging.getLogger("run_cycle")
LOCK_KEY = 0x58B07  # arbitrary, app-specific


def fetch_all() -> list[dict]:
    items = []
    fetchers = get_fetchers()
    for name in config.ENABLED_SOURCES:
        try:
            got = fetchers[name]()
            log.info("fetch %-16s %3d items", name, len(got))
            items += got
        except Exception as e:
            log.warning("fetch %s failed: %s", name, e)
    return items


def run() -> int:
    started = time.monotonic()
    with db.connect() as conn:
        if not conn.execute("SELECT pg_try_advisory_lock(%s) AS ok", (LOCK_KEY,)).fetchone()["ok"]:
            log.warning("another cycle is still running; exiting")
            return 0
        conn.commit()

        new_ids = dedupe.store_new(conn, fetch_all())
        conn.commit()
        log.info("stored %d new items", len(new_ids))

        s = score.score_pending(conn)
        log.info("scoring: %s", s)
        g = generate.generate_pending(conn)
        log.info("generation: %s", g)
        t = send.send_pending(conn)
        log.info("telegram: %s", t)

        conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
    log.info("cycle done in %.1fs", time.monotonic() - started)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.exit(run())
