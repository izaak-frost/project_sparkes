from pathlib import Path
import os
import requests

from ..sub_modules.file_utilities import save_to_json

OUTPUT_FILE = Path("data/strava_runs.json")
OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
RUN_TYPES = {"Run", "TrailRun", "VirtualRun"}


def _get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing requir-ed environment variable: {name}")

    cleaned = value.strip().strip('"').strip("'")
    if not cleaned:
        raise RuntimeError(f"Environment variable {name} is empty")

    return cleaned


def _get_credentials() -> tuple[str, str, str]:
    client_id = _get_required_env("STRAVA_CLIENT_ID")
    client_secret = _get_required_env("STRAVA_CLIENT_SECRET")
    refresh_token = _get_required_env("STRAVA_REFRESH_TOKEN")

    if not client_id.isdigit():
        raise ValueError(
            "STRAVA_CLIENT_ID must be your numeric Strava application ID, not the app name or an access token."
        )

    return client_id, client_secret, refresh_token


def refresh_access_token() -> dict:
    client_id, client_secret, refresh_token = _get_credentials()

    response = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )

    if not response.ok:
        raise RuntimeError(
            "Failed to refresh Strava access token. "
            f"Status {response.status_code}: {response.text}"
        )

    return response.json()


def fetch_run_activities(access_token: str) -> list[dict]:
    page = 1
    runs = []

    while True:
        response = requests.get(
            "https://www.strava.com/api/v3/athlete/activities",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"page": page, "per_page": 200},
            timeout=30,
        )

        if not response.ok:
            raise RuntimeError(
                "Failed to fetch Strava activities. "
                f"Status {response.status_code}: {response.text}"
            )

        activities = response.json()
        if not activities:
            break

        runs.extend(
            activity
            for activity in activities
            if activity.get("sport_type") in RUN_TYPES
        )
        page += 1

    return runs


def normalise_run_activity(activity: dict) -> dict:
    start_date_local = activity.get("start_date_local")

    return {
        "id": activity.get("id"),
        "name": activity.get("name"),
        "date": start_date_local.split("T")[0] if start_date_local else None,
        "start_date_local": start_date_local,
        "sport_type": activity.get("sport_type"),
        "distance_m": activity.get("distance"),
        "moving_time_s": activity.get("moving_time"),
        "elapsed_time_s": activity.get("elapsed_time"),
        "total_elevation_gain_m": activity.get("total_elevation_gain"),
        "average_speed_mps": activity.get("average_speed"),
        "max_speed_mps": activity.get("max_speed"),
    }


def get_run_activities() -> list[dict]:
    token_data = refresh_access_token()
    runs = fetch_run_activities(token_data["access_token"])
    normalised_runs = [normalise_run_activity(activity) for activity in runs]
    save_to_json(normalised_runs, "run activities", OUTPUT_FILE)
    print(f"    Found {len(normalised_runs)} run activities")
    return normalised_runs
