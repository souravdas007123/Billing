import datetime
import sqlite3
import tempfile
import unittest
from pathlib import Path

from billing.backup import daily_backup, snapshot


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db = self.tmp / "db.sqlite3"
        c = sqlite3.connect(self.db)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("create table t(x)")
        c.execute("insert into t values (1)")
        c.commit()  # stays in the -wal file until a checkpoint: a plain file copy would lose it
        self.c = c

    def tearDown(self):
        self.c.close()

    def test_snapshot_contains_recent_wal_data(self):
        out = snapshot(self.db, self.tmp / "b" / "copy.sqlite3")
        self.assertEqual(sqlite3.connect(out).execute("select x from t").fetchall(), [(1,)])

    def test_daily_once_and_pruned(self):
        folder = self.tmp / "backups"
        d = datetime.date(2026, 10, 1)
        for i in range(5):
            self.assertIsNotNone(daily_backup(self.db, folder, d + datetime.timedelta(days=i), keep=3))
        self.assertIsNone(daily_backup(self.db, folder, d + datetime.timedelta(days=4), keep=3))  # already made today
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["db-2026-10-03.sqlite3", "db-2026-10-04.sqlite3", "db-2026-10-05.sqlite3"])


if __name__ == "__main__":
    unittest.main()
