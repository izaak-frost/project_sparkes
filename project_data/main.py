from dotenv import load_dotenv
load_dotenv()

from garmin_sync.sub_modules.garmin_authentication import authenticate

from garmin_sync.extract_methods.get_weight import get_weight_data
from garmin_sync.extract_methods.get_steps import get_step_data
from garmin_sync.extract_methods.get_sleep_data import get_sleep_data
from garmin_sync.extract_methods.get_workouts import get_workout_data
from garmin_sync.extract_methods.get_strava_activities import get_run_activities

from garmin_sync.export_methods.export_sleep import export_sleep_to_gsheet

def main():
    garmin_connection = authenticate()

    if garmin_connection is None:
        raise RuntimeError("Failed to authenticate with Garmin.")

    #The python functions to collect Garmin data
    get_weight_data(garmin_connection)
    get_step_data(garmin_connection)
    get_sleep_data(garmin_connection)
    get_workout_data()
    #get_run_activities()
    
    print(f"\n[INFO] Garmin Data extracted successfully and updated.")

    print(f"[INFO] Updating Google Sheets document...")
    export_sleep_to_gsheet()

    print(f"\n[INFO] Job completed, data extracted and exported.\n")
if __name__ == "__main__":
    main()