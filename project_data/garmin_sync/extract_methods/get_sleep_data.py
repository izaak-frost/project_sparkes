from pathlib import Path
from datetime import date, timedelta, datetime, timezone
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

    dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
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

        print(f"[WARN] {file_path} does not contain a list. Starting fresh.")
        return []

    except (json.JSONDecodeError, OSError) as exc:
        print(f"[WARN] Could not read {file_path}: {exc}")
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
    """
    if not isinstance(raw_day, dict):
        return None

    dto = raw_day.get("dailySleepDTO", {})
    if not isinstance(dto, dict) or not dto:
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
    Fetch sleep data from START_DATE to today inclusive.

    - Skips dates already present in sleep_data.json
    - Attempts to fetch today's sleep in case Garmin has already published it
    - Safely skips dates where no sleep data is available yet
    - Saves incrementally after each successful fetch
    """
    start_date = os.getenv("START_DATE", "2000-01-01")
    latest_date = date.today().isoformat()

    print(f"    Fetching sleep data from {start_date} to {latest_date}...")

    existing_data = load_existing_sleep_data(OUTPUT_FILE)
    existing_dates = get_existing_dates(existing_data)

    all_dates = get_target_dates(start_date, latest_date)
    missing_dates = [d for d in all_dates if d not in existing_dates]

    if not missing_dates:
        print(f"    Saved {len(existing_data)} days of sleep data to {OUTPUT_FILE}")
        return existing_data

    for sleep_date in missing_dates:
        try:
            raw_day = garmin_connection.get_sleep_data(sleep_date)
            record = extract_single_sleep_record(raw_day)

            if record is None:
                print(f"    No sleep data available for {sleep_date}; skipping.")
                continue

            if record["calendarDate"] in existing_dates:
                continue

            existing_data.append(record)
            existing_dates.add(record["calendarDate"])

            existing_data.sort(key=lambda x: x.get("calendarDate", ""))
            save_to_json(existing_data, "days of sleep data", OUTPUT_FILE)

        except Exception as exc:
            print(f"[ERROR] Failed to fetch sleep data for {sleep_date}: {exc}")

    return existing_data