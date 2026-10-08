#!/usr/bin/env python
"""Back up the events database and reconcile it against a baseline.

Scraper work rewrites rows in bulk, so take a snapshot before a run and compare
after it. The comparison is what matters: a scrape that "succeeds" while
silently dropping a venue's events looks fine in the logs and obvious here.

    python db_safety.py backup                 # snapshot + manifest
    python db_safety.py compare                # current vs newest manifest
    python db_safety.py compare <manifest.json>
    python db_safety.py restore <backup.db>    # put a snapshot back
"""

import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB = Path("data/events.db")
BACKUPS = Path("data/backups")
# Spelled out per table alias rather than patched with str.replace, which also
# rewrote the date() call itself into e.date().
UPCOMING = "date >= date('now')"
UPCOMING_E = "e.date >= date('now')"


def _manifest(conn: sqlite3.Connection) -> dict:
    """Counts worth noticing a change in."""
    cur = conn.cursor()
    total = cur.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    upcoming = cur.execute(f"SELECT COUNT(*) FROM events WHERE {UPCOMING}").fetchone()[0]
    dated = cur.execute(
        f"SELECT COUNT(*) FROM events WHERE {UPCOMING} AND date IS NOT NULL"
    ).fetchone()[0]
    placed = cur.execute(
        f"SELECT COUNT(*) FROM events WHERE {UPCOMING} AND neighborhood_id IS NOT NULL"
    ).fetchone()[0]
    by_source = dict(
        cur.execute(
            f"SELECT source, COUNT(*) FROM events WHERE {UPCOMING} GROUP BY source"
        ).fetchall()
    )
    by_hood = dict(
        cur.execute(
            f"""SELECT nb.name, COUNT(e.id) FROM neighborhoods nb
                JOIN events e ON e.neighborhood_id = nb.id AND {UPCOMING_E}
                GROUP BY nb.name"""
        ).fetchall()
    )
    return {
        "taken_at": datetime.now().isoformat(timespec="seconds"),
        "totals": {"all": total, "upcoming": upcoming, "dated": dated, "placed": placed},
        "by_source": by_source,
        "by_neighborhood": by_hood,
    }


def backup() -> Path:
    BACKUPS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BACKUPS / f"events-{stamp}.db"

    src = sqlite3.connect(DB)
    dst = sqlite3.connect(dest)
    with dst:
        # The online backup API copies a consistent snapshot even while the
        # database is in use; a file copy can catch a half-written page.
        src.backup(dst)
    ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
    manifest = _manifest(src)
    dst.close()
    src.close()

    if ok != "ok":
        raise SystemExit(f"backup failed integrity check: {ok}")

    (BACKUPS / f"manifest-{stamp}.json").write_text(json.dumps(manifest, indent=2))
    t = manifest["totals"]
    print(f"backup   : {dest} ({dest.stat().st_size / 1e6:.1f} MB, integrity ok)")
    print(f"manifest : {BACKUPS / f'manifest-{stamp}.json'}")
    print(f"snapshot : {t['upcoming']} upcoming, {t['dated']} dated, {t['placed']} placed")
    return dest


def compare(path: Path | None = None) -> None:
    manifests = sorted(BACKUPS.glob("manifest-*.json"))
    if path is None:
        if not manifests:
            raise SystemExit("no manifests yet - run `backup` first")
        path = manifests[-1]
    before = json.loads(Path(path).read_text())
    after = _manifest(sqlite3.connect(DB))

    print(f"baseline {path.name} ({before['taken_at']})\n")
    print(f"{'':<34}{'before':>9}{'after':>9}{'delta':>9}")
    for key in ("all", "upcoming", "dated", "placed"):
        b, a = before["totals"][key], after["totals"][key]
        print(f"{key:<34}{b:>9}{a:>9}{a - b:>+9}")

    for label, field in (("source", "by_source"), ("neighborhood", "by_neighborhood")):
        b, a = before[field], after[field]
        changed = {
            k: (b.get(k, 0), a.get(k, 0)) for k in set(b) | set(a) if b.get(k, 0) != a.get(k, 0)
        }
        losses = {k: v for k, v in changed.items() if v[1] < v[0]}
        print(f"\n{label}s changed: {len(changed)}   losses: {len(losses)}")
        for k, (bv, av) in sorted(changed.items(), key=lambda kv: kv[1][1] - kv[1][0]):
            mark = "  <-- LOST" if av < bv else ""
            print(f"   {k:<40}{bv:>6} -> {av:<6}{av - bv:>+6}{mark}")


def restore(path: str) -> None:
    source = Path(path)
    if not source.exists():
        raise SystemExit(f"no such backup: {source}")
    # Never overwrite without keeping what is currently there.
    safety = BACKUPS / f"pre-restore-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    BACKUPS.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DB, safety)
    shutil.copy2(source, DB)
    print(f"current db set aside at {safety}")
    print(f"restored {source} -> {DB}")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "backup"
    if command == "backup":
        backup()
    elif command == "compare":
        compare(Path(sys.argv[2]) if len(sys.argv) > 2 else None)
    elif command == "restore":
        restore(sys.argv[2])
    else:
        raise SystemExit(__doc__)
