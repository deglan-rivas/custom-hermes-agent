"""Unit tests for backup/restore_verify.py (design ref: design.md §12).

Restore verification logic used by backup/restore.sh after `restic
restore`: SQLite integrity checks (with D8 snapshot fallback), skills
git history presence, and the JSON summary printed to the operator.

Stdlib unittest + the real `git` binary (already a project prerequisite
per ops/skills-autocommit.sh), per this project's TDD convention.

Run with: python3 -m unittest discover asistente_personal/tests
"""

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(os.path.dirname(TESTS_DIR), "backup")
sys.path.insert(0, BACKUP_DIR)

import restore_verify  # noqa: E402  (import after sys.path tweak, by design)


def _make_valid_db(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
    conn.execute("INSERT INTO t (val) VALUES ('ok')")
    conn.commit()
    conn.close()


def _init_git_repo(path, commits=1):
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.local"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    for i in range(commits):
        fname = os.path.join(path, f"f{i}.txt")
        with open(fname, "w") as fh:
            fh.write(str(i))
        subprocess.run(["git", "add", "-A"], cwd=path, check=True)
        subprocess.run(["git", "commit", "-q", "-m", f"commit {i}"], cwd=path, check=True)


class TestIntegrityCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_db_reports_ok(self):
        db = os.path.join(self.tmp.name, "vida.db")
        _make_valid_db(db)
        ok, detail = restore_verify.integrity_check(db)
        self.assertTrue(ok)
        self.assertEqual(detail, "ok")

    def test_corrupted_file_reports_not_ok(self):
        # Triangulation: a file with a .db extension but garbage bytes is
        # not a valid SQLite header -> DatabaseError on read, not "ok".
        db = os.path.join(self.tmp.name, "corrupt.db")
        with open(db, "wb") as fh:
            fh.write(b"not a real sqlite file at all, just garbage bytes")
        ok, detail = restore_verify.integrity_check(db)
        self.assertFalse(ok)

    def test_missing_file_reports_not_ok(self):
        ok, detail = restore_verify.integrity_check(os.path.join(self.tmp.name, "missing.db"))
        self.assertFalse(ok)
        self.assertIn("not found", detail)


class TestCountGitCommits(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_git_dir_returns_zero(self):
        plain_dir = os.path.join(self.tmp.name, "no-git")
        os.makedirs(plain_dir)
        self.assertEqual(restore_verify.count_git_commits(plain_dir), 0)

    def test_repo_with_three_commits_returns_three(self):
        repo = os.path.join(self.tmp.name, "skills")
        _init_git_repo(repo, commits=3)
        self.assertEqual(restore_verify.count_git_commits(repo), 3)


class TestResolveDbForVerification(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_live_db_ok_is_used_directly(self):
        live = os.path.join(self.tmp.name, "vida.db")
        _make_valid_db(live)
        path, ok, detail = restore_verify.resolve_db_for_verification(live, self.tmp.name)
        self.assertEqual(path, live)
        self.assertTrue(ok)

    def test_corrupt_live_db_falls_back_to_latest_snapshot(self):
        live = os.path.join(self.tmp.name, "vida.db")
        with open(live, "wb") as fh:
            fh.write(b"garbage, not sqlite")
        older = os.path.join(self.tmp.name, "vida-20260101T000000.snapshot")
        newer = os.path.join(self.tmp.name, "vida-20260201T000000.snapshot")
        _make_valid_db(older)
        _make_valid_db(newer)

        path, ok, detail = restore_verify.resolve_db_for_verification(live, self.tmp.name)

        self.assertEqual(path, newer)
        self.assertTrue(ok)


class TestBuildSummary(unittest.TestCase):
    def test_restore_ok_true_when_all_dbs_ok_and_commits_present(self):
        summary = restore_verify.build_summary(
            target_dir="/tmp/restore-drill",
            snapshot_id="abc123",
            snapshot_time="2026-07-29T03:30:00",
            db_results={"vida.db": ("/tmp/restore-drill/data/vida.db", True, "ok")},
            skills_commit_count=5,
        )
        self.assertTrue(summary["restore_ok"])
        self.assertEqual(summary["databases"]["vida.db"]["ok"], True)
        self.assertEqual(summary["skills_git_commits"], 5)

    def test_restore_ok_false_when_any_db_fails(self):
        summary = restore_verify.build_summary(
            target_dir="/tmp/restore-drill",
            snapshot_id="abc123",
            snapshot_time="2026-07-29T03:30:00",
            db_results={
                "vida.db": ("/tmp/restore-drill/data/vida.db", True, "ok"),
                "state.db": ("/tmp/restore-drill/state.db", False, "database disk image is malformed"),
            },
            skills_commit_count=5,
        )
        self.assertFalse(summary["restore_ok"])

    def test_restore_ok_false_when_no_skills_commits(self):
        summary = restore_verify.build_summary(
            target_dir="/tmp/restore-drill",
            snapshot_id="abc123",
            snapshot_time="2026-07-29T03:30:00",
            db_results={"vida.db": ("/tmp/restore-drill/data/vida.db", True, "ok")},
            skills_commit_count=0,
        )
        self.assertFalse(summary["restore_ok"])


if __name__ == "__main__":
    unittest.main()
