import argparse
from pathlib import Path
import json
import os
from datetime import datetime, date, timedelta

import gspread
from gspread.exceptions import APIError
from dotenv import dotenv_values, load_dotenv
from support.runtime import BASE_DIR, GARMIN_DATA_DIR, PUBLISH_DATA_DIR as DATA_DIR, configured_path
from support.storage import atomic_json

load_dotenv(BASE_DIR / ".env", override=False)

INPUT_FILE = GARMIN_DATA_DIR / "sleep_data.json"
WORKSHEET_NAME = "SLEEP DATA"
DATA_START_ROW = 3

# A = WEEK
# B = AVG HOURS
# C = AVG QUALITY
# D = DATE
# E = WATCH SLEEP
# F = TIME SLEEP
# G = SLEEP NEED
# H = BED TIME
# I = WAKE UP
# J = QUALITY
# K = NOTES/DIARY (manual, preserve by date for every week)
# L = AVERAGE HR
# M = AVERAGE SLEEP STRESS
# N = DEEP SLEEP
# O = LIGHT SLEEP
# P = REM SLEEP

COACHING_START_DATE = os.getenv("COACHING_START_DATE")
WEEK_1_START = date.fromisoformat(COACHING_START_DATE) if COACHING_START_DATE else None


def load_sleep_data(file_path: Path) -> list[dict]:
    if not file_path.exists():
        raise FileNotFoundError(f"Sleep data file not found: {file_path}")

    with file_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError(f"Expected a list in {file_path}, got {type(data).__name__}")

    return data


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def hhmm_to_minutes(value: str | None) -> int | None:
    if not value:
        return None
    try:
        hours, minutes = value.split(":")
        return int(hours) * 60 + int(minutes)
    except (ValueError, AttributeError):
        return None


def minutes_to_hhmm(minutes: float | int | None) -> str:
    if minutes is None:
        return ""
    total = int(round(minutes))
    hours = total // 60
    mins = total % 60
    return f"{hours:02d}:{mins:02d}"


def week_number_for_date(d: date) -> int | None:
    if d < WEEK_1_START:
        return None
    return ((d - WEEK_1_START).days // 7) + 1


def week_label_for_date(d: date) -> str:
    week_num = week_number_for_date(d)
    return f"WEEK {week_num}" if week_num else ""


def get_pre_coaching_row_count(enriched_rows: list[dict]) -> int:
    """
    Return how many rows fall before the coaching start date.
    These rows should be hidden in the sheet.
    """
    count = 0
    for row in enriched_rows:
        if row["date"] < WEEK_1_START:
            count += 1
        else:
            break
    return count


def unhide_sleep_rows(spreadsheet, worksheet, start_row: int, end_row: int) -> None:
    """
    Unhide a row range in the worksheet.
    """
    if end_row < start_row:
        return

    spreadsheet.batch_update(
        {
            "requests": [
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": worksheet.id,
                            "dimension": "ROWS",
                            "startIndex": start_row - 1,
                            "endIndex": end_row,
                        },
                        "properties": {
                            "hiddenByUser": False
                        },
                        "fields": "hiddenByUser",
                    }
                }
            ]
        }
    )


def hide_pre_coaching_rows(spreadsheet, worksheet, pre_coaching_row_count: int) -> None:
    """
    Hide rows before the coaching start date.
    """
    if pre_coaching_row_count <= 0:
        return

    start_row = DATA_START_ROW
    end_row = DATA_START_ROW + pre_coaching_row_count - 1

    spreadsheet.batch_update(
        {
            "requests": [
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": worksheet.id,
                            "dimension": "ROWS",
                            "startIndex": start_row - 1,
                            "endIndex": end_row,
                        },
                        "properties": {
                            "hiddenByUser": True
                        },
                        "fields": "hiddenByUser",
                    }
                }
            ]
        }
    )


def get_gspread_client() -> gspread.Client:
    service_account_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
    if not service_account_file:
        raise ValueError("Missing GOOGLE_SERVICE_ACCOUNT_FILE in environment variables.")
    return gspread.service_account(filename=str(configured_path("GOOGLE_SERVICE_ACCOUNT_FILE", BASE_DIR / "support" / "credentials" / "google-service-account.json")))


