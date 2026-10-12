"""Rolling 60-day chart formulas and native Google Sheets chart specifications."""
from copy import deepcopy
from datetime import date, timedelta

HELPER_TITLE = "_Sparkes chart data"
HELPER_ROWS = 370


def serial(day):
    return (day - date(1899, 12, 30)).days


def chart_window(as_of):
    # Include today: 59 previous days plus today is exactly 60 days.
    return as_of - timedelta(days=59), as_of


def chart_rows(title, first_day, last_row, as_of):
    start, end = chart_window(as_of)
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


def plan_charts(metadata, diary, first_day, last_row, as_of, *, include_chart_specs=False):
    charts = diary.get("charts", [])
    steps_charts = [chart for chart in charts if chart.get("spec", {}).get("title", "").strip().upper() == "AVERAGE WEEKLY STEPS"]
    daily_charts = [chart for chart in charts if chart not in steps_charts]
    # Publishing the helper table must work even while charts are being edited.
    # Native Apps Script owns the visible charts; spec planning is opt-in only.
    if include_chart_specs and (len(daily_charts) != 2 or len(steps_charts) > 1 or
                               any("overlayPosition" not in chart.get("position", {}) for chart in charts)):
        raise ValueError("Expected two calorie/weight charts and at most one weekly steps chart")
    def anchor(chart):
        cell = chart["position"]["overlayPosition"]["anchorCell"]
        overlay = chart["position"]["overlayPosition"]
        return cell.get("columnIndex", 0), overlay.get("offsetXPixels", 0), cell.get("rowIndex", 0)
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
    # Clear trailing data left by the previous, longer chart window.
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
    if not include_chart_specs:
        return requests
    left = min(daily_charts, key=anchor)
    start, end = chart_window(as_of)
    for chart in charts:
        # Apps Script applies these chart changes natively; REST can lose bounds.
        spec = deepcopy(chart["spec"])
        basic = spec["basicChart"]
        is_steps = chart in steps_charts
        calories = chart is left
        metric_column = 1 if is_steps else 4 if calories else 10
        spec["title"] = "AVERAGE WEEKLY STEPS" if is_steps else "CALORIE INTAKE" if calories else "BODY WEIGHT"
        basic["chartType"] = "LINE"
        basic["interpolateNulls"] = False
        def data(column):
            return {"sourceRange": {"sources": [{"sheetId": helper_id,
                "startRowIndex": 0, "endRowIndex": daily_count + 1,
                "startColumnIndex": column, "endColumnIndex": column + 1}]}}
        basic["domains"] = [{"domain": data(0 if is_steps else 3)}]
        basic["series"] = [{"series": data(metric_column), "targetAxis": "LEFT_AXIS",
            "color": {"red": 0.96, "green": 0.42, "blue": 0.09} if calories else
                     {"red": 0.43, "green": 0.28, "blue": 0.81},
            "lineStyle": {"width": 2, "type": "SOLID"},
            "pointStyle": {"size": 2 if calories else 0}}]
        horizontal = deepcopy(next((axis for axis in basic.get("axis", [])
                                    if axis["position"] == "BOTTOM_AXIS"), {"position": "BOTTOM_AXIS"}))
        basic["axis"] = [horizontal, {"position": "LEFT_AXIS",
            "title": "Calories (kcal)" if calories else "Body weight (kg)",
            "viewWindowOptions": {"viewWindowMode": "EXPLICIT",
                "viewWindowMin": 1500 if calories else 95,
                "viewWindowMax": 3000 if calories else 105}}]
        if is_steps:
            basic["axis"][1] = deepcopy(next((axis for axis in chart["spec"]["basicChart"].get("axis", [])
                if axis["position"] == "LEFT_AXIS"), {"position": "LEFT_AXIS", "title": "Steps / day"}))
            basic["series"] = deepcopy(chart["spec"]["basicChart"]["series"][:1])
            basic["series"][0]["series"] = data(1)
        count = weekly_count if is_steps else daily_count
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
