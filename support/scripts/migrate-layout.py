"""Move legacy local data into the source-specific layout. Stop services first."""
from contextlib import closing
import json
import hashlib
from pathlib import Path
import shutil
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from support.config import load_settings
from support.runtime import BASE_DIR, DATA_DIR, GARMIN_DATA_DIR, PUBLISH_DATA_DIR
from support.storage import atomic_json, database, hevy_database
from support.sync import export_data


def move_within_workspace(source, target):
    """Never overwrite existing data; verify recursive moves stay under the data root."""
    source, target = source.resolve(), target.resolve()
    if not source.is_relative_to(DATA_DIR.resolve()) or not target.is_relative_to(DATA_DIR.resolve()):
        raise ValueError("Migration paths must stay inside the configured data directory")
    if not source.exists():
        return
    if target.exists():
        if source.is_dir() and target.is_dir():
            for child in list(source.iterdir()):
                move_within_workspace(child, target / child.name)
            source.rmdir()
            return
        if source.is_file() and target.is_file() and hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(target.read_bytes()).digest():
            source.unlink()
            return
        raise FileExistsError(f"Migration destination already exists with different contents: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))


def migrate():
    settings = load_settings()
    old = DATA_DIR / "health_sync"
    old_database = old / "health.sqlite3"
    archive = DATA_DIR / "archive" / "previous-layout"
    if old_database.exists():
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        if not settings.database.exists():
            with closing(sqlite3.connect(old_database)) as source, closing(sqlite3.connect(settings.database)) as target:
                source.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("Copied Health database failed its integrity check; original data retained")
        else:
            # A Windows viewer can hold the old file open after a successful copy.
            # Permit a retry only if the stored totals match, never overwrite either.
            with closing(sqlite3.connect(old_database)) as source, closing(sqlite3.connect(settings.database)) as target:
                if nutrition_totals(source) != nutrition_totals(target):
                    raise FileExistsError("Old and new Health totals differ; reconcile them before migrating")
        # The old shared database held Hevy history. Copy before removing it from Health.
        with database(settings) as source:
            has_workouts = source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workouts'").fetchone()
            if has_workouts:
                workouts = source.execute("SELECT id, payload FROM workouts").fetchall()
                with hevy_database(settings) as target:
                    existing = [tuple(row) for row in target.execute("SELECT id, payload FROM workouts ORDER BY id")]
                    supplied = sorted(tuple(row) for row in workouts)
                    if existing and existing != supplied:
                        raise RuntimeError("Hevy database contains different history; original shared data retained")
                    target.executemany("INSERT OR IGNORE INTO workouts VALUES (?, ?)", supplied)
                    synced = source.execute("SELECT value FROM sync_state WHERE name='hevy_synced_at'").fetchone()
                    if synced:
                        target.execute("INSERT OR REPLACE INTO sync_state VALUES ('hevy_synced_at', ?)", (synced[0],))
                source.execute("DROP TABLE workouts")
                source.execute("DELETE FROM sync_state WHERE name='hevy_synced_at'")
        export_data(settings)
        archive_target = archive / "health_sync"
        retry = 1
        while archive_target.exists():
            archive_target = archive / f"health_sync-retry-{retry}"
            retry += 1
        move_within_workspace(old, archive_target)
        print("Health and Hevy databases separated; original shared data archived.")

    for name in ("sleep_data.json", "daily_steps.json", "weights.json"):
        move_within_workspace(DATA_DIR / name, GARMIN_DATA_DIR / name)
    move_within_workspace(DATA_DIR / "garmin_tokens", GARMIN_DATA_DIR / "tokens")
    for name in ("sleep_sheet_notes.json", "sleep_sheet_notes.pending.json"):
        move_within_workspace(DATA_DIR / name, PUBLISH_DATA_DIR / name)
    for name in ("garmin_tokens.json", "workouts.json"):
        move_within_workspace(DATA_DIR / name, archive / name)
    legacy_token = BASE_DIR / "garmin_tokens.json"
    if legacy_token.exists():
        target = archive / "legacy_root_garmin_tokens.json"
        if target.exists():
            raise FileExistsError("Legacy token archive already exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        legacy_token.rename(target)
    restore_saved_session(archive)
    for path in (GARMIN_DATA_DIR, settings.data_dir, settings.hevy_directory, PUBLISH_DATA_DIR):
        path.mkdir(parents=True, exist_ok=True)
    print("Data organised under garmin, health, hevy and publish.")


def restore_saved_session(archive):
    from support.runtime import configured_path
    token_dir = configured_path("GARMIN_TOKENS", GARMIN_DATA_DIR / "tokens")
    token_file = token_dir / "garmin_tokens.json"
    if token_file.exists():
        return
    candidates = [archive / "garmin_tokens.json", archive / "legacy_root_garmin_tokens.json"]
    candidates = sorted((path for path in candidates if path.exists()),
                        key=lambda path: path.stat().st_mtime, reverse=True)
    for candidate in candidates:
        payload = json.loads(candidate.read_text(encoding="utf-8-sig"))
        if isinstance(payload, dict) and all(isinstance(payload.get(key), str) and payload[key]
                                             for key in ("di_token", "di_refresh_token", "di_client_id")):
            atomic_json(token_file, payload)
            print("Existing Garmin session restored to the configured token directory; no login requested.")
            return


def nutrition_totals(conn):
    from support.config import DAILY_COLUMNS
    columns = [row[1] for row in conn.execute("PRAGMA table_info(nutrition)")]
    if columns[0] == "day":
        return {(day, metric): quantity for day, metric, quantity in conn.execute("SELECT day, metric, quantity FROM nutrition")}
    totals = {}
    for day, *values in conn.execute("SELECT date, calories, protein, carbs, fat FROM nutrition"):
        for metric, value in zip(DAILY_COLUMNS.values(), values):
            if value is not None:
                totals[(day, metric)] = value
    for day, details in conn.execute("SELECT date, details FROM nutrition_metadata"):
        totals.update({(day, metric): value for metric, value in json.loads(details)["extras"].items()})
    return totals


if __name__ == "__main__":
    migrate()
