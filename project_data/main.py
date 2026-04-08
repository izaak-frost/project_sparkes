from dotenv import load_dotenv
load_dotenv()

from garmin_sync.sub_modules.garmin_authentication import authenticate

from garmin_sync.extract.get_weight import get_weight_data
from garmin_sync.extract.get_steps import get_step_data
from garmin_sync.extract.get_sleep_data import get_sleep_data

def main():
    garmin_connection = authenticate()

    if garmin_connection is None:
        raise RuntimeError("Failed to authenticate with Garmin.")

    #The python functions to collect Garmin data
    weight_data = get_weight_data(garmin_connection)
    step_data = get_step_data(garmin_connection)
    sleep_data = get_sleep_data(garmin_connection)

if __name__ == "__main__":
    main()