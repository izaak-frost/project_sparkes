# Deploy Project Sparkes to the existing OCI server

Target: `ubuntu@145.241.203.39` (`polymathic-projects-vnic`). This deploys the
backend pipelines and nutrition receiver alongside SafeWaters. The repository's
frontend source will also be on OCI if you clone the full repository; hosting
the Expo app is a separate step.

One daily job runs Garmin sleep/steps/weight, the existing sleep Google Sheets
update, Hevy workouts, and nutrition exports. The iPhone pushes nutrition using
the free Shortcut described in [the phone guide](../docs/APPLE_HEALTH.md).

## 1. Commit and push the prepared changes from Windows

Review the changes in this checkout, then commit and push them to your repository
using your usual Git app. The OCI clone needs these latest changes, not only
your earlier recovery commit. The Strong importer, Strava importer, and embedded
Strava library have been removed. A private local recovery archive, including
the embedded repository history, is in `project_helper/retired-strava.tar.gz`;
it is ignored by Git and should not be uploaded to OCI.

The old `garmin/tokens.json` file has been removed from Git tracking,
but your local copy remains. This does not remove it from earlier commits. The
new server login creates a private token directory rather than using that file.
Do not transfer the Windows virtual environment, the retired archive, or private
credentials through Git.

The repository address currently configured locally is:

```text
https://github.com/izaak-frost/project-sparkes.git
```

## 2. Connect and inspect the server

In your usual local terminal, connect with your normal key configuration:

```powershell
ssh ubuntu@145.241.203.39
```

If your key isn't configured in SSH, use your existing command with `-i` and
your key's path. On the server, run these read-only checks:

```bash
cat /etc/os-release
python3 --version
command -v git
systemctl is-active nginx caddy docker
```

Inactive/missing services are useful information, not a reason to stop. This
identifies the OS version, Python and SafeWaters' likely proxy. The instructions
below assume Ubuntu with Python **3.10 or newer**. If the server reports another
distribution or older Python, adjust installation first. Oracle's Linux SSH
guide describes the standard Ubuntu username and key connection:
[OCI connection guide](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/connect-to-linux-instance.htm).

## 3. Install dependencies and clone into a separate directory

On Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y git python3-venv
sudo install -d -o ubuntu -g ubuntu /opt/project-sparkes
git clone https://github.com/izaak-frost/project-sparkes.git /opt/project-sparkes
cd /opt/project-sparkes
python3 -m venv .venv-health
.venv-health/bin/python -m pip install -r requirements.txt
```

If the repository is private, use your existing GitHub SSH key/deploy-key setup
or authenticated Git workflow; don't embed a GitHub token into a command or
remote URL. If `/opt/project-sparkes` already contains a checkout, inspect its
changes and use `git pull --ff-only` there rather than cloning over it. No
submodule initialisation is needed after the cleanup.

Create a separate unprivileged service user. If it already exists, skip useradd:

```bash
sudo useradd --system --user-group --home-dir /opt/project-sparkes --shell /usr/sbin/nologin sparkes
sudo install -d -o sparkes -g sparkes -m 700 /opt/project-sparkes/data
sudo install -d -o sparkes -g sparkes -m 700 /opt/project-sparkes/data/health
sudo install -d -o sparkes -g sparkes -m 700 /opt/project-sparkes/support/credentials
cp .env.example .env
chmod 600 .env
```

The checkout and virtual environment can stay owned by `ubuntu`. Give `sparkes`
read access to the code/environment and ownership only of its private
configuration, credential files and generated data. Don't change ownership of
SafeWaters' directories.

## 4. Configure the private environment

On the server, edit:

```bash
nano /opt/project-sparkes/.env
```

Set:

| Setting | Value |
|---|---|
| `START_DATE` | First date of Garmin history you want, e.g. a real `YYYY-MM-DD` date |
| `COACHING_START_DATE` | Your actual coaching start date for the sleep sheet |
| `GARMIN_TOKENS` | `data/garmin/tokens` (a directory, not the retired token file) |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | `support/credentials/google-service-account.json` |
| `GOOGLE_SHEET_ID` | Existing sleep spreadsheet ID |
| `HEVY_API_KEY` | Key from your Hevy Pro developer settings |
| `HEALTH_UPLOAD_TOKEN` | A new random token generated below |
| `HEALTH_TIMEZONE` | `Europe/London` |

Generate the upload token with:

```bash
cd /opt/project-sparkes
.venv-health/bin/python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Paste it into `.env` and into the Shortcut's Authorization header later. Keep
`GARMIN_EMAIL` and `GARMIN_PASSWORD` empty if you prefer entering them only during
the initial interactive login. The scheduled job then relies on saved tokens.

