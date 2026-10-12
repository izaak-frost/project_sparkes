from datetime import date, timedelta
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import main
from support.config import Settings
from garmin_extract import get_sleep_data as sleep
from garmin_extract import authentication as auth
from publish import export_sleep as sheet


def sleep_payload(day, seconds=28800):
    return {"dailySleepDTO": {"calendarDate": day, "sleepTimeSeconds": seconds}}


class DailyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def week_rows(self, count):
        return [{"calendarDate": (date(2026, 10, 5) + timedelta(days=index)).isoformat(),
                 "sleepStartTime": "23:00", "sleepEndTime": "07:00", "overallSleepScore": 80}
                for index in range(count)]

    def test_weekly_averages_use_daily_cell_formulas_and_expand_with_week(self):
        with patch.object(sheet, "WEEK_1_START", date(2026, 10, 5)):
            partial = sheet.build_enriched_rows(self.week_rows(9))
            blocks = sheet.build_week_blocks(partial)
            matrix, _ = sheet.build_sheet_matrices(partial, blocks)
            self.assertEqual(matrix[0][1:3], ['=IFERROR(SUM(F3:F9)/COUNT(F3:F9),"")',
                                            '=IFERROR(SUM(J3:J9)/COUNT(J3:J9),"")'])
            self.assertEqual(matrix[7][1], '=IFERROR(SUM(F10:F11)/COUNT(F10:F11),"")')
            complete = sheet.build_enriched_rows(self.week_rows(14))
            matrix, _ = sheet.build_sheet_matrices(complete, sheet.build_week_blocks(complete))
            self.assertEqual(matrix[7][1:3], ['=IFERROR(SUM(F10:F16)/COUNT(F10:F16),"")',
                                            '=IFERROR(SUM(J10:J16)/COUNT(J10:J16),"")'])
            self.assertEqual(matrix[8][1:3], ["", ""])

    def test_week_borders_remove_old_partial_week_and_daily_separators(self):
        worksheet, spreadsheet = MagicMock(), MagicMock()
        worksheet.row_count = 100
        borders = {4, 11, 50}  # Historical daily/partial-week separators.
        with patch.object(sheet, "WEEK_1_START", date(2026, 10, 5)):
            rows = sheet.build_enriched_rows(self.week_rows(14))
            sheet.apply_week_borders(spreadsheet, worksheet, sheet.build_week_blocks(rows))
        requests = spreadsheet.batch_update.call_args.args[0]["requests"]
        for request in requests:
            border = request["updateBorders"]
            start, end = border["range"]["startRowIndex"], border["range"]["endRowIndex"]
            for edge, positions in (("top", [start]), ("bottom", [end]),
                                    ("innerHorizontal", range(start + 1, end))):
                if edge in border:
                    if border[edge]["style"] == "NONE":
                        borders.difference_update(positions)
                    else:
                        borders.update(positions)
        self.assertEqual(borders, {2, 9, 16})
        self.assertTrue(all("left" not in request["updateBorders"] and "right" not in request["updateBorders"]
                            for request in requests[1:]))

    def test_sheet_check_reports_inherited_override_without_writing(self):
        (self.root / ".env").write_text("GOOGLE_SHEET_ID=correct-id\nGOOGLE_SERVICE_ACCOUNT_FILE=credentials.json\n")
        credentials = self.root / "credentials.json"
        credentials.write_text('{"client_email":"test@example.com","private_key":"must-not-print"}')
        client = MagicMock()
        spreadsheet = MagicMock()
        client.open_by_key.return_value = spreadsheet
        output = io.StringIO()
        with patch.object(sheet, "BASE_DIR", self.root), patch.object(sheet, "configured_path", return_value=credentials), patch.object(sheet, "get_gspread_client", return_value=client), patch.dict(os.environ, {"GOOGLE_SHEET_ID": "stale-id", "GOOGLE_SERVICE_ACCOUNT_FILE": "credentials.json"}), redirect_stdout(output):
            sheet.check_spreadsheet_access()
        self.assertIn("GOOGLE_SHEET_ID in this terminal overrides", output.getvalue())
        self.assertIn("stale-id", output.getvalue())
        self.assertNotIn("must-not-print", output.getvalue())
        client.open_by_key.assert_called_once_with("stale-id")
        spreadsheet.worksheet.assert_called_once_with("SLEEP DATA")
        spreadsheet.batch_update.assert_not_called()

    def test_sleep_refreshes_recent_record_without_duplicate(self):
        target = self.root / "sleep_data.json"
        target.write_text(json.dumps([{"calendarDate": "2026-10-07", "sleepTime": "06:00"}]))
        client = MagicMock()
        client.get_sleep_data.side_effect = lambda day: sleep_payload(day, 28800)
        with patch.object(sleep, "OUTPUT_FILE", target), patch.object(sleep, "today", return_value=date(2026, 10, 8)), patch.dict(os.environ, {"START_DATE": "2026-10-07", "SLEEP_REFRESH_DAYS": "3"}):
            result = sleep.get_sleep_data(client)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["sleepTime"], "08:00")

    def test_sleep_failure_surfaces_and_keeps_old_day(self):
        target = self.root / "sleep_data.json"
        target.write_text(json.dumps([{"calendarDate": "2026-10-07", "sleepTime": "06:00"}]))
        client = MagicMock()
        client.get_sleep_data.side_effect = RuntimeError("Network failure")
        with patch.object(sleep, "OUTPUT_FILE", target), patch.object(sleep, "today", return_value=date(2026, 10, 8)), patch.dict(os.environ, {"START_DATE": "2026-10-07"}):
            with self.assertRaises(RuntimeError):
                sleep.get_sleep_data(client)
        self.assertEqual(json.loads(target.read_text())[0]["sleepTime"], "06:00")

    def test_bad_sleep_history_is_not_overwritten(self):
        target = self.root / "sleep_data.json"
        target.write_text("invalid json")
        with self.assertRaises(ValueError):
            sleep.load_existing_sleep_data(target)
        self.assertEqual(target.read_text(), "invalid json")

    def test_cached_auth_persists_refreshed_tokens(self):
        client = MagicMock()
        with patch.object(auth, "Garmin", return_value=client), patch.dict(os.environ, {"GARMIN_TOKENS": str(self.root / "tokens")}):
            self.assertIs(auth.authenticate(), client)
        client.client.dump.assert_called_once_with(str(self.root / "tokens"))

    def test_unattended_auth_never_prompts_for_credentials(self):
        client = MagicMock()
        client.login.side_effect = auth.GarminConnectAuthenticationError("Missing tokens")
        with patch.object(auth, "Garmin", return_value=client), patch.dict(os.environ, {"GARMIN_TOKENS": str(self.root / "tokens"), "GARMIN_EMAIL": "", "GARMIN_PASSWORD": ""}), patch("builtins.input") as prompt:
            with self.assertRaisesRegex(RuntimeError, "--garmin-login"):
                auth.authenticate(interactive=False)
        prompt.assert_not_called()

    def test_credential_rate_limit_reports_the_block_without_dumping_tokens(self):
        cached, credential = MagicMock(), MagicMock()
        cached.login.side_effect = auth.GarminConnectAuthenticationError("Missing tokens")
        credential.login.side_effect = auth.GarminConnectTooManyRequestsError("429")
        with patch.object(auth, "Garmin", side_effect=[cached, credential]), patch.dict(os.environ, {"GARMIN_TOKENS": str(self.root / "tokens"), "GARMIN_EMAIL": "test@example.com", "GARMIN_PASSWORD": "test-password"}):
            with self.assertRaisesRegex(RuntimeError, "HTTP 429"):
                auth.authenticate(interactive=True)
        credential.login.assert_called_once()
        credential.client.dump.assert_not_called()

    def test_credential_connection_block_does_not_claim_mfa_required(self):
        cached, credential = MagicMock(), MagicMock()
        cached.login.side_effect = auth.GarminConnectAuthenticationError("Missing tokens")
        credential.login.side_effect = auth.GarminConnectConnectionError("HTTP 403")
        with patch.object(auth, "Garmin", side_effect=[cached, credential]), patch.dict(os.environ, {"GARMIN_TOKENS": str(self.root / "tokens"), "GARMIN_EMAIL": "test@example.com", "GARMIN_PASSWORD": "test-password"}):
            with self.assertRaisesRegex(RuntimeError, "access protection"):
                auth.authenticate(interactive=True)
        credential.client.dump.assert_not_called()

    def test_garmin_failure_does_not_skip_hevy(self):
        settings = Settings(self.root / "health", "test-key")
        with patch.object(main, "DATA_DIR", self.root), patch.object(main, "load_settings", return_value=settings), patch.object(auth, "authenticate", side_effect=RuntimeError("Garmin unavailable")), patch.dict(os.environ, {"START_DATE": "2026-10-01"}), patch.object(main, "sync_hevy", return_value=2) as hevy, patch.object(main, "export_data", return_value={"nutrition_warnings": []}), patch("publish.export_macros.export_macros_to_gsheet") as macros:
            with patch("publish.export_checkins.export_checkins_to_gsheet") as checkins:
                self.assertEqual(main.run_daily(), 1)
                checkins.assert_called_once()
        hevy.assert_called_once()
        macros.assert_called_once()
        status = json.loads((self.root / "daily_status.json").read_text())
        self.assertFalse(status["stages"]["garmin_login"]["ok"])
        self.assertTrue(status["stages"]["hevy"]["ok"])

    def test_sheet_notes_remain_with_date_after_backfill(self):
        worksheet = MagicMock()
        worksheet.row_count = 100
        worksheet.get.return_value = [["07-10-2026", "", "", "", "", "", "", "Keep this note"]]
        spreadsheet = MagicMock()
        spreadsheet.title = "Test"
        rows = [{"calendarDate": "2026-10-06", "sleepTime": "08:00"}, {"calendarDate": "2026-10-07", "sleepTime": "07:00"}]
        with patch.object(sheet, "DATA_DIR", self.root), patch.object(sheet, "WEEK_1_START", date(2026, 10, 5)), patch.object(sheet, "load_sleep_data", return_value=rows), patch.object(sheet, "get_gspread_client"), patch.object(sheet, "get_spreadsheet", return_value=spreadsheet), patch.object(sheet, "get_or_create_worksheet", return_value=worksheet):
            sheet.export_sleep_to_gsheet()
        note_update = next(call for call in worksheet.update.call_args_list if call.kwargs["range_name"].startswith("K"))
        self.assertEqual(note_update.kwargs["values"], [[""], ["Keep this note"]])
        self.assertFalse((self.root / "sleep_sheet_notes.pending.json").exists())
        self.assertEqual(json.loads((self.root / "sleep_sheet_notes.json").read_text())["2026-10-07"], "Keep this note")
        worksheet.delete_rows.assert_not_called()

    def test_sheet_retry_uses_saved_notes_after_partial_failure(self):
        snapshot = {"2026-10-07": "Original note"}
        (self.root / "sleep_sheet_notes.pending.json").write_text(json.dumps(snapshot))
        worksheet = MagicMock()
        worksheet.row_count = 100
        with patch.object(sheet, "DATA_DIR", self.root), patch.object(sheet, "WEEK_1_START", date(2026, 10, 5)), patch.object(sheet, "load_sleep_data", return_value=[{"calendarDate": "2026-10-07"}]), patch.object(sheet, "get_gspread_client"), patch.object(sheet, "get_spreadsheet"), patch.object(sheet, "get_or_create_worksheet", return_value=worksheet):
            sheet.export_sleep_to_gsheet()
        worksheet.get.assert_not_called()
        note_update = next(call for call in worksheet.update.call_args_list if call.kwargs["range_name"].startswith("K"))
        self.assertEqual(note_update.kwargs["values"], [["Original note"]])


if __name__ == "__main__":
    unittest.main()