def get_spreadsheet(client: gspread.Client):
    spreadsheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip()
    spreadsheet_name = os.getenv("GOOGLE_SHEET_NAME", "").strip()

    try:
        if spreadsheet_id:
            spreadsheet = client.open_by_key(spreadsheet_id)
            print(f"\n    Opened spreadsheet by ID: {spreadsheet.title}")
        elif spreadsheet_name:
            spreadsheet = client.open(spreadsheet_name)
            print(f"\n    Opened spreadsheet by name: {spreadsheet_name}")
        else:
            raise ValueError("Set either GOOGLE_SHEET_ID or GOOGLE_SHEET_NAME in the environment.")
        return spreadsheet

    except gspread.SpreadsheetNotFound as exc:
        target = f"ID {spreadsheet_id!r}" if spreadsheet_id else f"name {spreadsheet_name!r}"
        raise RuntimeError(
            f"Spreadsheet not found using {target}. Run python -m publish.export_sleep --check "
            "to inspect the active configuration and service account."
        ) from exc

    except APIError:
        print("Google API error while opening spreadsheet.")
        print("Check that Google Sheets API and Google Drive API are enabled,")
        print("and that the spreadsheet is shared with your service account.")
        raise


def check_spreadsheet_access():
    """Show non-secret targeting settings and verify access without writing cells."""
    saved = dotenv_values(BASE_DIR / ".env")
    for name in ("GOOGLE_SHEET_ID", "GOOGLE_SHEET_NAME", "GOOGLE_SERVICE_ACCOUNT_FILE"):
        if name in saved and os.environ.get(name, "").strip() != (saved[name] or "").strip():
            print(f"WARNING: {name} in this terminal overrides a different value in .env.", flush=True)
    path = configured_path("GOOGLE_SERVICE_ACCOUNT_FILE", BASE_DIR / "support" / "credentials" / "google-service-account.json")
    credentials = json.loads(path.read_text(encoding="utf-8-sig"))
    print(f"Service account: {credentials.get('client_email', 'missing')}", flush=True)
    print(f"Active spreadsheet ID: {os.environ.get('GOOGLE_SHEET_ID', '').strip() or '(not set)'}", flush=True)
    print(f"Active spreadsheet name: {os.environ.get('GOOGLE_SHEET_NAME', '').strip() or '(not set)'}", flush=True)
    spreadsheet = get_spreadsheet(get_gspread_client())
    spreadsheet.worksheet(WORKSHEET_NAME)
    print("Spreadsheet and SLEEP DATA tab are accessible. No spreadsheet contents changed.")


def get_or_create_worksheet(spreadsheet, worksheet_name: str, rows: int = 3000, cols: int = 20):
    try:
        worksheet = spreadsheet.worksheet(worksheet_name)
        print(f"    Opened existing worksheet: {worksheet_name}")
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=worksheet_name,
            rows=rows,
            cols=cols,
        )
        print(f"    Created worksheet: {worksheet_name}")
    return worksheet


def clear_auto_managed_ranges(worksheet) -> None:
    """
    Clear all non-manual columns from the sleep table.
    Column K is intentionally preserved here.
    """
    worksheet.batch_clear([
        f"A{DATA_START_ROW}:J",
        f"L{DATA_START_ROW}:P",
    ])


def build_enriched_rows(data: list[dict]) -> list[dict]:
    sorted_data = sorted(data, key=lambda x: x.get("calendarDate", ""))

    enriched_rows = []
    for item in sorted_data:
        calendar_date = item.get("calendarDate")
        if not calendar_date:
            continue

        d = parse_date(calendar_date)

        sleep_start = hhmm_to_minutes(item.get("sleepStartTime"))
        sleep_end = hhmm_to_minutes(item.get("sleepEndTime"))

        if sleep_start is None or sleep_end is None:
            time_sleep_minutes = None
        else:
            if sleep_end >= sleep_start:
                time_sleep_minutes = sleep_end - sleep_start
            else:
                time_sleep_minutes = (24 * 60 - sleep_start) + sleep_end

        enriched_rows.append(
            {
                "date": d,
                "week_num": week_number_for_date(d),
                "week_label": week_label_for_date(d),
                "time_sleep_minutes": time_sleep_minutes,
                "quality": item.get("overallSleepScore"),
                "raw": item,
            }
        )

    return enriched_rows


