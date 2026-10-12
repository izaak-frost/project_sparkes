from dataclasses import dataclass
from pathlib import Path
import os
import math
from zoneinfo import ZoneInfo

from support.runtime import DATA_DIR, configured_path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    hevy_api_key: str = ""
    upload_token: str = ""
    timezone: str = "Europe/London"
    max_upload_age_hours: float = 48

    hevy_data_dir: Path | None = None

    @property
    def hevy_directory(self) -> Path:
        return self.hevy_data_dir or self.data_dir / "hevy"

    @property
    def hevy_database(self) -> Path:
        return self.hevy_directory / "hevy.sqlite3"

    @property
    def database(self) -> Path:
        return self.data_dir / "health.sqlite3"


def load_settings() -> Settings:
    default_data = DATA_DIR / "health"
    zone = os.environ.get("HEALTH_TIMEZONE", "Europe/London")
    ZoneInfo(zone)
    max_age = float(os.environ.get("HEALTH_MAX_UPLOAD_AGE_HOURS", "48"))
    if not math.isfinite(max_age) or max_age <= 0:
        raise ValueError("HEALTH_MAX_UPLOAD_AGE_HOURS must be positive and finite")
    return Settings(
        hevy_data_dir=configured_path("HEVY_DATA_DIR", DATA_DIR / "hevy"),
        data_dir=configured_path("HEALTH_DATA_DIR", default_data),
        hevy_api_key=os.environ.get("HEVY_API_KEY", "").strip(),
        upload_token=os.environ.get("HEALTH_UPLOAD_TOKEN", "").strip(),
        timezone=zone,
        max_upload_age_hours=max_age,
    )


NUTRITION_UNITS = {
    "calories_kcal": "kcal", "protein_g": "g", "carbs_g": "g", "fat_g": "g",
    "saturated_fat_g": "g", "sugar_g": "g", "fibre_g": "g",
    "sodium_mg": "mg", "water_ml": "ml",
}
GROUPED_ALIASES = {
    "calories": "calories_kcal", "protein": "protein_g",
    "carbs": "carbs_g", "carbohydrates": "carbs_g", "fat": "fat_g",
}
DAILY_COLUMNS = {"calories": "calories_kcal", "protein": "protein_g",
                 "carbs": "carbs_g", "fat": "fat_g"}

