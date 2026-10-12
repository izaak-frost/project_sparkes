"""Update the existing MACROS & WEIGHT diary by date, preserving manual notes."""
import argparse
from datetime import date, datetime, timedelta
import json
import math

from publish.export_sleep import get_gspread_client, get_spreadsheet
from publish.macros_charts import plan_charts
from support.config import load_settings
from support.runtime import GARMIN_DATA_DIR, PUBLISH_DATA_DIR, today
from support.storage import atomic_json

WORKSHEET_NAME = "MACROS & WEIGHT"
START_ROW = 39
# Column M is manual comments; the existing notes blocks now occupy N:Z.
DIARY_END_COLUMN = 26  # Exclusive, zero-based boundary after Z.
NOTES_START_COLUMN = 13  # N
NOTES_END_COLUMN = 20  # Exclusive boundary after T.
COLUMNS = {"weight": "D", "protein": "E", "carbs": "F", "fat": "G",
           "calories": "I", "steps": "K"}


def parse_sheet_date(value):
    if isinstance(value, (int, float)):
        return date(1899, 12, 30) + timedelta(days=int(value))
    for pattern in ("%a, %d %b %Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(value).strip(), pattern).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognised diary date: {value!r}; no cells changed")


def read_dates(rows):
    dates = {}
    for row_number, row in enumerate(rows, START_ROW):
        if not row or row[0] in (None, ""):
            continue
        day = parse_sheet_date(row[0])
        if day in dates:
            raise ValueError("Duplicate dates in the macros diary; no cells changed")
        dates[day] = row_number
    ordered = sorted(dates.items(), key=lambda item: item[1])
    if not ordered or ordered[0][1] != START_ROW:
        raise ValueError("Expected diary dates to begin at B39; no cells changed")
    for index, (day, row) in enumerate(ordered):
        if row != START_ROW + index or day != ordered[0][0] + timedelta(days=index):
            raise ValueError("Diary dates must be consecutive with no gaps; no cells changed")
    if len(ordered) % 7:
        raise ValueError("Expected complete seven-day diary blocks; no cells changed")
    return dates


def load_totals(settings):
    totals = {}
    files = [(GARMIN_DATA_DIR / "weights.json", ("weight",)),
             (GARMIN_DATA_DIR / "daily_steps.json", ("steps",)),
             (settings.data_dir / "daily_nutrition.json", ("calories", "protein", "carbs", "fat"))]
    for path, fields in files:
        if not path.exists():
            raise FileNotFoundError(f"Missing source data: {path}; run the extracts first")
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise ValueError(f"Expected daily records in {path}")
        seen = set()
        for record in rows:
            day = date.fromisoformat(record["date"])
            if day in seen:
                raise ValueError(f"Duplicate daily records in {path}")
            seen.add(day)
            for field in fields:
                value = record.get(field)
                if value is None:
                    continue
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise ValueError(f"Invalid {field} quantity in {path}")
                totals.setdefault(day, {})[field] = None if field != "steps" and value == 0 else value
    return totals


def plan_values(dates, totals, as_of, existing_values=None):
    updates = []
    # Remove existing zero measurements too, including manual/historical zeros.
    # Do not touch the zero-step readings or any other manual values.
    zero_cells = set()
    for index, existing in enumerate(existing_values or []):
        for offset, column in ((0, "D"), (1, "E"), (2, "F"), (3, "G"), (5, "I")):
            if offset < len(existing) and type(existing[offset]) in (int, float) and existing[offset] == 0:
                zero_cells.add(f"{column}{START_ROW + index}")
    for day, row in sorted(dates.items()):
        # Future dates remain available for planning; imported totals stop today.
        if day > as_of:
            continue
        for field, value in totals.get(day, {}).items():
            cell = f"{COLUMNS[field]}{row}"
            zero_cells.discard(cell)
            updates.append({"range": cell, "values": [["" if value is None else value]]})
    updates.extend({"range": cell, "values": [[""]]} for cell in sorted(zero_cells))
    for index in range(0, len(dates), 7):
        start, end = START_ROW + index, START_ROW + index + 6
        for target, source in (("C", "D"), ("J", "I"), ("L", "K")):
            updates.append({"range": f"{target}{start}",
                            "values": [[f'=IFERROR(AVERAGE({source}{start}:{source}{end}),"")']]})
    return updates