def build_week_blocks(enriched_rows: list[dict]) -> list[dict]:
    """
    Returns week blocks based on 7-day windows from WEEK_1_START.
    Each block contains:
      - start_idx / end_idx in enriched_rows
      - start_row / end_row in sheet
      - label
      - avg_sleep / avg_quality: formulas evaluated by Google Sheets
    """
    if not enriched_rows:
        return []

    blocks: list[dict] = []
    start_idx = 0
    total_rows = len(enriched_rows)

    while start_idx < total_rows:
        current_week_num = enriched_rows[start_idx]["week_num"]
        end_idx = start_idx

        while (
            end_idx + 1 < total_rows
            and enriched_rows[end_idx + 1]["week_num"] == current_week_num
        ):
            end_idx += 1

        week_rows = enriched_rows[start_idx:end_idx + 1]
        start_row = DATA_START_ROW + start_idx
        end_row = DATA_START_ROW + end_idx

        # Average only numeric daily values; incomplete weeks and missing days
        # must not count as zero. References expand when later days are imported.
        avg_sleep = f'=IFERROR(SUM(F{start_row}:F{end_row})/COUNT(F{start_row}:F{end_row}),"")'
        avg_quality = f'=IFERROR(SUM(J{start_row}:J{end_row})/COUNT(J{start_row}:J{end_row}),"")'

        blocks.append(
            {
                "week_num": current_week_num,
                "label": week_rows[0]["week_label"],
                "start_idx": start_idx,
                "end_idx": end_idx,
                "start_row": start_row,
                "end_row": end_row,
                "avg_sleep": avg_sleep,
                "avg_quality": avg_quality,
            }
        )

        start_idx = end_idx + 1

    return blocks


def build_sheet_matrices(enriched_rows: list[dict], week_blocks: list[dict]):
    """
    Build two matrices:
      - A:J
      - L:P
    Leaving K untouched in the main refresh.
    """
    week_start_by_idx = {block["start_idx"]: block for block in week_blocks}

    left_matrix = []
    right_matrix = []

    for idx, row in enumerate(enriched_rows):
        raw = row["raw"]

        if idx in week_start_by_idx:
            block = week_start_by_idx[idx]
            week_label = block["label"]
            avg_sleep = block["avg_sleep"]
            avg_quality = block["avg_quality"]
        else:
            week_label = ""
            avg_sleep = ""
            avg_quality = ""

        left_matrix.append(
            [
                week_label,                       # A
                avg_sleep,                        # B
                avg_quality,                      # C
                raw.get("calendarDate", ""),      # D
                raw.get("sleepTime", ""),         # E
                "",                               # F (formula set separately)
                raw.get("sleepNeed", ""),         # G
                raw.get("sleepStartTime", ""),    # H
                raw.get("sleepEndTime", ""),      # I
                raw.get("overallSleepScore", ""), # J
            ]
        )

        right_matrix.append(
            [
                raw.get("avgHeartRate", ""),      # L
                raw.get("avgSleepStress", ""),    # M
                raw.get("deepSleep", ""),         # N
                raw.get("lightSleep", ""),        # O
                raw.get("remSleep", ""),          # P
            ]
        )

    return left_matrix, right_matrix


def set_time_sleep_formula(worksheet, start_row: int, record_count: int) -> None:
    if record_count <= 0:
        return

    end_row = DATA_START_ROW + record_count - 1
    formula = (
        "=IFERROR("
        "IF(OR(H{row}=\"\",I{row}=\"\"),\"\"," 
        "IF(I{row}>=H{row},I{row}-H{row},(1-H{row})+I{row})"
        "),"
        "\"\""
        ")"
    )

    formulas = [[formula.format(row=row)] for row in range(start_row, end_row + 1)]
    worksheet.update(
        range_name=f"F{start_row}:F{end_row}",
        values=formulas,
        value_input_option="USER_ENTERED"
    )


def unmerge_existing_ranges(spreadsheet, worksheet, start_row: int = DATA_START_ROW) -> None:
    spreadsheet.batch_update(
        {
            "requests": [
                {
                    "unmergeCells": {
                        "range": {
                            "sheetId": worksheet.id,
                            "startRowIndex": start_row - 1,
                            "endRowIndex": worksheet.row_count,
                            "startColumnIndex": 0,
                            "endColumnIndex": 16,
                        }
                    }
                }
            ]
        }
    )


def ensure_worksheet_row_capacity(worksheet, required_row_count: int) -> None:
    current_rows = worksheet.row_count
    if current_rows < required_row_count:
        worksheet.add_rows(required_row_count - current_rows)
        

