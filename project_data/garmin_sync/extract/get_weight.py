from pathlib import Path
from datetime import date
from garminconnect import Garmin
import json

from ..garmin_authentication import authenticate

# Output path
OUTPUT_FILE = Path("garmin_sync/data/weights.json")
OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

def fetch_raw_weigh_ins(garmin_connection: Garmin) -> dict:
    """Fetch raw all-time-ish weigh-in data from Garmin."""
    start_date = "2000-01-01"
    end_date = date.today().isoformat()

    print(f"Fetching weigh-ins from {start_date} to {end_date}...")
    data = garmin_connection.get_weigh_ins(start_date, end_date)

    if not isinstance(data, dict):
        raise ValueError(f"Unexpected response type from Garmin: {type(data).__name__}")

    return data


def normalise_weight(weight_value):
    """
    Garmin often returns weight in grams, e.g. 96800.0 for 96.8 kg.
    Convert to kg when appropriate.
    """
    if isinstance(weight_value, (int, float)) and weight_value > 1000:
        return round(weight_value / 1000, 1)
    return weight_value


def extract_date_weight_pairs(raw_data: dict) -> list[dict]:
    """
    Convert Garmin's nested response into:
    [
      {"date": "YYYY-MM-DD", "weight": ##.#},
      ...
    ]
    """
    results = []
    daily_summaries = raw_data.get("dailyWeightSummaries", [])

    for day in daily_summaries:
        latest = day.get("latestWeight") or {}
        summary_date = day.get("summaryDate") or latest.get("calendarDate")
        weight = latest.get("weight")

        if summary_date and weight is not None:
            results.append(
                {
                    "date": summary_date,
                    "weight": normalise_weight(weight),
                }
            )

    return results


def save_to_json(data: list[dict]) -> None:
    """Save simplified weigh-in data to JSON."""
    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(data)} weigh-ins to {OUTPUT_FILE}")


def get_weight_data() -> list[dict]:
    garmin_connection = authenticate()

    if garmin_connection is None:
        raise RuntimeError("Failed to authenticate with Garmin.")

    raw_data = fetch_raw_weigh_ins(garmin_connection)
    weigh_ins = extract_date_weight_pairs(raw_data)
    save_to_json(weigh_ins)

    return weigh_ins