Finish permissions after editing:

```bash
sudo chown sparkes:sparkes /opt/project-sparkes/.env
sudo chmod 600 /opt/project-sparkes/.env
```

Use this root `.env` for the full deployment. Move any settings from the retired
integration-specific environment file into it. The local Windows receiver uses
`support/credentials/local.env` for its upload token; that file is not needed on OCI.

## 5. Transfer the existing Google Sheets credential privately

In a **second local Windows terminal**, transfer the service-account file you
already use locally:

```powershell
scp "D:\git_projects\project_sparkes\support\credentials\google-service-account.json" ubuntu@145.241.203.39:~/sparkes-google-service-account.json
```

Use your existing `-i` key option if needed. Then in the server terminal:

```bash
chmod 600 ~/sparkes-google-service-account.json
sudo install -o sparkes -g sparkes -m 600 ~/sparkes-google-service-account.json /opt/project-sparkes/support/credentials/google-service-account.json
rm ~/sparkes-google-service-account.json
```

The sleep spreadsheet must be shared with that service account as an editor.
If it already works locally, use the same spreadsheet ID and credential file.
Check that no Windows drive paths remain in the server `.env`.

Optional: transfer existing local Garmin JSON history to avoid fetching it all
again. Files expected under `data/garmin` are `sleep_data.json`,
`daily_steps.json`, and `weights.json`.
Use `scp` to a private staging directory under the Ubuntu account and install
them into `data/` owned by `sparkes`, mode 600. Do not copy over
newer server data during later deployments. You can also rebuild these from
Garmin by starting with the desired `START_DATE`.

## 6. Bootstrap Garmin once and test each source

On the server:

```bash
cd /opt/project-sparkes
sudo -u sparkes .venv-health/bin/python main.py --garmin-login
```

Enter your Garmin email, password and MFA code if requested. The saved session
stays under `data/garmin/tokens`. This command intentionally needs your terminal;
the scheduled job never pauses for prompts. If Garmin requires a new session
later, rerun it. Login and Garmin data access use the community Garmin library,
so Garmin may change behaviour or rate-limit it.

Test collection before the spreadsheet write:

```bash
sudo -u sparkes .venv-health/bin/python main.py --only garmin --skip-sheets
```

Then test the sleep update and Hevy separately:

```bash
sudo -u sparkes .venv-health/bin/python main.py --only sleep
sudo -u sparkes .venv-health/bin/python -m support.sync --only hevy
```

The sleep command writes the existing `SLEEP DATA` worksheet. It now preserves
notes text in column K for every week, keyed by date, instead of deleting the
current week's rows. A local notes snapshot protects retries after a failed
refresh. If a `.pending.json` snapshot exists after failure, rerun before adding
new notes to the partly updated sheet. Column K is treated as free-text notes;
formulas stored there are preserved as their displayed text.

## 7. Start the upload receiver

Install its prepared service definition:

```bash
sudo cp /opt/project-sparkes/support/deploy/sparkes-health-receiver.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sparkes-health-receiver.service
sudo systemctl status sparkes-health-receiver.service --no-pager
```

It listens on `127.0.0.1:8765`. It is normal for an unauthenticated test to return
401:

```bash
curl -i -X POST http://127.0.0.1:8765/apple-health
```

Choose a dedicated hostname such as `health.YOUR-DOMAIN` and point its DNS to
`145.241.203.39`. Publish it through SafeWaters' existing HTTPS proxy. Check
whether that proxy is native or in Docker before editing its configuration.

For an existing native Caddy setup, the separate site block is:

