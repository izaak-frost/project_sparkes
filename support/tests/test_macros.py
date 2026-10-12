from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from publish import export_macros as macros
from support.config import Settings


class MacrosTests(unittest.TestCase):
    def test_surplus_weeks_are_removed_and_calendar_ends_after_next_week(self):
        dates = self.dates(4)
        requests, values = macros.plan_extension(MagicMock(id=123, row_count=66), dates, {}, date(2026, 10, 8))
        self.assertEqual(len(dates), 14)
        self.assertEqual(max(dates), date(2026, 10, 19))
        self.assertEqual(requests[0]["deleteDimension"]["range"],
                         {"sheetId": 123, "dimension": "ROWS", "startIndex": 52, "endIndex": 66})
        self.assertEqual(values, [])

    def test_formats_labels_and_notes_template_cover_every_week(self):
        dates = {date(2025, 7, 29) + timedelta(days=i): 39+i for i in range(448)}
        requests, values = macros.plan_formatting(MagicMock(id=123, row_count=486), dates)
        formats = [request["repeatCell"] for request in requests if "repeatCell" in request]
        self.assertEqual([item["cell"]["userEnteredFormat"]["numberFormat"]["pattern"] for item in formats],
                         ["ddd, d mmm yyyy", "0.0", "#,##0"])
        self.assertTrue(all(item["range"]["endRowIndex"] == 486 for item in formats))
        copies = [request["copyPaste"] for request in requests if "copyPaste" in request]
        self.assertEqual(len(copies), 63)
        self.assertTrue(all(item["source"]["startRowIndex"] == 479 and item["source"]["endRowIndex"] == 486
                            and item["source"]["startColumnIndex"] == 13 and item["source"]["endColumnIndex"] == 20
                            and item["pasteType"] == "PASTE_FORMAT" for item in copies))
        calendar = {item["range"]: item["values"] for item in values}
        self.assertEqual(calendar["A480"], [["WEEK 64"]])
        self.assertEqual(len(calendar["B39:B486"]), 448)

    def dates(self, weeks=2):
        return {date(2026, 10, 6) + timedelta(days=index): 39 + index for index in range(weeks*7)}

    def test_updates_align_by_date_preserve_missing_and_omit_future(self):
        updates = macros.plan_values(self.dates(), {
            date(2026, 10, 6): {"weight": 99.1, "calories": 2100, "protein": 140, "carbs": 220, "fat": 60, "steps": 10000},
            date(2026, 10, 7): {"steps": 0},
            date(2026, 10, 9): {"weight": 90},
        }, date(2026, 10, 8))
        actual = {update["range"]: update["values"][0][0] for update in updates}
        self.assertEqual({cell: actual[cell] for cell in ("D39", "E39", "F39", "G39", "I39", "K39", "K40")},
                         {"D39": 99.1, "E39": 140, "F39": 220, "G39": 60, "I39": 2100, "K39": 10000, "K40": 0})
        self.assertNotIn("D40", actual)
        self.assertNotIn("D42", actual)
        self.assertEqual(actual["C39"], '=IFERROR(AVERAGE(D39:D45),"")')
        self.assertEqual(actual["J39"], '=IFERROR(AVERAGE(I39:I45),"")')
        self.assertFalse(any(cell.startswith(("M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y")) for cell in actual))

    def test_new_week_clones_formats_and_merges_without_notes_or_values(self):
        worksheet = MagicMock(id=123, row_count=52)
        dates = self.dates()
        metadata = {"merges": [{"sheetId": 123, "startRowIndex": 45, "endRowIndex": 52,
                                "startColumnIndex": 20, "endColumnIndex": 26}]}
        requests, updates = macros.plan_extension(worksheet, dates, metadata, date(2026, 10, 13))
        self.assertEqual(max(dates), date(2026, 10, 26))
        self.assertEqual(len(dates), 21)
        self.assertEqual(requests[0]["appendDimension"]["length"], 7)
        self.assertEqual([r["copyPaste"]["pasteType"] for r in requests if "copyPaste" in r], ["PASTE_FORMAT", "PASTE_CONDITIONAL_FORMATTING"])
        copied_merge = next(r["mergeCells"]["range"] for r in requests if "mergeCells" in r)
        self.assertEqual((copied_merge["startRowIndex"], copied_merge["endRowIndex"]), (52, 59))
        self.assertEqual((copied_merge["startColumnIndex"], copied_merge["endColumnIndex"]), (20, 26))
        self.assertTrue(all(r["copyPaste"]["source"]["endColumnIndex"] == 26
                            for r in requests if "copyPaste" in r))
        self.assertTrue(all(update["range"].startswith(("A", "B")) for update in updates))
        more, _ = macros.plan_extension(MagicMock(id=123, row_count=59), dates, metadata, date(2026, 10, 13))
        self.assertEqual(more, [])

    def test_sheet_date_checks_reject_duplicates_gaps_and_partial_weeks(self):
        good = [[day.isoformat()] for day in self.dates()]
        self.assertEqual(len(macros.read_dates(good)), 14)
        for rows in (good[:-1], good[:3] + good[4:], good[:3] + good[2:]):
            with self.assertRaises(ValueError):
                macros.read_dates(rows)

    def test_sources_keep_missing_distinct_from_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(root / "health")
            settings.data_dir.mkdir()
            (root / "weights.json").write_text('[{"date":"2026-10-07","weight":99.1}]')
            (root / "daily_steps.json").write_text('[{"date":"2026-10-07","steps":null}]')
            (settings.data_dir / "daily_nutrition.json").write_text('[{"date":"2026-10-07","calories":0,"protein":null}]')
            with patch.object(macros, "GARMIN_DATA_DIR", root):
                totals = macros.load_totals(settings)
            self.assertEqual(totals, {date(2026, 10, 7): {"weight": 99.1, "calories": None}})

    def test_zero_measurements_become_blank_while_zero_steps_remain(self):
        updates = macros.plan_values(self.dates(), {
            date(2026, 10, 6): {"weight": None, "protein": None, "carbs": None, "fat": None, "calories": None, "steps": 0}
        }, date(2026, 10, 8), existing_values=[[0, 0, 0, 0, "", 0, "", 0], [0, 140, "", "", "", 0]])
        cells = {update["range"]: update["values"][0][0] for update in updates}
        self.assertTrue(all(cells[cell] == "" for cell in ("D39", "E39", "F39", "G39", "I39", "D40", "I40")))
        self.assertEqual(cells["K39"], 0)
        self.assertNotIn("E40", cells)
