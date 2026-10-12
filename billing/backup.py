"""Daily database backup. Uses SQLite's own backup call, so it is safe while the app is running (a plain file copy is not,
because recent changes can still be in the -wal file)."""
import datetime
import re
import sqlite3
from pathlib import Path

PATTERN = re.compile(r"^db-(\d{4}-\d{2}-\d{2})\.sqlite3$")


def snapshot(src, dest):
    """Write a consistent copy of the SQLite database `src` to the file `dest`."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    if tmp.exists():
        tmp.unlink()
    source = sqlite3.connect(str(src))
    target = sqlite3.connect(str(tmp))
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    tmp.replace(dest)
    return dest


def prune(folder, keep):
    """Keep the newest `keep` daily backups and delete the older ones."""
    files = sorted((p for p in Path(folder).iterdir() if PATTERN.match(p.name)), key=lambda p: p.name)
    for p in files[:-keep] if keep > 0 else []:
        p.unlink()


def daily_backup(src, folder, today=None, keep=30):
    """Make today's backup if it does not exist yet. Returns its path, or None when it was already there."""
    today = today or datetime.date.today()
    dest = Path(folder) / f"db-{today:%Y-%m-%d}.sqlite3"
    if dest.exists():
        return None
    snapshot(src, dest)
    prune(folder, keep)
    return dest
