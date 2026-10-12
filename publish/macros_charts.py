"""Rolling-year chart formulas and native Google Sheets chart specifications."""
from copy import deepcopy
from datetime import date, timedelta

HELPER_TITLE = "_Sparkes chart data"
HELPER_ROWS = 370


def serial(day):
    return (day - date(1899, 12, 30)).days


def year_window(as_of):
    try:
        anniversary = as_of.replace(year=as_of.year - 1)
    except ValueError:  # 29 February follows 28 February in a non-leap year.
        anniversary = as_of.replace(year=as_of.year - 1, day=28)
    return anniversary + timedelta(days=1), as_of


def chart_rows(title, first_day, last_row, as_of):
    start, end = year_window(as_of)
    source = "'" + title.replace("'", "''") + "'!"
    dates = f"{source}$B$39:$B${last_row}"
    steps = f"{source}$K$39:$K${last_row}"
    rows = [["Week (Tuesday–Monday)", "Average daily steps", "", "Date", "Calories (kcal)",
             "Recorded weight (kg)", "Previous weight", "Previous date", "Next weight", "Next date", "Weight trend (kg)"]]
    for index in range((end - start).days + 1):
        row = index + 2
        values = ["", "", "", serial(start + timedelta(days=index))]
        for column in ("I", "D"):
            metric = f"{source}${column}$39:${column}${last_row}"
            values.append(f'=IFERROR(AVERAGEIFS({metric},{dates},D{row},{metric},">0"),"")')
        rows.append(values)
    last = len(rows)
    for row in range(2, last + 1):
        previous_weight = f"G{row-1}" if row > 2 else '""'
        previous_date = f"H{row-1}" if row > 2 else '""'
        next_weight = f"I{row+1}" if row < last else '""'
        next_date = f"J{row+1}" if row < last else '""'
        # Only the plotted weight trend bridges gaps. Raw F and calorie E stay blank.
        rows[row-1].extend([
            f'=IF(ISNUMBER(F{row}),F{row},{previous_weight})',
            f'=IF(ISNUMBER(F{row}),D{row},{previous_date})',
            f'=IF(ISNUMBER(F{row}),F{row},{next_weight})',
            f'=IF(ISNUMBER(F{row}),D{row},{next_date})',
            f'=IF(ISNUMBER(F{row}),F{row},IF(AND(ISNUMBER(G{row}),ISNUMBER(I{row})),G{row}+(I{row}-G{row})*(D{row}-H{row})/(J{row}-H{row}),""))'])
    week = start - timedelta(days=(start - first_day).days % 7)
    weekly_count = 0
    while week <= end:
        lower, upper = max(week, start), min(week + timedelta(days=6), end)
        weekly_count += 1
        rows[weekly_count][0:2] = [serial(lower),
            f'=IFERROR(AVERAGEIFS({steps},{dates},">={serial(lower)}",{dates},"<={serial(upper)}"),"")']
        week += timedelta(days=7)
    return rows, weekly_count


def plan_charts(metadata, diary, first_day, last_row, as_of):
    charts = diary.get("charts", [])
    if len(charts) != 2 or any("overlayPosition" not in chart.get("position", {}) for chart in charts):
        raise ValueError("Expected the two existing dashboard charts; no chart changes made")
    def anchor(chart):
        cell = chart["position"]["overlayPosition"]["anchorCell"]
        return cell.get("rowIndex", 0), cell.get("columnIndex", 0)
    top = min(charts, key=anchor)
    bottom = next(chart for chart in charts if chart is not top)
    helper = next((sheet for sheet in metadata["sheets"] if sheet["properties"]["title"] == HELPER_TITLE), None)
    requests = []
    if helper is None:
        helper_id = max(sheet["properties"]["sheetId"] for sheet in metadata["sheets"]) + 1
        requests.append({"addSheet": {"properties": {"sheetId": helper_id, "title": HELPER_TITLE,
            "hidden": True, "gridProperties": {"rowCount": HELPER_ROWS, "columnCount": 11}}}})
    else:
        helper_id = helper["properties"]["sheetId"]
        requests.append({"updateSheetProperties": {"properties": {"sheetId": helper_id,
            "hidden": True, "gridProperties": {"rowCount": HELPER_ROWS, "columnCount": 11}},
            "fields": "hidden,gridProperties.rowCount,gridProperties.columnCount"}})
    rows, weekly_count = chart_rows(diary["properties"]["title"], first_day, last_row, as_of)
    daily_count = len(rows) - 1
    def cell(value):
        key = "formulaValue" if isinstance(value, str) and value.startswith("=") else "stringValue" if isinstance(value, str) else "numberValue"
        return {"userEnteredValue": {key: value}}
    # Clear the old trailing day/week when a leap-year window becomes shorter.
    filled = rows + [[""] * 11 for _ in range(HELPER_ROWS - len(rows))]
    requests.append({"updateCells": {"range": {"sheetId": helper_id, "startRowIndex": 0,
        "endRowIndex": HELPER_ROWS, "startColumnIndex": 0, "endColumnIndex": 11},
        "rows": [{"values": [cell(value) for value in row]} for row in filled], "fields": "userEnteredValue"}})
    for column, kind, pattern in ((0, "DATE", "mmm yy"), (3, "DATE", "mmm yy"),
                                  (1, "NUMBER", "#,##0"), (4, "NUMBER", "#,##0"), (5, "NUMBER", "0.0"), (10, "NUMBER", "0.0")):
        requests.append({"repeatCell": {"range": {"sheetId": helper_id, "startRowIndex": 1,
            "endRowIndex": HELPER_ROWS, "startColumnIndex": column, "endColumnIndex": column + 1},
            "cell": {"userEnteredFormat": {"numberFormat": {"type": kind, "pattern": pattern}}},
            "fields": "userEnteredFormat.numberFormat"}})
    start, end = year_window(as_of)
    for chart in charts:
        # Preserve the actual saved chart, including axis options whose defaults
        # differ from the API's EXPLICIT mode. Never rebuild the user's styling.
        spec = deepcopy(chart["spec"])
        basic = spec["basicChart"]
        count = weekly_count if chart is top else daily_count
        sources = [domain["domain"] for domain in basic.get("domains", [])]
        sources.extend(series["series"] for series in basic.get("series", []))
        for data in sources:
            for grid in data["sourceRange"]["sources"]:
                grid.update(sheetId=helper_id, startRowIndex=0, endRowIndex=count + 1)
        for axis in basic.get("axis", []):
            if axis["position"] == "BOTTOM_AXIS":
                axis.setdefault("viewWindowOptions", {}).update(
                    viewWindowMin=serial(start), viewWindowMax=serial(end))
        spec["subtitle"] = f"{start:%d %b %Y} – {end:%d %b %Y}"
        requests.append({"updateChartSpec": {"chartId": chart["chartId"], "spec": spec}})
    return requests