```caddyfile
health.YOUR-DOMAIN {
    reverse_proxy 127.0.0.1:8765
}
```

For an existing native Nginx setup, the new hostname's HTTPS server block needs:

```nginx
location /apple-health {
    client_max_body_size 1m;
    proxy_pass http://127.0.0.1:8765;
    proxy_set_header Host $host;
    proxy_set_header Authorization $http_authorization;
}
```

Use the existing certificate workflow for this new hostname, validate the full
proxy configuration, then reload. These snippets are examples, not instructions
to replace SafeWaters' configuration. If the proxy runs in Docker, its localhost
is different from the host; use an appropriate host/network route rather than
blindly copying the loopback address. Keep 8765 private. Public HTTPS uses the
existing port 443 access. Tell me which proxy you have before applying this part
so we can choose the exact safe configuration.

Then build and run the [iPhone Shortcut](../docs/APPLE_HEALTH.md) with:

```text
URL: https://health.YOUR-DOMAIN/apple-health
Authorization: Bearer YOUR_UPLOAD_TOKEN
```

## 8. Enable the complete daily job

The supplied daily service runs `main.py`, including Garmin sleep and Sheets.
The timer runs at **10:17 Europe/London**, with up to three minutes of random
delay. Missed executions run after the server starts again.

```bash
sudo cp /opt/project-sparkes/support/deploy/sparkes-health-daily.service /etc/systemd/system/
sudo cp /opt/project-sparkes/support/deploy/sparkes-health-daily.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start sparkes-health-daily.service
sudo journalctl -u sparkes-health-daily.service -n 100 --no-pager
sudo systemctl enable --now sparkes-health-daily.timer
systemctl list-timers sparkes-health-daily.timer --all
```

The job can report failure before the first phone upload, even when Garmin and
Hevy succeed: absent/stale nutrition is explicitly flagged. Data is still saved.
Inspect `data/daily_status.json` for per-stage results. Do not also schedule the
old standalone health job or old Garmin job; one daily service handles both now.

## Data, logs and updates

Generated files under `/opt/project-sparkes/data`:

- `garmin/sleep_data.json`, `garmin/daily_steps.json`, `garmin/weights.json`
  and `garmin/tokens/` for Garmin.
- `daily_status.json` for the complete job's result.
- `publish/sleep_sheet_notes.json` for the notes snapshot.
- `health/health.sqlite3`, `health/daily_nutrition.json`,
  `health/daily_nutrition.csv`, and `health/sync_status.json` for nutrition.
- `hevy/hevy.sqlite3` and `hevy/hevy_workouts.json` for workouts.

The status file under `health` is separate from the complete job status.
Apple Health must arrive from the iPhone; OCI cannot fetch it from your Apple
account. Seven-day repeat uploads overwrite each nutrient/day safely. They
only correct dates within that window; older diary edits need an explicit
backfill. Don't replay an old saved total after a newer correction.

Keep backups of private configuration, Garmin sessions, Google credentials,
JSON data and the SQLite database. Use SQLite's online backup facility rather
than copying its live main file without its journal.

For later code updates, push your changes from Windows, then on OCI:

```bash
cd /opt/project-sparkes
git pull --ff-only
.venv-health/bin/python -m pip install -r requirements.txt
sudo systemctl restart sparkes-health-receiver.service
```

If service files change, copy them again and run `systemctl daemon-reload`.
When upgrading an installation with the old folder layout, stop both services
before updating, then run `.venv-health/bin/python support/scripts/migrate-layout.py`
from the repository root. Set `GARMIN_TOKENS=data/garmin/tokens` in `.env` and update
any explicit `HEALTH_DATA_DIR` to `data/health`. Copy the new service files from
`support/deploy/`, reload systemd, and restart. The migration preserves the
original shared database under `data/archive/previous-layout`.
Inspect logs with `journalctl -u sparkes-health-receiver.service` and
`journalctl -u sparkes-health-daily.service`. Generated data and `.env` are
ignored by Git and stay in place during normal pulls. The public FastAPI demo
API is not started as part of this deployment, because the receiver alone is
needed for phone uploads. Its source remains in the repository.