def plan_extension(worksheet, dates, metadata, as_of):
    first = min(dates)
    if as_of < first:
        raise ValueError("Current date precedes the diary start")
    current_week = (as_of - first).days // 7
    required_days = (current_week + 2) * 7
    requests, values = [], []
    existing = len(dates)
    required_rows = START_ROW - 1 + required_days
    if existing > required_days:
        requests.append({"deleteDimension": {"range": {
            "sheetId": worksheet.id, "dimension": "ROWS",
            "startIndex": required_rows, "endIndex": START_ROW - 1 + existing}}})
        for day in list(dates):
            if dates[day] > required_rows:
                del dates[day]
    if required_rows > worksheet.row_count:
        requests.append({"appendDimension": {"sheetId": worksheet.id, "dimension": "ROWS",
                                             "length": required_rows - worksheet.row_count}})
    # Copy the last complete block's appearance, never its values or diary text.
    template_start = START_ROW - 1 + existing - 7
    template_end = template_start + 7
    source = {"sheetId": worksheet.id, "startRowIndex": template_start,
              "endRowIndex": template_end, "startColumnIndex": 0, "endColumnIndex": DIARY_END_COLUMN}
    merges = [merge for merge in metadata.get("merges", [])
              if merge.get("startRowIndex", 0) >= template_start
              and merge.get("endRowIndex", 0) <= template_end
              and merge.get("endColumnIndex", 0) <= DIARY_END_COLUMN]
    for index in range(existing, required_days, 7):
        start = START_ROW - 1 + index
        destination = {**source, "startRowIndex": start, "endRowIndex": start + 7}
        for paste in ("PASTE_FORMAT", "PASTE_CONDITIONAL_FORMATTING"):
            requests.append({"copyPaste": {"source": source, "destination": destination,
                                            "pasteType": paste, "pasteOrientation": "NORMAL"}})
        for merge in merges:
            new_merge = {**merge, "startRowIndex": merge["startRowIndex"] + start - template_start,
                         "endRowIndex": merge["endRowIndex"] + start - template_start}
            requests.append({"mergeCells": {"range": new_merge, "mergeType": "MERGE_ALL"}})
        values.append({"range": f"A{start+1}", "values": [[f"WEEK {index // 7 + 1}"]]})
        for offset in range(7):
            day = first + timedelta(days=index + offset)
            row = start + offset + 1
            dates[day] = row
            values.append({"range": f"B{row}", "values": [[(day - date(1899, 12, 30)).days]]})
        requests.append({"repeatCell": {"range": {**destination, "startColumnIndex": 1, "endColumnIndex": 2},
                         "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "ddd, d mmm yyyy"}}},
                         "fields": "userEnteredFormat.numberFormat"}})
    return requests, values


def plan_formatting(worksheet, dates):
    """Refresh the diary and use the user's week-64 notes formatting."""
    end = START_ROW - 1 + len(dates)
    base = {"sheetId": worksheet.id, "startRowIndex": START_ROW - 1, "endRowIndex": end}
    requests, values = [], []
    for left, right, kind, pattern in ((1, 2, "DATE", "ddd, d mmm yyyy"),
                                       (2, 7, "NUMBER", "0.0"),
                                       (8, 12, "NUMBER", "#,##0")):
        requests.append({"repeatCell": {"range": {**base, "startColumnIndex": left, "endColumnIndex": right},
                         "cell": {"userEnteredFormat": {"numberFormat": {"type": kind, "pattern": pattern}}},
                         "fields": "userEnteredFormat.numberFormat"}})
    # N480:T486 is the supplied template. A smaller diary uses its last full week.
    template_start = 479 if end >= 486 and worksheet.row_count >= 486 else end - 7
    source = {"sheetId": worksheet.id, "startRowIndex": template_start,
              "endRowIndex": template_start + 7, "startColumnIndex": NOTES_START_COLUMN,
              "endColumnIndex": NOTES_END_COLUMN}
    for index in range(0, len(dates), 7):
        start = START_ROW - 1 + index
        values.append({"range": f"A{start + 1}", "values": [[f"WEEK {index // 7 + 1}"]]})
        if start != template_start:
            requests.append({"copyPaste": {"source": source,
                "destination": {**source, "startRowIndex": start, "endRowIndex": start + 7},
                "pasteType": "PASTE_FORMAT", "pasteOrientation": "NORMAL"}})
    ordered = sorted(dates.items(), key=lambda item: item[1])
    values.append({"range": f"B{START_ROW}:B{end}",
                   "values": [[(day - date(1899, 12, 30)).days] for day, _ in ordered]})
    # Adjacent format copies can replace a shared edge. Draw week boundaries last.
    for start in range(START_ROW - 1, end, 7):
        requests.append({"updateBorders": {"range": {**source,
            "startRowIndex": start, "endRowIndex": start + 7},
            "bottom": {"style": "SOLID", "color": {"red": 0, "green": 0, "blue": 0}}}})
    return requests, values


