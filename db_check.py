"""Check PostgreSQL and pgvector using DATABASE_URL from the environment."""

import os

import psycopg


def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("Set DATABASE_URL before running db_check.py.")
        return 1
    try:
        with psycopg.connect(database_url, connect_timeout=5) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                assert cursor.fetchone() == (1,)
                print("SELECT 1: 1")
                cursor.execute(
                    "SELECT extversion FROM pg_extension WHERE extname = %s",
                    ("vector",),
                )
                row = cursor.fetchone()
                if row is None:
                    print("pgvector extension is not installed.")
                    return 1
                print(f"pgvector version: {row[0]}")
    except psycopg.Error:
        # Connection errors may contain connection details; keep them private.
        print("Database check failed. Check configuration and database availability.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
