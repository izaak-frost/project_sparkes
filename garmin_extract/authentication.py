"""Reuse Garmin sessions daily; bootstrap MFA explicitly from a terminal."""
from getpass import getpass
import os

from garminconnect import Garmin, GarminConnectAuthenticationError, GarminConnectConnectionError, GarminConnectTooManyRequestsError

from support.runtime import GARMIN_DATA_DIR as DATA_DIR, configured_path


def authenticate(interactive: bool = False) -> Garmin:
    token_dir = configured_path("GARMIN_TOKENS", DATA_DIR / "tokens")
    if token_dir.is_file():
        raise RuntimeError("GARMIN_TOKENS must name a token directory. Set it to data/garmin/tokens and run python main.py --garmin-login")
    print("Logging in to Garmin Connect")
    client = Garmin()
    try:
        client.login(str(token_dir))
    except (FileNotFoundError, GarminConnectAuthenticationError):
        client = None
    except GarminConnectTooManyRequestsError:
        raise RuntimeError("Garmin refused the session request with HTTP 429. Stop retrying and allow the rate limit to clear; your saved session has been kept.") from None
    except GarminConnectConnectionError:
        raise RuntimeError("Garmin could not validate the saved session because the connection failed or access was blocked. Your saved session has been kept.") from None

    if client is None:
        email = os.environ.get("GARMIN_EMAIL")
        password = os.environ.get("GARMIN_PASSWORD")
        if interactive:
            email = email or input("Garmin email: ").strip()
            password = password or getpass("Garmin password: ")
        if not email or not password:
            raise RuntimeError("Garmin needs a saved session; run python main.py --garmin-login in an SSH terminal")

        def prompt_mfa():
            if not interactive:
                raise RuntimeError("Garmin requires MFA; run python main.py --garmin-login")
            return input("Garmin MFA one-time code: ").strip()

        client = Garmin(email=email, password=password, prompt_mfa=prompt_mfa)
        try:
            client.login()
        except GarminConnectTooManyRequestsError:
            raise RuntimeError("Garmin refused login with HTTP 429 (rate limiting). Stop retrying and allow the restriction to clear before another attempt. This does not establish that your password or MFA is wrong.") from None
        except GarminConnectConnectionError:
            raise RuntimeError("Garmin login could not connect or was blocked by Garmin's access protection. Stop repeated login attempts; check normal Garmin Connect access before trying again later.") from None
        except GarminConnectAuthenticationError:
            raise RuntimeError("Garmin rejected authentication. Check your credentials and complete any MFA prompt; no new session was saved.") from None
        except Exception:
            raise RuntimeError("Garmin login failed unexpectedly; no new session was saved. Check the preceding login messages before retrying.") from None
    token_dir.mkdir(parents=True, exist_ok=True)
    client.client.dump(str(token_dir))
    print("Garmin session saved")
    return client
