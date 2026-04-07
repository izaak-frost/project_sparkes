from pathlib import Path
from datetime import date
from garminconnect import Garmin
import os

from ..sub_modules.file_utilities import save_to_json

# Output path
OUTPUT_FILE = Path("garmin_sync/data/daily_steps.json")
OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

def fetch_raw_steps(garmin_connection: Garmin) -> list[dict]:
    """Fetch raw daily steps data from Garmin."""
    start_date = os.getenv("START_DATE", "2000-01-01")
    end_date = date.today().isoformat()

    print(f"\nFetching daily steps from {start_date} to {end_date}...")
    data = garmin_connection.get_daily_steps(start_date, end_date)

    if not isinstance(data, list):
        raise ValueError(
            f"Unexpected response type from Garmin: {type(data).__name__}"
        )

    return data


def extract_date_step_pairs(raw_data: list[dict]) -> list[dict]:
    """
    Convert Garmin step response into:
    [
        {
            "date": "YYYY-MM-DD",
            "steps": 12345
        },
        ...
    ]
    """
    results = []

    for day in raw_data:
        summary_date = day.get("calendarDate")
        steps = day.get("totalSteps")

        # Skip rows with no useful data
        if summary_date and steps is not None:
            results.append(
                {
                    "date": summary_date,
                    "steps": steps
                }
            )

    return results


def get_step_data(garmin_connection) -> list[dict]:

    raw_data = fetch_raw_steps(garmin_connection)
    daily_step_data = extract_date_step_pairs(raw_data)
    save_to_json(daily_step_data, "daily steps", OUTPUT_FILE)

    return
