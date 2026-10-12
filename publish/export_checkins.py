"""Keep a blank six-question week at the bottom of CHECK IN QUESTIONS."""
import argparse
from datetime import datetime

from publish.export_sleep import get_gspread_client, get_spreadsheet
from support.runtime import PUBLISH_DATA_DIR
from support.storage import atomic_json

WORKSHEET_NAME = "CHECK IN QUESTIONS"
HEADER_ROW = 8
FIRST_ROW = 9
BLOCK_ROWS = 6


def cell(rows, row, column):
    return rows[row][column] if row < len(rows) and column < len(rows[row]) else ""


def plan_blank_week(worksheet, rows, metadata):
    """Plan one atomic append, preserving existing answers and manual formatting."""
    expected = {1: "WEEK", 2: "QUESTION", 4: "CLIENT RESPONSE", 15: "COMPLETE?", 16: "RESPONSE"}
    if any(str(cell(rows, HEADER_ROW - 1, column)).strip().upper() != label
           for column, label in expected.items()):
        raise ValueError("Check-in headers differ from the expected B8:R8 layout; no cells changed")
    anchors = [(row, cell(rows, row, 1)) for row in range(FIRST_ROW - 1, len(rows))
               if cell(rows, row, 1) not in (None, "")]
    if not anchors:
        raise ValueError("No existing check-in week to use as a template")
    start, week = anchors[-1]
    if type(week) not in (int, float) or week < 1 or int(week) != week:
        raise ValueError("Last check-in week must have a positive numeric label")
    end = start + BLOCK_ROWS
    if end > worksheet.row_count or any(not str(cell(rows, row, 2)).strip() for row in range(start, end)):
        raise ValueError("Last check-in week must contain six questions; no cells changed")
    week_merges = [merge for merge in metadata.get("merges", [])
                   if merge.get("startColumnIndex") == 1 and merge.get("endColumnIndex") == 2
                   and merge.get("startRowIndex") == start and merge.get("endRowIndex") == end]
    if len(week_merges) != 1:
        raise ValueError("Expected a six-row merged check-in week label; no cells changed")
    # A default unchecked checkbox is False, and is not a completed response.
    used = any(cell(rows, row, column) not in (None, "")
               for row in range(start, end) for column in (*range(4, 15), 16, 17))
    used = used or any(cell(rows, row, 15) not in (None, "", False) for row in range(start, end))
    if not used:
        return [], None
    destination_end = end + BLOCK_ROWS
    if any(cell(rows, row, column) not in (None, "")
           for row in range(end, destination_end) for column in range(1, 18)):
        raise ValueError("Content follows the last check-in week; no cells changed")
    requests = []
    if destination_end > worksheet.row_count:
        requests.append({"appendDimension": {"sheetId": worksheet.id, "dimension": "ROWS",
                                             "length": destination_end - worksheet.row_count}})
    source = {"sheetId": worksheet.id, "startRowIndex": start, "endRowIndex": end,
              "startColumnIndex": 1, "endColumnIndex": 18}
    destination = {**source, "startRowIndex": end, "endRowIndex": destination_end}
    requests.append({"copyPaste": {"source": source, "destination": destination,
                                  "pasteType": "PASTE_NORMAL", "pasteOrientation": "NORMAL"}})
    # Clear only the new client/coach responses. Keep questions, styles and validation.
    for left, right in ((4, 15), (16, 18)):
        requests.append({"updateCells": {"range": {**destination,
            "startColumnIndex": left, "endColumnIndex": right}, "fields": "userEnteredValue"}})
    requests.append({"updateCells": {"range": {**destination, "startColumnIndex": 15, "endColumnIndex": 16},
        "rows": [{"values": [{"userEnteredValue": {"boolValue": False}}]} for _ in range(BLOCK_ROWS)],
        "fields": "userEnteredValue"}})
    requests.append({"updateCells": {"start": {"sheetId": worksheet.id, "rowIndex": end, "columnIndex": 1},
        "rows": [{"values": [{"userEnteredValue": {"numberValue": int(week) + 1}}]}],
        "fields": "userEnteredValue"}})
    # Copy individual row heights when supplied by the metadata read.
    heights = {}
    for grid in metadata.get("data", []):
        for offset, properties in enumerate(grid.get("rowMetadata", [])):
            heights[grid.get("startRow", 0) + offset] = properties
    for offset in range(BLOCK_ROWS):
        properties = heights.get(start + offset, {})
        if "pixelSize" in properties:
            requests.append({"updateDimensionProperties": {"range": {"sheetId": worksheet.id,
                "dimension": "ROWS", "startIndex": end + offset, "endIndex": end + offset + 1},
                "properties": {"pixelSize": properties["pixelSize"]}, "fields": "pixelSize"}})
    return requests, int(week) + 1


def export_checkins_to_gsheet(dry_run=False):
    book = get_spreadsheet(get_gspread_client())
    matches = [sheet for sheet in book.worksheets() if sheet.title.strip().upper() == WORKSHEET_NAME]
    if len(matches) != 1:
        raise ValueError("Expected exactly one CHECK IN QUESTIONS tab")
    worksheet = matches[0]
    rows = worksheet.get(value_render_option="UNFORMATTED_VALUE")
    # Read grid metadata for row heights; cell contents are not needed here.
    title = worksheet.title.replace("'", "''")
    metadata = book.fetch_sheet_metadata(params={"includeGridData": True,
        "ranges": f"'{title}'!B1:R{worksheet.row_count}",
        "fields": "sheets(properties,merges,data(startRow,rowMetadata))"})
    meta = next(sheet for sheet in metadata["sheets"] if sheet["properties"]["sheetId"] == worksheet.id)
    requests, week = plan_blank_week(worksheet, rows, meta)
    if not requests:
        print("Check-in questions: last week is already blank.")
        return
    if dry_run:
        print(f"Check-in questions: would append blank Week {week}; no cells changed.")
        return
    formulas = worksheet.get(value_render_option="FORMULA")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    atomic_json(PUBLISH_DATA_DIR / f"checkins_before_append_{stamp}.json", {
        "spreadsheet_id": book.id, "worksheet_id": worksheet.id,
        "captured_at": datetime.now().isoformat(), "values": formulas, "merges": meta.get("merges", [])})
    book.batch_update({"requests": requests})
    print(f"Check-in questions: appended blank Week {week}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    export_checkins_to_gsheet(parser.parse_args().dry_run)
