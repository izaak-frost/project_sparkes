import asyncio
import csv
from contextlib import closing
from datetime import datetime, timedelta
import json
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

from support.config import Settings
from support.storage import database, hevy_database
from support.sync import export_data
from health_extract.nutrition import ingest_nutrition, parse_nutrition
from hevy_extract.workouts import request_hevy, sync_hevy
from health_extract.receiver import create_app


def payload(quantity=2000, day="2026-10-07", field="calories_kcal"):
    return {"date": day, "source": "nutracheck", field: quantity}


class TemporaryDatabase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.settings = Settings(Path(self.temporary.name), "test-key", "a" * 40)


class PipelineTests(TemporaryDatabase):
    def test_grouped_upload_and_correction_keep_dates_and_nutrients(self):
        grouped = {"calories_kcal": [{"date": "2026-10-06", "value": 2100}, {"date": "2026-10-07", "value": 2250}],
                   "protein_g": [{"date": "2026-10-07", "value": 160}]}
        self.assertEqual(ingest_nutrition(self.settings, grouped), 3)
        ingest_nutrition(self.settings, grouped)
        ingest_nutrition(self.settings, {"Calories": [{"date": "2026-10-07", "value": 2200}]})
        with database(self.settings) as conn:
            rows = [tuple(row) for row in conn.execute("SELECT * FROM nutrition ORDER BY date")]
            self.assertEqual([row[1] for row in conn.execute("PRAGMA table_info(nutrition)")],
                             ["date", "calories", "protein", "carbs", "fat"])
        self.assertEqual(rows, [("2026-10-06", 2100, None, None, None),
                               ("2026-10-07", 2200, 160, None, None)])

    def test_invalid_grouped_batch_keeps_existing_data(self):
        ingest_nutrition(self.settings, payload())
        bad_batches = [
            {"calories_kcal": [{"date": "2026-10-07", "value": 1800}], "protein_g": [{"date": "2026-10-07", "value": -1}]},
            {"Calories": [{"date": "2026-10-07", "value": 1800}, {"date": "2026-10-07", "value": 200}]},
            {"Calories": [{"date": "2026-10-07", "value": "1800"}]},
            {"Calories": [{"date": "2026-10-07", "value": 1800}], "source": "other app"},
            {"Calories": []},
        ]
        for batch in bad_batches:
            with self.assertRaises(ValueError):
                ingest_nutrition(self.settings, batch)
        with database(self.settings) as conn:
            self.assertEqual(conn.execute("SELECT calories FROM nutrition").fetchone()[0], 2000)

    def test_replayed_and_corrected_uploads_replace_totals(self):
        for amount in (2000, 2000, 1800):
            ingest_nutrition(self.settings, payload(amount))
        with database(self.settings) as conn:
            self.assertEqual([row[0] for row in conn.execute("SELECT calories FROM nutrition")], [1800])

    def test_partial_metric_upload_keeps_other_metrics_and_days(self):
        ingest_nutrition(self.settings, payload())
        ingest_nutrition(self.settings, payload(140, field="protein_g"))
        ingest_nutrition(self.settings, payload(1900, day="2026-10-06"))
        ingest_nutrition(self.settings, payload(150, field="protein_g"))
        export_data(self.settings)
        days = json.loads((self.settings.data_dir / "daily_nutrition.json").read_text())
        self.assertEqual(len(days), 2)
        self.assertEqual(days, [
            {"date": "2026-10-06", "calories": 1900, "protein": None, "carbs": None, "fat": None},
            {"date": "2026-10-07", "calories": 2000, "protein": 150, "carbs": None, "fat": None},
        ])
        with (self.settings.data_dir / "daily_nutrition.csv").open(newline="") as exported:
            csv_rows = list(csv.DictReader(exported))
        self.assertEqual(csv_rows[1], {"date": "2026-10-07", "calories": "2000.0",
                                      "protein": "150.0", "carbs": "", "fat": ""})
        with database(self.settings) as conn:
            stored_rows = [dict(row) for row in conn.execute("SELECT * FROM nutrition ORDER BY date")]
        self.assertEqual(stored_rows, days)

    def test_invalid_upload_has_no_partial_writes(self):
        ingest_nutrition(self.settings, payload())
        with self.assertRaises(ValueError):
            ingest_nutrition(self.settings, {**payload(1800), "protein_g": -1})
        with database(self.settings) as conn:
            self.assertEqual(conn.execute("SELECT calories FROM nutrition").fetchone()[0], 2000)

    def test_rejects_unknown_fields_and_other_sources(self):
        for bad in (payload(field="active_energy"), {**payload(), "source": "another app"},
                    {"date": "2026-10-07", "source": "nutracheck"}, [payload()]):
            with self.assertRaises(ValueError):
                parse_nutrition(bad, "Europe/London")

    def test_rejects_invalid_quantities_and_dates(self):
        for number in (float("nan"), float("inf"), -1, True, "2000", None):
            with self.assertRaises(ValueError):
                parse_nutrition(payload(number), "Europe/London")
        for day in ("2026-10-07T00:00:00+01:00", "bad", "2099-01-01", None):
            with self.assertRaises(ValueError):
                parse_nutrition(payload(day=day), "Europe/London")

    def test_explicit_zero_correction_is_preserved(self):
        ingest_nutrition(self.settings, payload())
        ingest_nutrition(self.settings, payload(0))
        ingest_nutrition(self.settings, payload(20, field="sodium_mg"))
        ingest_nutrition(self.settings, payload(0, field="sodium_mg"))
        export_data(self.settings)
        self.assertEqual(json.loads((self.settings.data_dir / "nutrition_details.json").read_text())[0]["sodium_mg"], 0)
        with database(self.settings) as conn:
            self.assertEqual(conn.execute("SELECT calories FROM nutrition").fetchone()[0], 0)

    def create_legacy_database(self):
        with closing(sqlite3.connect(self.settings.database)) as conn, conn:
            conn.executescript("""
                CREATE TABLE nutrition (day TEXT, metric TEXT, quantity REAL,
                    source TEXT, received_at TEXT, PRIMARY KEY(day, metric));
                CREATE VIEW daily_nutrition AS SELECT day AS date FROM nutrition;
                CREATE TABLE sync_state (name TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT INTO sync_state VALUES ('nutrition_received_at', '2026-10-08T10:00:00+00:00');
                CREATE TABLE workouts (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                INSERT INTO workouts VALUES ('existing', '{"id":"existing","exercises":[]}');
            """)
            conn.executemany("INSERT INTO nutrition VALUES (?, ?, ?, ?, ?)", [
                ("2026-10-06", "calories_kcal", 0, "nutracheck", "2026-10-08T10:00:00+00:00"),
                ("2026-10-07", "calories_kcal", 2100, "nutracheck", "2026-10-08T10:00:00+00:00"),
                ("2026-10-07", "protein_g", 140, "nutracheck", "2026-10-08T10:00:00+00:00"),
                ("2026-10-07", "sodium_mg", 50, "nutracheck", "2026-10-08T10:00:00+00:00"),
            ])

    def test_legacy_migration_preserves_totals_extras_metadata_and_workouts(self):
        self.create_legacy_database()
        for _ in range(2):
            export_data(self.settings)
            with database(self.settings) as conn:
                self.assertEqual([tuple(row) for row in conn.execute("SELECT * FROM nutrition ORDER BY date")], [
                    ("2026-10-06", 0, None, None, None), ("2026-10-07", 2100, 140, None, None)])
                self.assertEqual(conn.execute("SELECT id FROM workouts").fetchone()[0], "existing")
                self.assertEqual(conn.execute("SELECT value FROM sync_state").fetchone()[0], "2026-10-08T10:00:00+00:00")
                self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='daily_nutrition'").fetchone())
                details = json.loads(conn.execute("SELECT details FROM nutrition_metadata WHERE date='2026-10-07'").fetchone()[0])
                self.assertEqual(details["sources"]["protein_g"], "nutracheck")
                self.assertEqual(details["received_at"]["protein_g"], "2026-10-08T10:00:00+00:00")
            exported = json.loads((self.settings.data_dir / "nutrition_details.json").read_text())
            self.assertEqual(exported[1]["sodium_mg"], 50)
        ingest_nutrition(self.settings, payload(150, field="protein_g"))
        with database(self.settings) as conn:
            self.assertEqual(tuple(conn.execute("SELECT calories, protein FROM nutrition WHERE date='2026-10-07'").fetchone()), (2100, 150))

    def test_failed_migration_rolls_back_schema_and_original_rows(self):
        self.create_legacy_database()
        with patch("support.storage.store_nutrition_rows", side_effect=RuntimeError("Interrupted migration")):
            with self.assertRaisesRegex(RuntimeError, "Interrupted migration"):
                with database(self.settings):
                    pass
        with closing(sqlite3.connect(self.settings.database)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM nutrition").fetchone()[0], 4)
            self.assertEqual([row[1] for row in conn.execute("PRAGMA table_info(nutrition)")],
                             ["day", "metric", "quantity", "source", "received_at"])
            self.assertIsNotNone(conn.execute("SELECT name FROM sqlite_master WHERE name='daily_nutrition'").fetchone())

    def test_full_hevy_snapshot_handles_pagination_edits_and_deletions(self):
        first = [{"id": str(i), "exercises": []} for i in range(10)]
        pages = {1: {"page": 1, "page_count": 2, "workouts": first},
                 2: {"page": 2, "page_count": 2, "workouts": [{"id": "10", "exercises": []}]}}
        self.assertEqual(sync_hevy(self.settings, lambda key, page: pages[page]), 11)
        updated = {"id": "10", "title": "Updated", "exercises": [{"sets": [{"reps": 5, "weight_kg": 100}]}]}
        sync_hevy(self.settings, lambda key, page: {"page": 1, "page_count": 1, "workouts": [updated]})
        export_data(self.settings)
        self.assertEqual(json.loads((self.settings.hevy_directory / "hevy_workouts.json").read_text()), [updated])

    def test_hevy_failure_preserves_previous_snapshot(self):
        old = {"id": "old", "exercises": []}
        sync_hevy(self.settings, lambda key, page: {"page": 1, "page_count": 1, "workouts": [old]})
        def failing_fetch(key, page):
            if page == 2:
                raise RuntimeError("Network unavailable")
            return {"page": 1, "page_count": 2, "workouts": [{"id": str(i), "exercises": []} for i in range(10)]}
        with self.assertRaises(RuntimeError):
            sync_hevy(self.settings, failing_fetch)
        with hevy_database(self.settings) as conn:
            self.assertEqual(conn.execute("SELECT id FROM workouts").fetchone()[0], "old")

    def test_empty_account_and_changed_pagination(self):
        self.assertEqual(sync_hevy(self.settings, lambda key, page: {"page": 1, "page_count": 0, "workouts": []}), 0)
        def changing(key, page):
            return {"page": page, "page_count": 2 if page == 1 else 3,
                    "workouts": [{"id": str(i), "exercises": []} for i in range(10)]}
        with self.assertRaises(ValueError):
            sync_hevy(self.settings, changing)

    def test_duplicate_and_incomplete_hevy_pages_rejected(self):
        for rows in ([{"id": "a", "exercises": []}] * 10, [{"id": "a", "exercises": []}]):
            with self.assertRaises(ValueError):
                sync_hevy(self.settings, lambda key, page: {"page": page, "page_count": 2, "workouts": rows})

    def test_missing_nutrition_is_flagged_without_fabricating_zero(self):
        status = export_data(self.settings)
        self.assertTrue(status["nutrition_warnings"])
        self.assertEqual(json.loads((self.settings.data_dir / "daily_nutrition.json").read_text()), [])

    def test_recent_upload_with_yesterday_calories_is_healthy(self):
        yesterday = (datetime.now(ZoneInfo("Europe/London")).date() - timedelta(days=1)).isoformat()
        ingest_nutrition(self.settings, payload(day=yesterday))
        self.assertEqual(export_data(self.settings)["nutrition_warnings"], [])
        with database(self.settings) as conn:
            conn.execute("UPDATE sync_state SET value='2000-01-01T00:00:00+00:00' WHERE name='nutrition_received_at'")
        self.assertTrue(any("stale" in item for item in export_data(self.settings)["nutrition_warnings"]))

    @patch("hevy_extract.workouts.time.sleep")
    @patch("hevy_extract.workouts.urlopen")
    def test_retry_rate_limit_without_logging_key(self, opener, sleep):
        opener.side_effect = HTTPError("https://api.hevyapp.com", 429, "rate limit", {}, None)
        with self.assertRaisesRegex(RuntimeError, "HTTP 429"):
            request_hevy("secret-test-key", 1)
        self.assertEqual(opener.call_count, 4)
        self.assertEqual(sleep.call_count, 3)
        request = opener.call_args.args[0]
        self.assertEqual(request.get_header("Api-key"), "secret-test-key")
        self.assertIn("pageSize=10", request.full_url)


async def asgi_request(app, body, headers):
    replies = []
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    async def send(message):
        replies.append(message)
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": "POST", "scheme": "http", "path": "/apple-health", "raw_path": b"/apple-health",
             "query_string": b"", "root_path": "", "headers": headers,
             "client": ("127.0.0.1", 1234), "server": ("127.0.0.1", 8765)}
    await app(scope, receive, send)
    return next(message["status"] for message in replies if message["type"] == "http.response.start")


