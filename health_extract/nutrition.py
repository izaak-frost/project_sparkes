"""Validate Apple Health uploads and store complete daily nutrition totals."""
from datetime import date, datetime, timedelta, timezone
import json
import math
from zoneinfo import ZoneInfo

from support.config import Settings, NUTRITION_UNITS, GROUPED_ALIASES, DAILY_COLUMNS
from support.storage import database, store_nutrition_rows, set_state, utc_now, atomic_json, atomic_csv

def validate_quantity(value) -> float:
    if type(value) not in (int, float):
        raise ValueError("Nutrition quantities must be finite non-negative numbers")
    try:
        number = float(value)
    except OverflowError:
        raise ValueError("Nutrition quantity is too large") from None
    if not math.isfinite(number) or number < 0:
        raise ValueError("Nutrition quantities must be finite non-negative numbers")
    return number


def parse_nutrition(payload: dict, zone: str) -> list[tuple]:
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object")
    if "date" not in payload:
        # A single shortcut upload may contain several days grouped by nutrient.
        # Validate the complete batch before touching stored totals.
        source = payload.get("source", "nutracheck")
        records = {}
        for name, points in payload.items():
            if name == "source":
                continue
            field = GROUPED_ALIASES.get(name.casefold(), name.casefold())
            if field not in NUTRITION_UNITS or not isinstance(points, list):
                raise ValueError("Use nutrient keys with lists of {date, value} daily totals")
            for point in points:
                if not isinstance(point, dict) or set(point) != {"date", "value"}:
                    raise ValueError("Each nutrient entry must contain exactly date and value")
                row = parse_nutrition({"date": point["date"], "source": source,
                                       field: point["value"]}, zone)[0]
                key = (row[0], row[1])
                if key in records:
                    raise ValueError("Duplicate nutrient/date total; sum samples by day before uploading")
                records[key] = row
        if not records:
            raise ValueError("No nutrition totals supplied; do not replace missing samples with zero")
        return list(records.values())
    value = payload.get("date")
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError("Use date in YYYY-MM-DD format for a complete daily total")
    day = date.fromisoformat(value).isoformat()
    if day != value:
        raise ValueError("Use a calendar date in YYYY-MM-DD format")
    if day > datetime.now(ZoneInfo(zone)).date().isoformat():
        raise ValueError("Nutrition date cannot be in the future")
    source = payload.get("source")
    if source != "nutracheck":
        raise ValueError("Set source to nutracheck and filter Health samples to that app")
    unknown = set(payload) - {"date", "source"} - NUTRITION_UNITS.keys()
    if unknown:
        raise ValueError("Unsupported nutrition fields; use the documented daily totals format")
    records = [(day, field, validate_quantity(payload[field]), source)
               for field in NUTRITION_UNITS if field in payload]
    if not records:
        raise ValueError("No nutrition totals supplied; do not replace missing samples with zero")
    return records


def ingest_nutrition(settings: Settings, payload: dict) -> int:
    rows = parse_nutrition(payload, settings.timezone)
    received = utc_now()
    with database(settings) as conn:
        store_nutrition_rows(conn, [(*row, received) for row in rows])
        set_state(conn, "nutrition_received_at", received)
    return len(rows)


def export_nutrition(settings: Settings) -> dict:
    with database(settings) as conn:
        conn.execute("BEGIN")
        rows = conn.execute("SELECT * FROM nutrition ORDER BY date").fetchall()
        metadata = {row["date"]: json.loads(row["details"])
                    for row in conn.execute("SELECT * FROM nutrition_metadata")}
        state = dict(conn.execute("SELECT name, value FROM sync_state").fetchall())
    days = {}
    daily_rows = []
    for row in rows:
        daily_rows.append({column: round(value, 6) if isinstance(value, float) else value
                           for column, value in dict(row).items()})
        details = metadata.get(row["date"], {"sources": {}, "extras": {}})
        day = {"date": row["date"], "source": "apple_health", "sources": details["sources"],
               **details["extras"]}
        day.update({metric: round(row[column], 6) for column, metric in DAILY_COLUMNS.items()
                    if row[column] is not None})
        days[row["date"]] = day
    warnings = []
    received = state.get("nutrition_received_at")
    if not received:
        warnings.append("No nutrition upload received yet")
    elif (datetime.now(timezone.utc) - datetime.fromisoformat(received)).total_seconds() > settings.max_upload_age_hours * 3600:
        warnings.append("Nutrition uploads are stale; unlock the iPhone and run an export")
    yesterday = (datetime.now(ZoneInfo(settings.timezone)).date() - timedelta(days=1)).isoformat()
    if "calories_kcal" not in days.get(yesterday, {}):
        warnings.append(f"No calorie total received for {yesterday}; missing data is not zero intake")
    status = {"exported_at": utc_now(), **state, "nutrition_day_count": len(days),
              "latest_calorie_date": max((day for day, values in days.items() if "calories_kcal" in values), default=None),
              "nutrition_warnings": warnings}
    atomic_json(settings.data_dir / "nutrition_details.json", list(days.values()))
    atomic_json(settings.data_dir / "daily_nutrition.json", daily_rows)
    atomic_csv(settings.data_dir / "daily_nutrition.csv", daily_rows)
    return status


