"""Terminal review for build phase (stand-in for the Telegram bot).

Walks every delivered-but-undecided draft: [a]pprove / [e]dit / [r]eject / [s]kip / [q]uit.
Edit opens $EDITOR (falls back to a single input line). Writes the same decisions /
edit_pairs rows the bot will.
"""
import os
import subprocess
import sys
import tempfile

import db
from pipeline import decide


def edit_text(original: str) -> str:
    editor = os.environ.get("EDITOR")
    if not editor:
        return input("edited version (one line): ").strip()
    with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False) as f:
        f.write(original)
        path = f.name
    try:
        subprocess.run([editor, path], check=True)
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    finally:
        os.unlink(path)


def main() -> int:
    with db.connect() as conn:
        drafts = db.undecided_drafts(conn)
        if not drafts:
            print("Nothing to review.")
            return 0
        print(f"{len(drafts)} drafts to review.\n")
        last_item = None
        for i, d in enumerate(drafts, 1):
            if d["raw_item_id"] != last_item:
                print(f"\n=== {d['title']}\n    {d['source_url']}")
                last_item = d["raw_item_id"]
            print(f"\n[{i}/{len(drafts)}] {d['angle_type']} · {str(d['id'])[:8]} · {len(d['ai_draft'])} chars")
            print(f"  {d['ai_draft']}")

            while True:
                choice = input("  [a]pprove [e]dit [r]eject [s]kip [q]uit > ").strip().lower()[:1]
                if choice in ("a", "e", "r", "s", "q"):
                    break
            if choice == "q":
                break
            if choice == "s":
                continue

            final = None
            if choice == "e":
                final = edit_text(d["ai_draft"])
                if not final:
                    print("  empty edit, skipped")
                    continue
            result = decide.decide(conn, d["id"], decide.ACTIONS[choice], final)
            extra = f" ({result['edit_distance']} word edits)" if result["decision"] == "edited" else ""
            print(f"  → {result['decision']}{extra}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print()
        sys.exit(0)
