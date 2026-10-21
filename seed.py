import random
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


DB_PATH = Path(__file__).resolve().with_name("parking.db")


def main() -> None:
    rng = random.Random(42)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    with sqlite3.connect(DB_PATH) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS lots (
                lot_id TEXT PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS slots (
                slot_id TEXT PRIMARY KEY,
                lot_id TEXT NOT NULL REFERENCES lots(lot_id)
            );
            CREATE TABLE IF NOT EXISTS readings (
                slot_id TEXT NOT NULL REFERENCES slots(slot_id),
                timestamp TEXT NOT NULL,
                occupied INTEGER NOT NULL CHECK (occupied IN (0, 1)),
                PRIMARY KEY (slot_id, timestamp)
            );
        """)
        connection.execute("DELETE FROM readings")
        connection.execute("DELETE FROM slots")
        connection.execute("DELETE FROM lots")

        for lot_id, capacity in (("A", 20), ("B", 12)):
            connection.execute("INSERT INTO lots VALUES (?)", (lot_id,))
            for number in range(1, capacity + 1):
                slot_id = f"{lot_id}-{number:02d}"
                connection.execute(
                    "INSERT INTO slots VALUES (?, ?)", (slot_id, lot_id)
                )
                connection.executemany(
                    "INSERT INTO readings VALUES (?, ?, ?)",
                    (
                        (
                            slot_id,
                            (start + timedelta(hours=hour)).isoformat(),
                            rng.randint(0, 1),
                        )
                        for hour in range(24)
                    ),
                )

    print(f"Seeded {DB_PATH} with 2 lots, 32 slots, and 768 readings.")


if __name__ == "__main__":
    main()
