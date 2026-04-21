from pathlib import Path
from collections import OrderedDict
from datetime import datetime
from typing import Any
import argparse
import csv

from ..sub_modules.file_utilities import save_to_json


DEFAULT_SOURCE_DIR = Path(r"D:\OneDrive\Important Documents\Fitness and Health")
OUTPUT_FILE = Path("data/workouts.json")
OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert a Strong workout CSV export into grouped JSON data. "
            "By default the newest CSV in the Strong export folder is used."
        )
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help=f"Directory containing Strong CSV exports. Default: {DEFAULT_SOURCE_DIR}",
    )
    parser.add_argument(
        "--input-file",
        type=Path,
        help="Optional explicit CSV file path. Overrides --source-dir.",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        default=OUTPUT_FILE,
        help=f"Destination JSON file. Default: {OUTPUT_FILE}",
    )
    return parser.parse_args()


def find_latest_csv(source_dir: Path) -> Path:
    if not source_dir.exists():
        raise FileNotFoundError(f"Strong export directory was not found: {source_dir}")

    csv_files = sorted(
        source_dir.glob("*.csv"),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )

    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in: {source_dir}")

    return csv_files[0]


def parse_number(value: str) -> int | float | None:
    cleaned = value.strip()
    if not cleaned:
        return None

    if "." in cleaned:
        number = float(cleaned)
        return int(number) if number.is_integer() else number

    return int(cleaned)


def parse_strong_datetime(value: str) -> datetime:
    cleaned = value.strip()
    supported_formats = (
        "%d/%m/%Y %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    )

    for date_format in supported_formats:
        try:
            return datetime.strptime(cleaned, date_format)
        except ValueError:
            continue

    raise ValueError(f"Unsupported Strong date format: {value!r}")


def read_strong_csv(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as file_handle:
        reader = csv.DictReader(file_handle)
        required_columns = {
            "Date",
            "Workout Name",
            "Duration",
            "Exercise Name",
            "Set Order",
            "Weight",
            "Reps",
            "Distance",
            "Seconds",
            "RPE",
        }

        missing_columns = required_columns.difference(reader.fieldnames or [])
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"CSV is missing required columns: {missing}")

        return list(reader)


def transform_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    workouts_by_timestamp: "OrderedDict[str, dict[str, Any]]" = OrderedDict()

    for row in rows:
        timestamp = row["Date"].strip()
        if not timestamp:
            continue

        workout_datetime = parse_strong_datetime(timestamp)

        workout = workouts_by_timestamp.setdefault(
            timestamp,
            {
                "date": workout_datetime.date().isoformat(),
                "workout_name": row["Workout Name"].strip(),
                "duration": row["Duration"].strip(),
                "exercises": OrderedDict(),
            },
        )

        exercise_name = row["Exercise Name"].strip()
        exercise = workout["exercises"].setdefault(
            exercise_name,
            {
                "exercise_name": exercise_name,
                "sets": [],
            },
        )

        exercise["sets"].append(
            {
                "set_order": parse_number(row["Set Order"]),
                "weight": parse_number(row["Weight"]),
                "reps": parse_number(row["Reps"]),
                "distance": parse_number(row["Distance"]),
                "seconds": parse_number(row["Seconds"]),
                "rpe": parse_number(row["RPE"]),
            }
        )

    grouped_by_date: "OrderedDict[str, dict[str, Any]]" = OrderedDict()

    for workout in workouts_by_timestamp.values():
        exercise_map = workout.pop("exercises")
        workout["exercises"] = list(exercise_map.values())

        day_bucket = grouped_by_date.setdefault(
            workout["date"],
            {
                "date": workout["date"],
                "workouts": [],
            },
        )
        day_bucket["workouts"].append(workout)

    return list(grouped_by_date.values())


def raw_workout_data(input_file: Path | None = None, source_dir: Path = DEFAULT_SOURCE_DIR) -> list[dict[str, Any]]:
    csv_path = input_file or find_latest_csv(source_dir)
    print(f"\n    Fetching workouts from {csv_path}...")

    rows = read_strong_csv(csv_path)
    return transform_rows(rows)


def get_workout_data():
    args = parse_args()
    workouts = raw_workout_data(input_file=args.input_file, source_dir=args.source_dir)
    save_to_json(workouts, "workouts", args.output_file)