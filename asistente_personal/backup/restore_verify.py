#!/usr/bin/env python3
"""backup/restore_verify.py — restore verification logic.

Design ref: openspec/changes/hermes-personal-assistant/design.md §12.

Used by backup/restore.sh after `restic restore` to prove the restored
volume is actually usable, not merely present:

1. SQLite `PRAGMA integrity_check` on each live DB, falling back to the
   latest D8 (ops/db_snapshot.py) snapshot when the live file fails.
2. Confirms `~/.hermes/skills/` git history exists (design §11 / spec §9).
3. Builds the JSON summary `restore.sh` prints for the operator.

Stdlib + the system `git` binary only, per project convention.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sqlite3
import subprocess
import sys


def integrity_check(db_path: str) -> tuple[bool, str]:
    """Run `PRAGMA integrity_check` on db_path.

    Returns (True, "ok") when SQLite reports a single "ok" row. Returns
    (False, <detail>) if the file is missing, cannot be opened as a SQLite
    database (corrupted header), or integrity_check reports a problem.
    """
    if not os.path.isfile(db_path):
        return False, f"file not found: {db_path}"
    try:
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        return False, str(exc)
    if row is None:
        return False, "no result from integrity_check"
    result = row[0]
    return (result == "ok"), result


def count_git_commits(repo_dir: str) -> int:
    """Count commits reachable from HEAD in repo_dir.

    Returns 0 if repo_dir is not a git repository or has no commits yet —
    never raises, since "no history" is a real (if bad) restore outcome to
    report, not a script failure.
    """
    if not os.path.isdir(os.path.join(repo_dir, ".git")):
        return 0
    try:
        out = subprocess.run(
            ["git", "-C", repo_dir, "rev-list", "--count", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return 0
    return int(out.stdout.strip())


def _latest_snapshot_for(basename: str, snapshot_dir: str) -> str | None:
    pattern = os.path.join(snapshot_dir, f"{basename}-*.snapshot")
    matches = sorted(glob.glob(pattern))
    return matches[-1] if matches else None


def resolve_db_for_verification(live_path: str, snapshot_dir: str) -> tuple[str, bool, str]:
    """Prefer live_path; fall back to the latest D8 snapshot on failure.

    Returns (path_actually_verified, ok, detail). This is what makes
    restore.sh's report honest when the live copy is torn but the
    03:20 sqlite3.backup() snapshot (db_snapshot.py) is intact.
    """
    ok, detail = integrity_check(live_path)
    if ok:
        return live_path, ok, detail

    basename = os.path.splitext(os.path.basename(live_path))[0]
    fallback = _latest_snapshot_for(basename, snapshot_dir)
    if fallback is None:
        return live_path, ok, detail

    fb_ok, fb_detail = integrity_check(fallback)
    return fallback, fb_ok, fb_detail


def build_summary(
    target_dir: str,
    snapshot_id: str,
    snapshot_time: str,
    db_results: dict[str, tuple[str, bool, str]],
    skills_commit_count: int,
) -> dict:
    """Assemble the JSON summary restore.sh prints at the end of a drill.

    `restore_ok` is only true when every DB passed integrity (live or
    snapshot fallback) AND the skills git repo has at least one commit —
    a restore that skips the skills history is a partial restore.
    """
    return {
        "target_dir": target_dir,
        "snapshot_id": snapshot_id,
        "snapshot_time": snapshot_time,
        "databases": {
            name: {"path": path, "ok": ok, "detail": detail}
            for name, (path, ok, detail) in db_results.items()
        },
        "skills_git_commits": skills_commit_count,
        "restore_ok": (
            all(ok for _path, ok, _detail in db_results.values())
            and skills_commit_count > 0
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="Restored volume root (e.g. state/hermes)")
    parser.add_argument(
        "--db",
        action="append",
        required=True,
        dest="dbs",
        help="DB path relative to --target to integrity-check (repeatable).",
    )
    parser.add_argument("--snapshot-dir", required=True, help="Dir with D8 *.snapshot fallback files")
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--snapshot-time", required=True)
    args = parser.parse_args(argv)

    db_results: dict[str, tuple[str, bool, str]] = {}
    for rel in args.dbs:
        abs_path = os.path.join(args.target, rel)
        db_results[rel] = resolve_db_for_verification(abs_path, args.snapshot_dir)

    skills_dir = os.path.join(args.target, "skills")
    commits = count_git_commits(skills_dir)

    summary = build_summary(args.target, args.snapshot_id, args.snapshot_time, db_results, commits)
    print(json.dumps(summary, indent=2))
    return 0 if summary["restore_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
