"""Fetch a complete Hevy workout snapshot without replacing data on failed fetches."""
import json
import random
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from support.config import Settings
from support.storage import hevy_database as database, set_state, utc_now, atomic_json

def request_hevy(key: str, page: int) -> dict:
    request = Request(
        f"https://api.hevyapp.com/v1/workouts?page={page}&pageSize=10",
        headers={"api-key": key, "Accept": "application/json"},
    )
    for attempt in range(4):
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.load(response)
            if not isinstance(payload, dict):
                raise ValueError("Hevy returned an invalid response")
            return payload
        except HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 3:
                # Do not log response bodies or request headers containing the key.
                raise RuntimeError(f"Hevy request failed with HTTP {exc.code}") from None
            retry_after = exc.headers.get("Retry-After", "")
            delay = min(float(retry_after), 60) if retry_after.isdigit() else 2 ** attempt
            time.sleep(delay + random.uniform(0, 1))
        except (URLError, TimeoutError):
            if attempt == 3:
                raise RuntimeError("Hevy connection failed after four attempts") from None
            time.sleep(2 ** attempt + random.uniform(0, 1))
    raise RuntimeError("Hevy request failed")


def sync_hevy(settings: Settings, fetch=request_hevy) -> int:
    if not settings.hevy_api_key:
        raise ValueError("Set HEVY_API_KEY in .env")
    workouts = {}
    expected_pages = None
    # Fetch everything before replacing stored data. A failed page preserves history.
    for page in range(1, 10001):
        payload = fetch(settings.hevy_api_key, page)
        page_count = payload.get("page_count")
        if (type(page_count) is not int or page_count < 0
                or page_count > 10000 or payload.get("page") != page):
            raise ValueError("Invalid Hevy pagination metadata")
        if expected_pages is None:
            expected_pages = page_count
        elif expected_pages != page_count:
            raise ValueError("Hevy history changed during pagination; retry the job")
        rows = payload.get("workouts")
        if not isinstance(rows, list) or len(rows) > 10:
            raise ValueError("Invalid Hevy workouts page")
        if page_count == 0 and rows:
            raise ValueError("Invalid empty Hevy history")
        if page < page_count and len(rows) != 10:
            raise ValueError("Incomplete Hevy page; previous history retained")
        if page_count > 1 and not rows:
            raise ValueError("Empty Hevy page; previous history retained")
        for workout in rows:
            if (not isinstance(workout, dict) or not isinstance(workout.get("id"), str)
                    or not workout["id"] or not isinstance(workout.get("exercises"), list)):
                raise ValueError("Invalid Hevy workout")
            if workout["id"] in workouts:
                raise ValueError("Hevy returned duplicate IDs; retry the job")
            workouts[workout["id"]] = workout
        if page >= page_count:
            break
    with database(settings) as conn:
        conn.execute("DELETE FROM workouts")
        conn.executemany("INSERT INTO workouts VALUES (?, ?)",
                         [(key, json.dumps(value, allow_nan=False)) for key, value in workouts.items()])
        set_state(conn, "hevy_synced_at", utc_now())
    return len(workouts)


def export_hevy(settings: Settings) -> dict:
    with database(settings) as conn:
        workouts = [json.loads(row[0]) for row in conn.execute("SELECT payload FROM workouts ORDER BY id")]
        state = dict(conn.execute("SELECT name, value FROM sync_state"))
    atomic_json(settings.hevy_directory / "hevy_workouts.json", workouts)
    return {"workout_count": len(workouts), **state}
