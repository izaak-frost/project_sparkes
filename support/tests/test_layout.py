from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from support.config import Settings

spec = importlib.util.spec_from_file_location("migrate_layout", Path(__file__).resolve().parents[1] / "scripts/migrate-layout.py")
layout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(layout)


class LayoutTests(unittest.TestCase):
    def test_saved_session_restored_from_archive_without_overwriting_current_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "archive"
            archive.mkdir()
            saved = {"di_token": "test-token", "di_refresh_token": "test-refresh", "di_client_id": "test-client"}
            (archive / "legacy_root_garmin_tokens.json").write_text(json.dumps(saved))
            with patch("support.runtime.configured_path", return_value=root / "tokens"):
                layout.restore_saved_session(archive)
                token = root / "tokens/garmin_tokens.json"
                self.assertEqual(json.loads(token.read_text()), saved)
                token.write_text('{"existing":"keep"}')
                layout.restore_saved_session(archive)
                self.assertEqual(json.loads(token.read_text()), {"existing": "keep"})

    def test_migration_preserves_shared_history_and_can_be_run_again(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"
            old = data / "health_sync"
            old.mkdir(parents=True)
            with closing(sqlite3.connect(old / "health.sqlite3")) as conn, conn:
                conn.executescript("""
                    CREATE TABLE nutrition (day TEXT, metric TEXT, quantity REAL, source TEXT, received_at TEXT, PRIMARY KEY(day, metric));
                    INSERT INTO nutrition VALUES ('2026-10-07', 'calories_kcal', 2100, 'nutracheck', '2026-10-08T10:00:00+00:00');
                    INSERT INTO nutrition VALUES ('2026-10-07', 'protein_g', 140, 'nutracheck', '2026-10-08T10:00:00+00:00');
                    CREATE TABLE workouts (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                    INSERT INTO workouts VALUES ('existing', '{"id":"existing","exercises":[]}');
                    CREATE TABLE sync_state (name TEXT PRIMARY KEY, value TEXT NOT NULL);
                    INSERT INTO sync_state VALUES ('hevy_synced_at', '2026-10-08T10:00:00+00:00');
                """)
            (data / "sleep_data.json").write_text('[{"calendarDate":"2026-10-07"}]')
            (data / "sleep_sheet_notes.pending.json").write_text('{"2026-10-07":"Keep"}')
            settings = Settings(data / "health", hevy_data_dir=data / "hevy")
            with patch.object(layout, "BASE_DIR", root), patch.object(layout, "DATA_DIR", data), patch.object(layout, "GARMIN_DATA_DIR", data / "garmin"), patch.object(layout, "PUBLISH_DATA_DIR", data / "publish"), patch.object(layout, "load_settings", return_value=settings):
                layout.migrate()
                layout.migrate()
            with closing(sqlite3.connect(settings.database)) as conn:
                self.assertEqual(conn.execute("SELECT * FROM nutrition").fetchone(), ("2026-10-07", 2100, 140, None, None))
                self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='workouts'").fetchone())
            with closing(sqlite3.connect(settings.hevy_database)) as conn:
                self.assertEqual(conn.execute("SELECT id FROM workouts").fetchone()[0], "existing")
                self.assertEqual(conn.execute("SELECT value FROM sync_state WHERE name='hevy_synced_at'").fetchone()[0], "2026-10-08T10:00:00+00:00")
            self.assertEqual(json.loads((data / "hevy/hevy_workouts.json").read_text())[0]["id"], "existing")
            self.assertTrue((data / "archive/previous-layout/health_sync/health.sqlite3").exists())
            self.assertEqual((data / "garmin/sleep_data.json").read_text(), '[{"calendarDate":"2026-10-07"}]')
            self.assertEqual((data / "publish/sleep_sheet_notes.pending.json").read_text(), '{"2026-10-07":"Keep"}')

    def test_move_rejects_paths_outside_data_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / "data"
            data.mkdir()
            source = data / "source.json"
            target = data / "target.json"
            source.write_text('original')
            target.write_text('existing')
            with patch.object(layout, "DATA_DIR", data):
                with self.assertRaises(FileExistsError):
                    layout.move_within_workspace(source, target)
                with self.assertRaises(ValueError):
                    layout.move_within_workspace(source, data.parent / "outside.json")
            self.assertEqual(source.read_text(), 'original')
            self.assertEqual(target.read_text(), 'existing')
