from pathlib import Path
import json
import os
from datetime import datetime, date

import gspread
from gspread.exceptions import APIError
from dotenv import load_dotenv

load_dotenv()

INPUT_FILE = Path("data/sleep_data.json")
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
# K = NOTES/DIARY (manual, preserve)
# L = AVERAGE HR
# M = AVERAGE SLEEP STRESS
# N = DEEP SLEEP
# O = LIGHT SLEEP
# P = REM SLEEP

# Week 1 starts on 01/07/2025, then every 7 days after that
WEEK_1_START = date(2025, 7, 1)


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


def get_gspread_client() -> gspread.Client:
    service_account_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
    if not service_account_file:
        raise ValueError("Missing GOOGLE_SERVICE_ACCOUNT_FILE in environment variables.")
    return gspread.service_account(filename=service_account_file)


def get_spreadsheet(client: gspread.Client):
    spreadsheet_id = os.getenv("GOOGLE_SHEET_ID")
    spreadsheet_name = os.getenv("GOOGLE_SHEET_NAME")

    try:
        if spreadsheet_id:
            spreadsheet = client.open_by_key(spreadsheet_id)
            print(f"Opened spreadsheet by ID: {spreadsheet.title}")
        else:
            spreadsheet = client.open(spreadsheet_name)
            print(f"Opened spreadsheet by name: {spreadsheet_name}")
        return spreadsheet

    except gspread.SpreadsheetNotFound as exc:
        raise RuntimeError(
            "Spreadsheet not found. Make sure it exists and is shared with your service account."
        ) from exc

    except APIError:
        print("Google API error while opening spreadsheet.")
        print("Check that Google Sheets API and Google Drive API are enabled,")
        print("and that the spreadsheet is shared with your service account.")
        raise


def get_or_create_worksheet(spreadsheet, worksheet_name: str, rows: int = 3000, cols: int = 20):
    try:
        worksheet = spreadsheet.worksheet(worksheet_name)
        print(f"Opened existing worksheet: {worksheet_name}")
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=worksheet_name,
            rows=rows,
            cols=cols,
        )
        print(f"Created worksheet: {worksheet_name}")
    return worksheet


def clear_existing_ranges(worksheet) -> None:
    # Preserve column K (NOTES/DIARY)
    worksheet.batch_clear([
        "A3:J",
        "L3:P",
    ])


def build_enriched_rows(data: list[dict]) -> list[dict]:
    sorted_data = sorted(data, key=lambda x: x.get("calendarDate", ""))

    enriched_rows = []
    for item in sorted_data:
        d = parse_date(item["calendarDate"])
        enriched_rows.append(
            {
                "date": d,
                "week_num": week_number_for_date(d),
                "week_label": week_label_for_date(d),
                "time_sleep_minutes": None
                if not item.get("sleepStartTime") or not item.get("sleepEndTime")
                else (
                    hhmm_to_minutes(item["sleepEndTime"]) - hhmm_to_minutes(item["sleepStartTime"])
                    if hhmm_to_minutes(item["sleepEndTime"]) >= hhmm_to_minutes(item["sleepStartTime"])
                    else (24 * 60 - hhmm_to_minutes(item["sleepStartTime"])) + hhmm_to_minutes(item["sleepEndTime"])
                ),
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
      - avg_sleep
      - avg_quality
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

        sleep_values = [r["time_sleep_minutes"] for r in week_rows if r["time_sleep_minutes"] is not None]
        quality_values = [r["quality"] for r in week_rows if isinstance(r["quality"], (int, float))]

        avg_sleep = minutes_to_hhmm(sum(sleep_values) / len(sleep_values)) if sleep_values else ""
        avg_quality = round(sum(quality_values) / len(quality_values), 1) if quality_values else ""

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
    Leaving K untouched/preserved
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
                week_label,                              # A
                avg_sleep,                               # B
                avg_quality,                             # C
                raw.get("calendarDate", ""),             # D
                raw.get("sleepTime", ""),                # E
                "",                                      # F (formula set separately)
                raw.get("sleepNeed", ""),                # G
                raw.get("sleepStartTime", ""),           # H
                raw.get("sleepEndTime", ""),             # I
                raw.get("overallSleepScore", ""),        # J
            ]
        )

        right_matrix.append(
            [
                raw.get("avgHeartRate", ""),             # L
                raw.get("avgSleepStress", ""),           # M
                raw.get("deepSleep", ""),                # N
                raw.get("lightSleep", ""),               # O
                raw.get("remSleep", ""),                 # P
            ]
        )

    return left_matrix, right_matrix


def set_time_sleep_formula(worksheet, record_count: int) -> None:
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

    formulas = [[formula.format(row=row)] for row in range(DATA_START_ROW, end_row + 1)]
    worksheet.update(
    range_name=f"F{DATA_START_ROW}:F{end_row}",
    values=formulas,
    value_input_option="USER_ENTERED"
)


def unmerge_existing_ranges(spreadsheet, worksheet) -> None:
    spreadsheet.batch_update(
        {
            "requests": [
                {
                    "unmergeCells": {
                        "range": {
                            "sheetId": worksheet.id,
                            "startRowIndex": DATA_START_ROW - 1,
                            "endRowIndex": 3000,
                            "startColumnIndex": 0,
                            "endColumnIndex": 16,
                        }
                    }
                }
            ]
        }
    )


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
    requests = []

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
                    "left": {"style": "SOLID_MEDIUM"},
                    "right": {"style": "SOLID_MEDIUM"},
                }
            }
        )

    if requests:
        spreadsheet.batch_update({"requests": requests})


def apply_sheet_formatting(spreadsheet, worksheet, record_count: int) -> None:
    if record_count <= 0:
        return

    sheet_id = worksheet.id
    start_row_index = DATA_START_ROW - 1
    end_row_index = DATA_START_ROW - 1 + record_count

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

    requests.append({
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
})

    spreadsheet.batch_update({"requests": requests})


def export_sleep_to_gsheet() -> None:
    data = load_sleep_data(INPUT_FILE)

    client = get_gspread_client()
    spreadsheet = get_spreadsheet(client)
    worksheet = get_or_create_worksheet(spreadsheet, WORKSHEET_NAME)

    clear_existing_ranges(worksheet)

    enriched_rows = build_enriched_rows(data)
    record_count = len(enriched_rows)

    if record_count == 0:
        print("No sleep records found.")
        return

    week_blocks = build_week_blocks(enriched_rows)
    left_matrix, right_matrix = build_sheet_matrices(enriched_rows, week_blocks)

    end_row = DATA_START_ROW + record_count - 1

    # Write data in two contiguous blocks so K is preserved
    worksheet.update(
        range_name=f"A{DATA_START_ROW}:J{end_row}",
        values=left_matrix,
        value_input_option="USER_ENTERED"
    )
    worksheet.update(
        range_name=f"L{DATA_START_ROW}:P{end_row}",
        values=right_matrix,
        value_input_option="USER_ENTERED"
    )
    # Rebuild formula column
    set_time_sleep_formula(worksheet, record_count)

    # Rebuild merges and borders
    unmerge_existing_ranges(spreadsheet, worksheet)
    merge_week_summary_blocks(spreadsheet, worksheet, week_blocks)
    apply_week_borders(spreadsheet, worksheet, week_blocks)

    # Number/date/time formatting
    apply_sheet_formatting(spreadsheet, worksheet, record_count)

    print(f"Exported {record_count} sleep records to '{spreadsheet.title}' / '{WORKSHEET_NAME}'")
    print(f"Spreadsheet URL: {spreadsheet.url}")


if __name__ == "__main__":
    export_sleep_to_gsheet()