def export_macros_to_gsheet(dry_run=False):
    settings = load_settings()
    totals = load_totals(settings)
    spreadsheet = get_spreadsheet(get_gspread_client())
    matches = [sheet for sheet in spreadsheet.worksheets() if sheet.title.strip() == WORKSHEET_NAME]
    if len(matches) != 1:
        raise ValueError("Expected exactly one MACROS & WEIGHT tab")
    worksheet = matches[0]
    # Verify the template before any mutation; preserve the dashboard and manual columns.
    header = worksheet.get("B37:L37")[0]
    expected = {0: "DATE", 1: "7 DAY AVERAGE", 2: "WEIGH IN", 3: "PROTEIN", 4: "CARBS",
                5: "FATS", 7: "CALORIES", 8: "7 DAY CALORIE", 9: "STEPS", 10: "7 DAY STEP"}
    if any(index >= len(header) or header[index].strip().upper() != label for index, label in expected.items()):
        raise ValueError("Macros diary column headers differ from the expected template; no cells changed")
    dates = read_dates(worksheet.get("B39:B", value_render_option="UNFORMATTED_VALUE"))
    before = len(dates)
    metadata = spreadsheet.fetch_sheet_metadata()
    meta = next(sheet for sheet in metadata["sheets"]
                if sheet["properties"]["sheetId"] == worksheet.id)
    structure, new_dates = plan_extension(worksheet, dates, meta, today())
    existing_values = worksheet.get(f"D{START_ROW}:K{worksheet.row_count}", value_render_option="UNFORMATTED_VALUE")
    existing_values = existing_values[:len(dates)]
    formatting, calendar = plan_formatting(worksheet, dates)
    structure.extend(formatting)
    updates = new_dates + calendar + plan_values(dates, totals, today(), existing_values)
    chart_requests = plan_charts(metadata, meta, min(dates), START_ROW - 1 + len(dates), today())
    # The following week is a blank input block; averages stay as live formulas.
    blank_start = START_ROW + len(dates) - 7
    for column in COLUMNS.values():
        updates.append({"range": f"{column}{blank_start}:{column}{blank_start + 6}",
                        "values": [[""] for _ in range(7)]})
    added, removed = max(0, (len(dates)-before)//7), max(0, (before-len(dates))//7)
    print(f"Macros diary: {len(updates)} cell updates; {added} added weeks; {removed} surplus weeks removed.")
    if dry_run:
        print("Dry run: no spreadsheet contents changed.")
        return
    # Keep a private pre-update snapshot for recovery. The publish scope never rewrites notes.
    all_values = worksheet.get(f"A1:AR{worksheet.row_count}", value_render_option="FORMULA")
    if before > len(dates) and any(any(value not in (None, "") for value in row[DIARY_END_COLUMN:])
                                  for row in all_values[START_ROW - 1 + len(dates):START_ROW - 1 + before]):
        raise ValueError("Extra week rows contain content outside the diary; no cells changed")
    snapshot = {"spreadsheet_id": spreadsheet.id, "worksheet_id": worksheet.id,
                "captured_at": datetime.now().isoformat(),
                "values": all_values,
                "charts": meta.get("charts", []),
                "merges": meta.get("merges", [])}
    atomic_json(PUBLISH_DATA_DIR / "macros_before_publish.json", snapshot)
    if before > len(dates):
        atomic_json(PUBLISH_DATA_DIR / f"macros_trimmed_weeks_{datetime.now():%Y%m%d_%H%M%S}.json", snapshot)
    if structure:
        spreadsheet.batch_update({"requests": structure})
    if updates:
        worksheet.batch_update(updates, value_input_option="USER_ENTERED")
    # Never rewrite chart specifications through REST: Google drops the user's
    # right-axis bounds even when cloning the complete saved specification.
    # Native chart date settings are handled by refresh_chart_dates.gs.
    spreadsheet.batch_update({"requests": [r for r in chart_requests if "updateChartSpec" not in r]})
    print("Chart source data refreshed; native chart dates require the installed Apps Script refresh.")
    print("Published weight, macros and steps; next week's blank block is available.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Check targeting and planned updates without changing the sheet")
    export_macros_to_gsheet(parser.parse_args().dry_run)