class ReceiverTests(TemporaryDatabase):
    def test_grouped_json_upload_returns_total_count(self):
        app = create_app(self.settings)
        body = json.dumps({"Calories": [{"date": "2026-10-07", "value": 2100}],
                           "Protein": [{"date": "2026-10-07", "value": 140}]}).encode()
        headers = [(b"authorization", b"Bearer " + b"a" * 40), (b"content-type", b"application/json")]
        self.assertEqual(asyncio.run(asgi_request(app, body, headers)), 200)
        self.assertEqual(json.loads((self.settings.data_dir / "daily_nutrition.json").read_text()), [
            {"date": "2026-10-07", "calories": 2100, "protein": 140, "carbs": None, "fat": None},
        ])
        self.assertTrue((self.settings.data_dir / "daily_nutrition.csv").exists())
        with database(self.settings) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM nutrition").fetchone()[0], 1)
            self.assertEqual(tuple(conn.execute("SELECT * FROM nutrition").fetchone()),
                             ("2026-10-07", 2100, 140, None, None))

    def test_upload_auth_validation_and_size(self):
        app = create_app(self.settings)
        headers = [(b"authorization", b"Bearer " + b"a" * 40), (b"content-type", b"application/json")]
        self.assertEqual(asyncio.run(asgi_request(app, json.dumps(payload()).encode(), headers)), 200)
        self.assertEqual(asyncio.run(asgi_request(app, b"{}", headers[1:])), 401)
        self.assertEqual(asyncio.run(asgi_request(app, b"{}", headers)), 422)
        self.assertEqual(asyncio.run(asgi_request(app, b"bad-json", headers)), 422)
        self.assertEqual(asyncio.run(asgi_request(app, b"x" * (1024 * 1024 + 1), headers)), 413)
        self.assertEqual(asyncio.run(asgi_request(app, b"{}", [headers[0], (b"content-type", b"text/plain")])), 415)

    def test_receiver_refuses_missing_token(self):
        with self.assertRaises(ValueError):
            create_app(Settings(self.settings.data_dir))


if __name__ == "__main__":
    unittest.main()
