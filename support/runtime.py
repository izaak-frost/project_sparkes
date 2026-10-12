"""Stable server paths and configuration, independent of the caller's directory."""
from datetime import datetime
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env", override=False)


def configured_path(name: str, default: Path) -> Path:
    value = Path(os.environ.get(name) or default).expanduser()
    if not value.is_absolute():
        value = BASE_DIR / value
    return value.resolve()


DATA_DIR = configured_path("SPARKES_DATA_DIR", BASE_DIR / "data")

GARMIN_DATA_DIR = DATA_DIR / "garmin"
PUBLISH_DATA_DIR = DATA_DIR / "publish"


def today():
    return datetime.now(ZoneInfo(os.environ.get("HEALTH_TIMEZONE", "Europe/London"))).date()
