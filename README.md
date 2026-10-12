# Project Sparkes

A personal fitness data platform with daily ingestion on an OCI Linux server.

Current integrations:

- **Garmin Connect:** sleep, daily steps and weight.
- **Google Sheets:** the existing `SLEEP DATA` worksheet, including coaching-week
  summaries and preserved notes, plus weight, nutrition and steps in the
  `MACROS & WEIGHT` diary.
- **Hevy Pro:** complete workouts, exercises, sets, reps and weights.
- **Nutracheck via Apple Health:** daily calories and nutrients pushed by a free
  iPhone Shortcut.

The daily job stores JSON datasets and SQLite workout/nutrition records. An
authenticated receiver accepts phone uploads independently of that job.

## Deploy to OCI

Follow [the server walkthrough](support/deploy/OCI.md) for
`ubuntu@145.241.203.39`, alongside the existing SafeWaters deployment.
It covers uploading code and credentials, Garmin MFA setup, manual checks,
the nutrition upload receiver and daily scheduling.

Follow [the iPhone Shortcut guide](support/docs/APPLE_HEALTH.md) to send
nutrition. The phone must push Apple Health data; the OCI server cannot pull
it directly. No paid export app is needed for the Shortcut approach.

## Local backend setup

Use Python 3.10 or newer:

```bash
python -m venv .venv-health
```

Activate your environment, then:

```bash
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env`, fill in the values,
then save a Garmin session interactively:

```bash
python main.py --garmin-login
```

Run the combined daily job:

```bash
python main.py
```

Other useful commands:

```bash
python main.py --only sleep
python main.py --only garmin --skip-sheets
python main.py --only health
python -m support.sync --only hevy
python -m publish.export_macros --dry-run
python -m publish.export_macros
python -m unittest discover -s support/tests -v
```

Each source is reported separately in `data/daily_status.json`.
A failed source does not prevent independent sources from updating. The job
exits nonzero if a source fails or nutrition is absent/stale, while retaining
successfully collected data.

The macros publisher matches dates in column B from row 39. It imports Garmin
weight and steps plus Apple Health calories, protein, carbs and fat, retaining
manual values wherever a source is missing. Weekly averages are formulas in
columns C, J and L. Column M is reserved for manual comments; notes formatting
uses N:T and the complete weekly template spans A:Z. Zero weight and nutrition quantities are shown as blanks
and excluded from averages; a zero step count remains valid. A complete blank
week follows the current Tuesday–Monday
week, using the existing diary's calendar and formatting. Notes, coaching
changes and the top dashboard's input cells remain untouched. A pre-update snapshot is kept
in `data/publish/macros_before_publish.json`. `--skip-sheets` skips both publishers.

Each macros refresh also updates the two existing dashboard charts: average daily
steps by Tuesday–Monday week, and daily calories/body weight on separate axes.
Both cover the rolling twelve months ending on the refresh date (inclusive).
Partial weeks use only dates inside that window; missing readings stay blank.
The formulas live in the hidden `_Sparkes chart data` tab and follow diary edits.
Calories connect only across consecutive recorded days. A separate plotted
weight trend linearly joins recorded weigh-ins, without filling the diary's
missing weights or extrapolating beyond the first/last recorded weigh-in.
The publisher updates chart source data without rewriting chart specifications:
the REST API drops manually configured right-axis bounds even when copying the
saved specification. To update native chart dates while preserving styling,
paste `publish/refresh_chart_dates.gs` into the spreadsheet's Extensions > Apps
Script editor, then run `installSparkesChartRefresh` once and authorise it.
The native refresh runs hourly and updates date ranges/subtitles. It restores
the captured calorie bounds 1,500–3,000 and weight bounds 95–103 if missing.

Garmin steps re-fetch today and the previous six days on every run, replacing
earlier totals for those dates. Missing older dates are fetched as before.

## Files

```text
project_sparkes/
  main.py                  Combined daily entry point
  requirements.txt         Backend dependencies
  .env.example             Configuration template
  garmin_extract/          Garmin authentication, sleep, steps and weight
  health_extract/          Apple Health upload receiver and nutrition ingestion
  hevy_extract/            Hevy workout extraction
  publish/                 Google Sheets sleep publishing
  support/                 Helpers, configuration and setup
    scripts/               Local server startup and data migration
    docs/                  iPhone Shortcut and local setup guides
    deploy/                OCI services and server walkthrough
    tests/                 Pipeline and publishing checks
    credentials/           Private keys and local upload token (ignored)
  data/
    garmin/                Sleep, steps, weight and saved sessions
    health/                Nutrition database, CSV and JSON
    hevy/                  Workout database and JSON
    publish/               Saved Sheets notes and retry state
    archive/               Retired files and original migration backups
```

The unused demo API is archived locally under `data/archive/unused-code`.

Keep environment files, Google credentials, Garmin sessions, and generated
personal data out of Git. Back up the server's configuration and data separately
from the source repository.

Start the local receiver from a PowerShell terminal at the repository root:

```powershell
.\support\scripts\start-local.ps1
```

See [the local guide](support/docs/LOCAL.md) for upload settings. When updating
an existing installation with the old layout, stop its receiver and daily job,
then run `python support/scripts/migrate-layout.py` from the repository root before restarting.
The migration retains the original shared database under `data/archive`.
