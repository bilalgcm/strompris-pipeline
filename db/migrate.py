"""Run one SQL migration against the database in DATABASE_URL.

Usage (from the repo root):
    python db/migrate.py up 001
    python db/migrate.py down 001

Each file runs in a single transaction, so a failing migration changes nothing.
The SQL is written to be safe to run twice (IF NOT EXISTS / IF EXISTS).
"""

import os
import sys
from pathlib import Path

import psycopg

MIGRATIONS = Path(__file__).parent / "migrations"


def find_migration(number: str, direction: str) -> Path:
    matches = sorted(MIGRATIONS.glob(f"{number}_*.{direction}.sql"))
    if len(matches) != 1:
        sys.exit(f"Expected exactly one migration {number} ({direction}), found {len(matches)}")
    return matches[0]


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in ("up", "down"):
        sys.exit(__doc__)
    direction, number = sys.argv[1], sys.argv[2]
    path = find_migration(number, direction)

    db = os.environ.get("DATABASE_URL")
    if not db:
        sys.exit("DATABASE_URL is not set")

    with psycopg.connect(db) as conn:  # commits on success, rolls back on error
        conn.execute(path.read_text())
    print(f"Applied {path.name}")


if __name__ == "__main__":
    main()
