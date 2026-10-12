"""Shared transactional storage and atomic file writes."""
from contextlib import contextmanager
from datetime import datetime, timezone
import csv
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from support.config import Settings, DAILY_COLUMNS

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def store_nutrition_rows(conn, rows):
    """Write supplied totals only, keeping omitted columns and other dates intact."""
    days = {}
    for day, metric, quantity, source, received in rows:
        days.setdefault(day, []).append((metric, quantity, source, received))
    metric_columns = {metric: column for column, metric in DAILY_COLUMNS.items()}
    for day, totals in days.items():
        values = {metric_columns[metric]: quantity for metric, quantity, _, _ in totals
                  if metric in metric_columns}
        columns = ["date", *values]
        # Column names come exclusively from DAILY_COLUMNS, never the request.
        update = ", ".join(f"{column}=excluded.{column}" for column in values)
        conflict = f"DO UPDATE SET {update}" if values else "DO NOTHING"
        conn.execute(f"INSERT INTO nutrition ({', '.join(columns)}) "
                     f"VALUES ({', '.join('?' for _ in columns)}) "
                     f"ON CONFLICT(date) {conflict}", [day, *values.values()])
        existing = conn.execute("SELECT details FROM nutrition_metadata WHERE date=?", (day,)).fetchone()
        details = json.loads(existing[0]) if existing else {"sources": {}, "received_at": {}, "extras": {}}
        for metric, quantity, source, received in totals:
            details["sources"][metric] = source
            details["received_at"][metric] = received
            if metric not in metric_columns:
                details["extras"][metric] = quantity
        conn.execute("INSERT INTO nutrition_metadata VALUES (?, ?) "
                     "ON CONFLICT(date) DO UPDATE SET details=excluded.details",
                     (day, json.dumps(details, allow_nan=False)))


def initialize_database(conn):
    # One transaction covers the schema migration and preserves legacy data on failure.
    conn.execute("BEGIN IMMEDIATE")
    legacy_columns = [row[1] for row in conn.execute("PRAGMA table_info(nutrition)")]
    legacy = legacy_columns == ["day", "metric", "quantity", "source", "received_at"]
    if legacy_columns and not legacy and legacy_columns != ["date", *DAILY_COLUMNS]:
        raise ValueError("Unrecognised nutrition schema; existing data was left unchanged")
    conn.execute("DROP VIEW IF EXISTS daily_nutrition")
    if legacy:
        conn.execute("ALTER TABLE nutrition RENAME TO nutrition_legacy")
    conn.execute("CREATE TABLE IF NOT EXISTS nutrition ("
                 "date TEXT PRIMARY KEY NOT NULL, calories REAL, protein REAL, carbs REAL, fat REAL)")
    conn.execute("CREATE TABLE IF NOT EXISTS nutrition_metadata ("
                 "date TEXT PRIMARY KEY NOT NULL, details TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS sync_state (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
    if legacy:
        rows = conn.execute("SELECT day, metric, quantity, source, received_at "
                            "FROM nutrition_legacy ORDER BY day, metric").fetchall()
        store_nutrition_rows(conn, rows)
        conn.execute("DROP TABLE nutrition_legacy")


@contextmanager
def database(settings: Settings):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.database, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        with conn:
            initialize_database(conn)
        with conn:
            yield conn
    finally:
        conn.close()


def atomic_json(path: Path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            json.dump(content, output, indent=2, ensure_ascii=False, allow_nan=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=["date", *DAILY_COLUMNS])
            writer.writeheader()
            writer.writerows(rows)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def hevy_database(settings: Settings):
    settings.hevy_directory.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.hevy_database, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        with conn:
            conn.execute("CREATE TABLE IF NOT EXISTS workouts (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS sync_state (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
            yield conn
    finally:
        conn.close()


def set_state(conn, name: str, value: str):
    conn.execute("INSERT OR REPLACE INTO sync_state VALUES (?, ?)", (name, value))


def save_to_json(data: list[dict], record_type:str, output_file: str | Path) -> None:
    """Save data to a JSON file."""
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    atomic_json(output_path, data)

    print(f"    Saved {len(data)} {record_type} to {output_path}\n")
