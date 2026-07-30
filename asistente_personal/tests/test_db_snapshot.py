"""Unit tests for ops/db_snapshot.py (design ref: design.md D8, §12).

WAL-safe SQLite snapshot logic — the online consistent copy via
sqlite3's backup API is the real logic worth testing here, per this
project's TDD convention (stdlib unittest only, see tests/test_vida.py).

Run with: python3 -m unittest discover asistente_personal/tests
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
OPS_DIR = os.path.join(os.path.dirname(TESTS_DIR), "ops")
sys.path.insert(0, OPS_DIR)

import db_snapshot  # noqa: E402  (import after sys.path tweak, by design)


def _make_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
    conn.executemany("INSERT INTO t (val) VALUES (?)", [(r,) for r in rows])
    conn.commit()
    conn.close()


class TestSnapshotDb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_snapshot_copies_all_rows_from_a_simple_db(self):
        src = os.path.join(self.tmp.name, "vida.db")
        dest = os.path.join(self.tmp.name, "out", "vida.snapshot")
        _make_db(src, ["a", "b", "c"])

        db_snapshot.snapshot_db(src, dest)

        conn = sqlite3.connect(dest)
        rows = conn.execute("SELECT val FROM t ORDER BY id").fetchall()
        conn.close()
        self.assertEqual([r[0] for r in rows], ["a", "b", "c"])

    def test_snapshot_captures_wal_mode_writes(self):
        # Triangulation: a different DB, WAL journal mode enabled, different
        # row count — proves the backup API captures more than a plain copy
        # of the -shm/-wal-less path would.
        src = os.path.join(self.tmp.name, "state.db")
        conn = sqlite3.connect(src)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE evt (id INTEGER PRIMARY KEY, name TEXT)")
        conn.executemany(
            "INSERT INTO evt (name) VALUES (?)",
            [("uno",), ("dos",), ("tres",), ("cuatro",)],
        )
        conn.commit()
        conn.close()

        dest = os.path.join(self.tmp.name, "out", "state.snapshot")
        db_snapshot.snapshot_db(src, dest)

        out = sqlite3.connect(dest)
        count = out.execute("SELECT COUNT(*) FROM evt").fetchone()[0]
        out.close()
        self.assertEqual(count, 4)

    def test_snapshot_missing_source_raises_file_not_found(self):
        missing = os.path.join(self.tmp.name, "does-not-exist.db")
        dest = os.path.join(self.tmp.name, "out.snapshot")
        with self.assertRaises(FileNotFoundError):
            db_snapshot.snapshot_db(missing, dest)


class TestSnapshotFilename(unittest.TestCase):
    def test_filename_embeds_basename_and_timestamp(self):
        when = datetime(2026, 7, 29, 3, 20, 0)
        name = db_snapshot.snapshot_filename("/data/vida.db", when)
        self.assertEqual(name, "vida-20260729T032000.snapshot")

    def test_filename_differs_for_different_basenames(self):
        when = datetime(2026, 7, 29, 3, 20, 0)
        name = db_snapshot.snapshot_filename("/data/state.db", when)
        self.assertEqual(name, "state-20260729T032000.snapshot")


if __name__ == "__main__":
    unittest.main()
