import sqlite3
import logging
import time
from pathlib import Path


DB_PATH = Path(__file__).resolve().with_name("parking.db")
logger = logging.getLogger(__name__)


class ToolError(Exception):
    """Expected failure whose message is safe to show to the model."""


class UnknownLotError(ToolError):
    pass


class UnknownToolError(ToolError):
    pass


class BadArgumentsError(ToolError):
    pass


class TemporaryToolError(ToolError):
    pass


def _latest_readings(lot_id: str) -> list:
    """Retry only SQLite lock contention, twice with bounded backoff."""
    for attempt in range(3):
        try:
            return _read_latest(lot_id)
        except sqlite3.OperationalError as exc:
            code = getattr(exc, "sqlite_errorcode", 0)
            if (code & 0xFF) not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise
            logger.warning("Database lock on attempt %s", attempt + 1, exc_info=True)
            if attempt == 2:
                raise TemporaryToolError(
                    "Database is temporarily busy after retries. Please try again later."
                ) from exc
            time.sleep(0.1 * (2 ** attempt))


def _read_latest(lot_id: str) -> list:
    if not isinstance(lot_id, str) or not lot_id.strip():
        raise BadArgumentsError("lot_id must be a non-empty string.")
    if not DB_PATH.is_file():
        raise FileNotFoundError(f"{DB_PATH} does not exist; run python seed.py first.")

    connection = sqlite3.connect(DB_PATH.as_uri() + "?mode=ro", uri=True, timeout=0.2)
    try:
        if connection.execute(
            "SELECT 1 FROM lots WHERE lot_id = ?", (lot_id,)
        ).fetchone() is None:
            raise UnknownLotError("Unknown lot ID. Use the exact, case-sensitive identifier without the 'Lot ' prefix.")

        rows = connection.execute(
            """
            SELECT s.slot_id, r.occupied, r.timestamp
            FROM slots AS s
            LEFT JOIN readings AS r
                ON r.slot_id = s.slot_id
                AND r.timestamp = (
                    SELECT MAX(timestamp) FROM readings WHERE slot_id = s.slot_id
                )
            WHERE s.lot_id = ?
            ORDER BY s.slot_id
            """,
            (lot_id,),
        ).fetchall()
        if any(row[1] is None for row in rows):
            raise ValueError(f"Lot {lot_id!r} has slots without readings.")
        return rows
    finally:
        connection.close()


def get_lot_status(lot_id: str) -> dict:
    """Return counts and the newest UTC timestamp across latest slot readings.

    Invalid or unknown lot IDs raise ToolError. An empty lot has zero counts
    and a None timestamp. Missing readings raise ValueError; missing databases
    raise FileNotFoundError.
    """
    rows = _latest_readings(lot_id)
    occupied = sum(row[1] for row in rows)
    return {
        "lot_id": lot_id,
        "total_slots": len(rows),
        "occupied": occupied,
        "free": len(rows) - occupied,
        "timestamp": max((row[2] for row in rows), default=None),
    }


def list_free_slots(lot_id: str) -> dict:
    """Return sorted IDs free at each slot's latest reading.

    Uses the same timestamp convention and error behavior as get_lot_status.
    """
    rows = _latest_readings(lot_id)
    return {
        "lot_id": lot_id,
        "free_slots": [row[0] for row in rows if row[1] == 0],
        "timestamp": max((row[2] for row in rows), default=None),
    }
