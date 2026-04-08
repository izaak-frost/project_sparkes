from pathlib import Path
from datetime import date, timedelta, datetime
from garminconnect import Garmin
import json
import os

from ..sub_modules.file_utilities import save_to_json

# Output path
OUTPUT_FILE = Path("data/sleep_data.json")
OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)


def seconds_to_hhmm(seconds: int | float | None) -> str | None:
    """Convert seconds to HH:MM."""
    if seconds is None:
        return None

    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    return f"{hours:02}:{minutes:02}"


def minutes_to_hhmm(minutes: int | float | None) -> str | None:
    """Convert minutes to HH:MM."""
    if minutes is None:
        return None

    total_minutes = int(minutes)
    hours = total_minutes // 60
    mins = total_minutes % 60
    return f"{hours:02}:{mins:02}"


def timestamp_ms_to_hhmm(timestamp_ms: int | None) -> str | None:
    """Convert Garmin local timestamp in milliseconds to HH:MM."""
    if timestamp_ms is None:
        return None

    dt = datetime.fromtimestamp(timestamp_ms / 1000)
    return dt.strftime("%H:%M")


def load_existing_sleep_data(file_path: Path) -> list[dict]:
    """Load existing sleep data from JSON if it exists."""
    if not file_path.exists():
        return []

    try:
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return data

        print(f"Warning: {file_path} does not contain a list. Starting fresh.")
        return []

    except (json.JSONDecodeError, OSError) as exc:
        print(f"Warning: Could not read {file_path}: {exc}")
        return []


def get_existing_dates(existing_data: list[dict]) -> set[str]:
    """Extract existing calendarDate values so they can be skipped."""
    return {
        item.get("calendarDate")
        for item in existing_data
        if isinstance(item, dict) and item.get("calendarDate")
    }


def get_target_dates(start_date_str: str, end_date_str: str) -> list[str]:
    """Return all dates from start_date to end_date inclusive."""
    start_dt = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_dt = datetime.strptime(end_date_str, "%Y-%m-%d").date()

    dates = []
    current = start_dt
    while current <= end_dt:
        dates.append(current.isoformat())
        current += timedelta(days=1)

    return dates


def extract_single_sleep_record(raw_day: dict) -> dict | None:
    """
    Extract only the required sleep fields from a single Garmin sleep payload.
    Ignores sleepMovement entirely.
    """
    if not isinstance(raw_day, dict):
        print("Skipped: raw_day is not a dict")
        return None

    dto = raw_day.get("dailySleepDTO", {})
    if not isinstance(dto, dict) or not dto:
        print("Skipped: missing dailySleepDTO")
        return None

    sleep_scores = dto.get("sleepScores", {})
    if not isinstance(sleep_scores, dict):
        sleep_scores = {}

    overall_score = sleep_scores.get("overall", {})
    if not isinstance(overall_score, dict):
        overall_score = {}

    sleep_need = dto.get("sleepNeed", {})
    if not isinstance(sleep_need, dict):
        sleep_need = {}

    calendar_date = dto.get("calendarDate")
    if not calendar_date:
        print("Skipped: missing calendarDate")
        return None

    return {
        "calendarDate": calendar_date,
        "sleepTime": seconds_to_hhmm(dto.get("sleepTimeSeconds")),
        "sleepStartTime": timestamp_ms_to_hhmm(dto.get("sleepStartTimestampLocal")),
        "sleepEndTime": timestamp_ms_to_hhmm(dto.get("sleepEndTimestampLocal")),
        "deepSleep": seconds_to_hhmm(dto.get("deepSleepSeconds")),
        "lightSleep": seconds_to_hhmm(dto.get("lightSleepSeconds")),
        "remSleep": seconds_to_hhmm(dto.get("remSleepSeconds")),
        "avgSleepStress": dto.get("avgSleepStress"),
        "avgHeartRate": dto.get("avgHeartRate"),
        "overallSleepScore": overall_score.get("value"),
        "sleepNeed": minutes_to_hhmm(sleep_need.get("actual")),
    }


def get_sleep_data(garmin_connection: Garmin) -> list[dict]:
    """
    Fetch sleep data from START_DATE to the latest completed date,
    skipping dates already present in sleep_data.json.
    Saves incrementally after each successful fetch.
    """
    start_date = os.getenv("START_DATE", "2000-01-01")
    latest_date = (date.today() - timedelta(days=1)).isoformat()

    existing_data = load_existing_sleep_data(OUTPUT_FILE)
    existing_dates = get_existing_dates(existing_data)

    all_dates = get_target_dates(start_date, latest_date)
    missing_dates = [d for d in all_dates if d not in existing_dates]

    print(f"START_DATE: {start_date}")
    print(f"LATEST_DATE: {latest_date}")
    print(f"Existing records: {len(existing_data)}")
    print(f"Missing dates to fetch: {len(missing_dates)}")

    if not missing_dates:
        print("\nNo new sleep dates to fetch.")
        return existing_data

    for sleep_date in missing_dates:
        print(f"\nFetching sleep data for {sleep_date}...")

        try:
            raw_day = garmin_connection.get_sleep_data(sleep_date)
            print(f"Response type for {sleep_date}: {type(raw_day).__name__}")

            if not raw_day:
                print(f"No sleep data returned for {sleep_date}")
                continue

            record = extract_single_sleep_record(raw_day)

            if record is None:
                print(f"No usable sleep record extracted for {sleep_date}")
                continue

            if record["calendarDate"] in existing_dates:
                print(f"Date already exists after extraction: {record['calendarDate']}")
                continue

            existing_data.append(record)
            existing_dates.add(record["calendarDate"])

            existing_data.sort(key=lambda x: x.get("calendarDate", ""))
            save_to_json(existing_data, "sleep data", OUTPUT_FILE)

            print(f"Added sleep data for {record['calendarDate']}")

        except Exception as exc:
            print(f"Failed to fetch sleep data for {sleep_date}: {exc}")

    print(f"\nFinal sleep record count: {len(existing_data)}")
    return existing_data