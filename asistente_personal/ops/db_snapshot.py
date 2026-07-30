#!/usr/bin/env python3
"""ops/db_snapshot.py — WAL-safe SQLite snapshot logic.

Design ref: openspec/changes/hermes-personal-assistant/design.md D8, §12.

Produces an online-consistent copy of one or more SQLite databases using
the stdlib `sqlite3` backup API. This is safe for a WAL-mode database with
concurrent writers because `Connection.backup()` takes its own consistent
snapshot rather than doing a byte-level file copy — a plain `cp` of `.db`
without `.db-wal`/`.db-shm` (or mid-write) can capture a torn state.

Invoked nightly at 03:20 by ops/db-snapshot.sh, 10 minutes before the
`restic` service's own 03:30 backup window (D8).

Stdlib only, per project convention (bin/vida.py, tests/test_vida.py).
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime


def snapshot_db(src_path: str, dest_path: str) -> None:
    """Copy `src_path` into `dest_path` via the sqlite3 online backup API.

    Raises FileNotFoundError if `src_path` does not exist. Creates the
    destination directory if needed. Overwrites `dest_path` if present.
    """
    if not os.path.isfile(src_path):
        raise FileNotFoundError(f"source database not found: {src_path}")

    dest_dir = os.path.dirname(dest_path)
    if dest_dir:
        os.makedirs(dest_dir, exist_ok=True)

    src = sqlite3.connect(src_path)
    try:
        dest = sqlite3.connect(dest_path)
        try:
            src.backup(dest)
        finally:
            dest.close()
    finally:
        src.close()


def snapshot_filename(db_path: str, when: datetime) -> str:
    """Build the `<basename>-<YYYYmmddTHHMMSS>.snapshot` output filename."""
    base = os.path.splitext(os.path.basename(db_path))[0]
    stamp = when.strftime("%Y%m%dT%H%M%S")
    return f"{base}-{stamp}.snapshot"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        action="append",
        required=True,
        dest="dbs",
        help="Path to a SQLite DB to snapshot (repeatable).",
    )
    parser.add_argument(
        "--out-dir",
        required=True,
        help="Directory to write <basename>-<timestamp>.snapshot files into.",
    )
    args = parser.parse_args(argv)

    now = datetime.now()
    exit_code = 0
    for db_path in args.dbs:
        dest = os.path.join(args.out_dir, snapshot_filename(db_path, now))
        try:
            snapshot_db(db_path, dest)
            print(f"db_snapshot: wrote {dest}")
        except FileNotFoundError as exc:
            # A missing DB (e.g. state.db not created yet on a fresh install)
            # is not a hard failure for the nightly job — report and continue
            # so one missing file does not skip the rest.
            print(f"db_snapshot: skipped ({exc})", file=sys.stderr)
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