def merge_week_summary_blocks(spreadsheet, worksheet, week_blocks: list[dict]) -> None:
    requests = []

    for block in week_blocks:
        start_row = block["start_row"]
        end_row = block["end_row"]

        if end_row <= start_row:
            continue

        for col_index in range(3):  # A, B, C
            requests.append(
                {
                    "mergeCells": {
                        "range": {
                            "sheetId": worksheet.id,
                            "startRowIndex": start_row - 1,
                            "endRowIndex": end_row,
                            "startColumnIndex": col_index,
                            "endColumnIndex": col_index + 1,
                        },
                        "mergeType": "MERGE_ALL",
                    }
                }
            )

    if requests:
        spreadsheet.batch_update({"requests": requests})


def apply_week_borders(spreadsheet, worksheet, week_blocks: list[dict]) -> None:
    # Value clearing does not remove formatting. Reset the entire managed area
    # so old partial-week bottom borders disappear as the week grows.
    requests = [{
        "updateBorders": {
            "range": {
                "sheetId": worksheet.id,
                "startRowIndex": DATA_START_ROW - 1,
                "endRowIndex": worksheet.row_count,
                "startColumnIndex": 0,
                "endColumnIndex": 16,
            },
            **{edge: {"style": "NONE"} for edge in
               ("top", "bottom", "left", "right", "innerHorizontal", "innerVertical")},
        }
    }]

    for block in week_blocks:
        start_row = block["start_row"]
        end_row = block["end_row"]

        requests.append(
            {
                "updateBorders": {
                    "range": {
                        "sheetId": worksheet.id,
                        "startRowIndex": start_row - 1,
                        "endRowIndex": end_row,
                        "startColumnIndex": 0,
                        "endColumnIndex": 16,
                    },
                    "top": {"style": "SOLID_MEDIUM"},
                    "bottom": {"style": "SOLID_MEDIUM"},
                }
            }
        )

    if requests:
        spreadsheet.batch_update({"requests": requests})


def apply_sheet_formatting(spreadsheet, worksheet, start_row: int, record_count: int) -> None:
    if record_count <= 0:
        return

    sheet_id = worksheet.id
    start_row_index = start_row - 1
    end_row_index = start_row - 1 + record_count

    def repeat_cell_request(start_col: int, end_col: int, number_type: str, pattern: str):
        return {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": start_row_index,
                    "endRowIndex": end_row_index,
                    "startColumnIndex": start_col,
                    "endColumnIndex": end_col,
                },
                "cell": {
                    "userEnteredFormat": {
                        "numberFormat": {
                            "type": number_type,
                            "pattern": pattern,
                        },
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                    }
                },
                "fields": (
                    "userEnteredFormat.numberFormat,"
                    "userEnteredFormat.horizontalAlignment,"
                    "userEnteredFormat.verticalAlignment"
                ),
            }
        }

    requests = [
        repeat_cell_request(1, 2, "TIME", "[hh]:mm"),       # B AVG HOURS
        repeat_cell_request(2, 3, "NUMBER", "0.0"),         # C AVG QUALITY
        repeat_cell_request(3, 4, "DATE", "dd-mm-yyyy"),    # D DATE
        repeat_cell_request(4, 5, "TIME", "[hh]:mm"),       # E WATCH SLEEP
        repeat_cell_request(5, 6, "TIME", "[hh]:mm"),       # F TIME SLEEP
        repeat_cell_request(6, 7, "TIME", "[hh]:mm"),       # G SLEEP NEED
        repeat_cell_request(7, 8, "TIME", "hh:mm"),         # H BED TIME
        repeat_cell_request(8, 9, "TIME", "hh:mm"),         # I WAKE UP
        repeat_cell_request(9, 10, "NUMBER", "0"),          # J QUALITY
        repeat_cell_request(11, 12, "NUMBER", "0.0"),       # L AVERAGE HR
        repeat_cell_request(12, 13, "NUMBER", "0.0"),       # M AVERAGE SLEEP STRESS
        repeat_cell_request(13, 14, "TIME", "[hh]:mm"),     # N DEEP SLEEP
        repeat_cell_request(14, 15, "TIME", "[hh]:mm"),     # O LIGHT SLEEP
        repeat_cell_request(15, 16, "TIME", "[hh]:mm"),     # P REM SLEEP
    ]

    requests.append(
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": start_row_index,
                    "endIndex": end_row_index,
                },
                "properties": {
                    "pixelSize": 25
                },
                "fields": "pixelSize",
            }
        }
    )

    spreadsheet.batch_update({"requests": requests})


