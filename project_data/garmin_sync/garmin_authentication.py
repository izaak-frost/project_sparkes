import os
import sys
import requests

from getpass import getpass
from dotenv import load_dotenv
from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

load_dotenv()

EMAIL = os.getenv("GARMIN_EMAIL")
PASSWORD = os.getenv("GARMIN_PASSWORD")
GARMIN_TOKENS = os.getenv("GARMIN_TOKENS", "garmin_tokens.json")


def get_mfa() -> str:
    """Get MFA token."""
    return input("\nMFA one-time passcode: ")


def authenticate() -> Garmin | None:
    """Authenticate to Garmin Connect."""
    print("\n[INFO] Logging in to Garmin Connect...")

    email = EMAIL
    password = PASSWORD

    try:
        print(f"[INFO] Attempting login using stored tokens from: '{GARMIN_TOKENS}'")
        garmin_connection = Garmin()
        garmin_connection.login(GARMIN_TOKENS)
        print("[INFO] Successfully logged in using stored tokens.\n")
        return garmin_connection

    except GarminConnectTooManyRequestsError as err:
        print(f"\n❌ Too many requests: {err}")
        sys.exit(1)

    except (
        FileNotFoundError,
        GarminConnectAuthenticationError,
        GarminConnectConnectionError,
    ):
        print("[WARN] No valid tokens found. Falling back to credential login.")

    while True:
        try:
            if not email or not password:
                email = input("Email address: ").strip()
                password = getpass("Password: ")

            print("\n[INFO] Logging in with credentials...")
            garmin_connection = Garmin(
                email=email,
                password=password,
                is_cn=False,
                return_on_mfa=True,
            )

            result1, result2 = garmin_connection.login()

            if result1 == "needs_mfa":
                print("[INFO] Multi-factor authentication required")
                mfa_code = get_mfa()
                print("[INFO] Submitting MFA code...")

                try:
                    garmin_connection.resume_login(result2, mfa_code)
                    print("[INFO] MFA authentication successful.")

                except GarminConnectTooManyRequestsError:
                    print("[ERR] Too many MFA attempts. Please wait before retrying.")
                    sys.exit(1)

                except GarminConnectAuthenticationError as mfa_error:
                    error_str = str(mfa_error)
                    if "401" in error_str or "403" in error_str:
                        print("[WARN] Invalid MFA code. Please try again.")
                        continue

                    print(f"[ERR] MFA authentication failed: {mfa_error}")
                    sys.exit(1)

            garmin_connection.client.dump(GARMIN_TOKENS)
            print(f"[INFO] Login successful. Tokens saved to: {GARMIN_TOKENS}\n")
            return garmin_connection

        except GarminConnectTooManyRequestsError as err:
            print(f"\n❌ Too many requests: {err}")
            sys.exit(1)

        except GarminConnectAuthenticationError as err:
            print(f"\n❌ Authentication failed: {err}")
            print("Please check your username and password and try again.")
            email = None
            password = None
            continue

        except (
            FileNotFoundError,
            GarminConnectConnectionError,
            requests.exceptions.HTTPError,
        ) as err:
            print(f"\n❌ Connection error: {err}")
            print("Please check your internet connection and try again.")
            return None

        except KeyboardInterrupt:
            print("\nLogin cancelled by user.")
            return None