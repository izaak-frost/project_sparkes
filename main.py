"""One daily OCI job for Garmin, Google Sheets, Hevy and pushed nutrition."""
import argparse
from datetime import date
import os
import sys

# Load the root environment before importing integrations that consult it.
from support.runtime import DATA_DIR
from support.config import load_settings
from support.storage import atomic_json, utc_now
from support.sync import export_data
from hevy_extract.workouts import sync_hevy


def run_daily(only="all", skip_sheets=False) -> int:
    settings = load_settings()
    stages = {}

    def stage(name, action):
        try:
            result = action()
            stages[name] = {"ok": True, "completed_at": utc_now()}
            print(f"Completed: {name}", flush=True)
            return True, result
        except Exception as exc:
            stages[name] = {"ok": False, "error": str(exc), "completed_at": utc_now()}
            print(f"Failed: {name}: {exc}", file=sys.stderr, flush=True)
            return False, None

    if only in ("all", "garmin", "sleep"):
        from garmin_extract.authentication import authenticate

        def login():
            value = os.environ.get("START_DATE")
            if not value:
                raise ValueError("Set START_DATE to the first day of Garmin history you need")
            date.fromisoformat(value)
            return authenticate(interactive=False)

        logged_in, client = stage("garmin_login", login)
        if logged_in:
            if only != "sleep":
                from garmin_extract.get_weight import get_weight_data
                from garmin_extract.get_steps import get_step_data
                stage("garmin_weight", lambda: get_weight_data(client))
                stage("garmin_steps", lambda: get_step_data(client))
            from garmin_extract.get_sleep_data import get_sleep_data
            sleep_ok, _ = stage("garmin_sleep", lambda: get_sleep_data(client))
            if sleep_ok and not skip_sheets:
                def export_sleep():
                    if not os.environ.get("COACHING_START_DATE"):
                        raise ValueError("Set COACHING_START_DATE for the sleep sheet")
                    from publish.export_sleep import export_sleep_to_gsheet
                    export_sleep_to_gsheet()
                stage("sleep_google_sheets", export_sleep)

    if only in ("all", "health"):
        stage("hevy", lambda: sync_hevy(settings))
        exported, health_status = stage("health_exports", lambda: export_data(settings))
        if exported:
            health_status["errors"] = [value["error"] for key, value in stages.items()
                                      if key in ("hevy", "health_exports") and not value["ok"]]
            atomic_json(settings.data_dir / "sync_status.json", health_status)
            warnings = health_status["nutrition_warnings"]
            stages["nutrition_readiness"] = {"ok": not warnings, "warnings": warnings}
            for warning in warnings:
                print(f"Nutrition warning: {warning}", file=sys.stderr, flush=True)
    if only in ("all", "garmin", "health") and not skip_sheets:
        from publish.export_macros import export_macros_to_gsheet
        stage("macros_google_sheets", export_macros_to_gsheet)
    success = all(value["ok"] for value in stages.values())
    atomic_json(DATA_DIR / "daily_status.json", {"completed_at": utc_now(), "ok": success, "stages": stages})
    return 0 if success else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--garmin-login", action="store_true", help="Save a Garmin session interactively, including MFA")
    parser.add_argument("--only", choices=("all", "garmin", "sleep", "health"), default="all")
    parser.add_argument("--skip-sheets", action="store_true", help="Run extracts without publishing to Google Sheets")
    args = parser.parse_args()
    try:
        if args.garmin_login:
            from garmin_extract.authentication import authenticate
            authenticate(interactive=True)
            return 0
        return run_daily(args.only, args.skip_sheets)
    except Exception as exc:
        print(f"Daily job failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