def read_existing_notes(worksheet) -> dict[str, str]:
    notes = {}
    for row in worksheet.get(f"D{DATA_START_ROW}:K", value_render_option="FORMATTED_VALUE"):
        if not row or not row[0]:
            continue
        parsed = None
        for pattern in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                parsed = datetime.strptime(str(row[0]), pattern).date().isoformat()
                break
            except ValueError:
                pass
        if parsed is None:
            raise ValueError("Unexpected date format in sleep sheet; notes were not overwritten")
        note = str(row[7]) if len(row) > 7 else ""
        if parsed in notes and notes[parsed] != note:
            raise ValueError("Duplicate sleep dates with different notes; resolve before updating")
        notes[parsed] = note
    return notes


def export_sleep_to_gsheet() -> None:
    if WEEK_1_START is None:
        raise ValueError("Set COACHING_START_DATE for the sleep sheet")
    data = load_sleep_data(INPUT_FILE)

    client = get_gspread_client()
    spreadsheet = get_spreadsheet(client)
    worksheet = get_or_create_worksheet(spreadsheet, WORKSHEET_NAME)

    enriched_rows = build_enriched_rows(data)
    record_count = len(enriched_rows)

    if record_count == 0:
        print("No sleep records found.")
        return

    pre_coaching_row_count = get_pre_coaching_row_count(enriched_rows)

    if record_count == 0:
        print("No sleep records found.")
        return
    
    required_rows = DATA_START_ROW + record_count - 1
    ensure_worksheet_row_capacity(worksheet, required_rows)

    week_blocks = build_week_blocks(enriched_rows)
    left_matrix, right_matrix = build_sheet_matrices(enriched_rows, week_blocks)

    # A pending snapshot survives a failed sheet refresh. Restore it on retry
    # before consulting rows that could have been left half-updated.
    notes_pending = DATA_DIR / "sleep_sheet_notes.pending.json"
    if notes_pending.exists():
        with notes_pending.open(encoding="utf-8") as source:
            notes = json.load(source)
    else:
        notes = read_existing_notes(worksheet)
        atomic_json(notes_pending, notes)
    atomic_json(DATA_DIR / "sleep_sheet_notes.json", notes)

    start_row = DATA_START_ROW
    end_row = DATA_START_ROW + record_count - 1

    print(f"\n    Refreshing all auto-managed sleep rows ({record_count} total).")

    # Step 1: remove merges so updates/deletes don't clash with merged cells
    unmerge_existing_ranges(spreadsheet, worksheet, DATA_START_ROW)

    # Clear only auto-managed columns; do not delete rows or partial-week notes.
    clear_auto_managed_ranges(worksheet)

    # Step 4: rewrite all auto-managed data
    worksheet.update(
        range_name=f"A{start_row}:J{end_row}",
        values=left_matrix,
        value_input_option="USER_ENTERED"
    )
    worksheet.update(
        range_name=f"L{start_row}:P{end_row}",
        values=right_matrix,
        value_input_option="USER_ENTERED"
    )
    worksheet.update(
        range_name=f"K{start_row}:K{end_row}",
        values=[[notes.get(row["raw"]["calendarDate"], "")] for row in enriched_rows],
        value_input_option="RAW",
    )

    # Step 5: rebuild formulas for all rows
    set_time_sleep_formula(worksheet, DATA_START_ROW, record_count)

    # Step 6: rebuild merges, borders, formatting for all rows
    merge_week_summary_blocks(spreadsheet, worksheet, week_blocks)
    apply_week_borders(spreadsheet, worksheet, week_blocks)
    apply_sheet_formatting(spreadsheet, worksheet, DATA_START_ROW, record_count)

    # Reset row visibility for the full managed area
    unhide_sleep_rows(spreadsheet, worksheet, DATA_START_ROW, end_row)

    # Hide rows before coaching start
    hide_pre_coaching_rows(spreadsheet, worksheet, pre_coaching_row_count)
    notes_pending.unlink()

    print(f"\n    Exported {record_count} sleep records to '{spreadsheet.title}' / '{WORKSHEET_NAME}'")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Publish saved sleep data to Google Sheets")
    parser.add_argument("--check", action="store_true", help="Check configuration and read-only spreadsheet access")
    args = parser.parse_args()
    if args.check:
        check_spreadsheet_access()
    else:
        export_sleep_to_gsheet()
