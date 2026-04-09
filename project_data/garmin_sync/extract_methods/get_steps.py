from pathlib import Path
from datetime import date, datetime, timedelta
from garminconnect import Garmin
import os
import json

from ..sub_modules.file_utilities import save_to_json

# Output path
OUTPUT_FILE = Path("data/daily_steps.json")
OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_existing_step_data(file_path: Path) -> list[dict]:
    """Load existing daily step data from JSON if available."""
    if not file_path.exists():
        return []

    try:
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            print(f"Warning: {file_path} did not contain a list. Ignoring existing data.")
            return []

        return data

    except (json.JSONDecodeError, OSError) as exc:
        print(f"Warning: Could not read existing step data from {file_path}: {exc}")
        return []


def daterange(start: date, end: date):
    """Yield dates from start to end inclusive."""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def get_missing_dates(
    existing_data: list[dict],
    start_date_str: str,
    end_date_str: str,
    force_refresh_days: int = 3
) -> list[str]:
    """
    Return date strings that should be fetched:
    - any missing dates in the full range
    - the last `force_refresh_days` days regardless
    """
    start_dt = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_dt = datetime.strptime(end_date_str, "%Y-%m-%d").date()

    existing_dates = {
        row["date"]
        for row in existing_data
        if isinstance(row, dict) and row.get("date")
    }

    all_dates = {d.isoformat() for d in daterange(start_dt, end_dt)}

    refresh_start = max(start_dt, end_dt - timedelta(days=force_refresh_days - 1))
    refresh_dates = {d.isoformat() for d in daterange(refresh_start, end_dt)}

    missing_dates = (all_dates - existing_dates) | refresh_dates

    return sorted(missing_dates)


def group_consecutive_dates(date_strings: list[str]) -> list[tuple[str, str]]:
    """
    Group sorted date strings into contiguous date ranges.
    Example:
    ["2026-04-01", "2026-04-02", "2026-04-04"]
    -> [("2026-04-01", "2026-04-02"), ("2026-04-04", "2026-04-04")]
    """
    if not date_strings:
        return []

    dates = [datetime.strptime(d, "%Y-%m-%d").date() for d in sorted(date_strings)]
    ranges = []

    range_start = dates[0]
    previous = dates[0]

    for current in dates[1:]:
        if current == previous + timedelta(days=1):
            previous = current
            continue

        ranges.append((range_start.isoformat(), previous.isoformat()))
        range_start = current
        previous = current

    ranges.append((range_start.isoformat(), previous.isoformat()))
    return ranges


def fetch_raw_steps_for_ranges(
    garmin_connection: Garmin,
    date_ranges: list[tuple[str, str]]
) -> list[dict]:
    """Fetch raw daily steps data from Garmin for one or more date ranges."""
    all_data = []

    for start_date, end_date in date_ranges:
        print(f"    Fetching daily steps from {start_date} to {end_date}")
        data = garmin_connection.get_daily_steps(start_date, end_date)

        if not isinstance(data, list):
            raise ValueError(
                f"Unexpected response type from Garmin: {type(data).__name__}"
            )

        all_data.extend(data)

    return all_data


def extract_date_step_pairs(
    raw_data: list[dict],
    expected_dates: list[str]
) -> list[dict]:
    """
    Ensure every expected date is present.
    Missing dates will have steps = None.
    """

    # Map returned data by date
    data_by_date = {}

    for day in raw_data:
        summary_date = day.get("calendarDate")
        steps = day.get("totalSteps")

        if summary_date:
            data_by_date[summary_date] = steps

    # Build full dataset including missing days
    results = []

    for d in expected_dates:
        results.append(
            {
                "date": d,
                "steps": data_by_date.get(d)  # None if missing
            }
        )

    return results


def merge_step_data(existing_data: list[dict], new_data: list[dict]) -> list[dict]:
    """
    Merge existing and new data, preferring new records when dates overlap.
    """
    merged = {}

    for row in existing_data:
        if isinstance(row, dict) and row.get("date"):
            merged[row["date"]] = row

    for row in new_data:
        if isinstance(row, dict) and row.get("date"):
            merged[row["date"]] = row

    return [merged[d] for d in sorted(merged.keys())]


def get_step_data(garmin_connection: Garmin) -> list[dict]:
    start_date = os.getenv("START_DATE", "2000-01-01")
    end_date = date.today().isoformat()

    existing_data = load_existing_step_data(OUTPUT_FILE)
    dates_to_fetch = get_missing_dates(existing_data, start_date, end_date, force_refresh_days=3)

    if not dates_to_fetch:
        print("No missing dates found. Existing data is up to date.")
        return existing_data

    date_ranges = group_consecutive_dates(dates_to_fetch)
    raw_data = fetch_raw_steps_for_ranges(garmin_connection, date_ranges)
    new_step_data = extract_date_step_pairs(raw_data,dates_to_fetch)

    merged_step_data = merge_step_data(existing_data, new_step_data)
    save_to_json(merged_step_data, "daily steps", OUTPUT_FILE)

    return merged_step_data