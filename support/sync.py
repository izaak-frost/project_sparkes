import argparse
import json
import sqlite3
import sys
from zoneinfo import ZoneInfoNotFoundError

from support.config import load_settings
from support.storage import atomic_json
from health_extract.nutrition import export_nutrition, ingest_nutrition
from hevy_extract.workouts import export_hevy, sync_hevy


def export_data(settings):
    return {**export_nutrition(settings), **export_hevy(settings)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily Hevy and Apple Health nutrition pipeline")
    parser.add_argument("--only", choices=("all", "hevy", "nutrition"), default="all")
    parser.add_argument("--import-health", metavar="JSON_FILE", help="Import a daily totals JSON file in the documented Shortcuts format")
    args = parser.parse_args()
    try:
        settings = load_settings()
        errors = []
        if args.only in ("all", "nutrition") and args.import_health:
            try:
                with open(args.import_health, encoding="utf-8-sig") as source:
                    count = ingest_nutrition(settings, json.load(source))
                print(f"Imported {count} daily nutrition totals")
            except (OSError, ValueError) as exc:
                errors.append(f"Nutrition import: {exc}")
        if args.only in ("all", "hevy"):
            try:
                print(f"Synced {sync_hevy(settings)} Hevy workouts")
            except (OSError, ValueError, RuntimeError) as exc:
                errors.append(f"Hevy sync: {exc}")
        status = export_data(settings)
        status["errors"] = errors
        atomic_json(settings.data_dir / "sync_status.json", status)
        for error in errors:
            print(error, file=sys.stderr)
        warnings = status["nutrition_warnings"] if args.only != "hevy" else []
        for warning in warnings:
            print(f"WARNING: {warning}", file=sys.stderr)
        print(f"Health exports: {settings.data_dir}; Hevy exports: {settings.hevy_directory}")
        return 1 if errors or warnings else 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error, ZoneInfoNotFoundError) as exc:
        print(f"Pipeline failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
