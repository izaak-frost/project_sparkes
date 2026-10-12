# Upload from your iPhone to this Windows PC

This PC's current LAN address is `192.168.0.28`. Use port `8765` for phone uploads
after starting the receiver with the command below. Use the same home network;
the PC may be connected
by Ethernet while the phone uses Wi-Fi. Guest Wi-Fi or wireless client isolation
can prevent the phone reaching the PC.

## Phone upload settings

The private token and the complete Authorization header are stored locally in
`data/local_phone_setup.txt`. The token configuration is in
`support/credentials/local.env`. Both are ignored by Git. Don't use the Hevy key
for phone uploads.

Your grouped JSON can use `calories_kcal`, `protein_g`, `carbs_g`, `fat_g` as its
keys. The familiar labels `Calories`, `Protein`, `Carbs`, `Fat` are also accepted
(case-insensitive). Each property contains a list of `{date, value}` objects.
Values are complete daily totals in kcal and grams; each nutrient/date must
occur only once in a batch. Missing days may be omitted. Re-sending a batch
replaces the stored totals without doubling them. The grouped route assumes
Nutracheck as the source; keep your Health samples filtered to that app.

In Shortcuts, after the action that produces your complete JSON text:

1. Add **URL** with `http://192.168.0.28:8765/apple-health`.
2. Add **Get Contents of URL**, selecting that URL and expanding its options.
3. Set Method to **POST**.
4. Add header **Authorization** with the full `Bearer ...` value from the local
   phone settings file. Include `Bearer` followed by a space and the token.
5. Add header **Content-Type** = `application/json`.
6. Set Request Body to **File** and select the existing JSON **text variable**
   as the file input. Shortcuts can pass content through its file conversion.
   If your variable is a Dictionary, first use **Get Text from Input** to
   convert it to JSON text and select that output. Send the entire JSON body;
   don't put it inside another JSON string property.
7. Add **Show Result** for the response from Get Contents of URL.

The File body option sends your already-built content. Apple documents JSON,
Form and File request bodies with variables in
[its request guide](https://support.apple.com/guide/shortcuts/request-your-first-api-apd58d46713f/ios).

For four nutrients with seven daily entries each, success returns:

```json
{"accepted_totals": 28}
```

If you omitted missing dates, the count is smaller. `401` means the upload token
doesn't match; `415` means Content-Type isn't application/json; `422` means the
JSON's fields, dates or values need correcting. A failed batch is not partially
saved. Permission prompts on the first run must be accepted on the iPhone.

## Windows firewall

The receiver runs, but this session did not have Windows administrator rights
to add an inbound firewall rule. Open **PowerShell as Administrator** on this PC
and run:

```powershell
New-NetFirewallRule -DisplayName 'Sparkes nutrition uploads (local)' -Direction Inbound -Action Allow -Protocol TCP -LocalAddress 192.168.0.28 -LocalPort 8765 -RemoteAddress LocalSubnet -Profile Any
```

This allows port 8765 only at the named local address, from the local subnet.
It doesn't change the network's Public/Private classification. Local testing
uses HTTP on your trusted home network; use HTTPS for the later OCI endpoint.
No router port forwarding is needed for this local setup.

To check basic phone connectivity, open
`http://192.168.0.28:8765/apple-health` in Safari on the iPhone. A
`Method Not Allowed` response is expected because Safari sends GET and uploads
use POST; it confirms you reached the service. A connection error suggests the
firewall, Wi-Fi isolation, an inactive server, or a changed PC address.

## Start the server from VS Code

Open the `D:\git_projects\project_sparkes` folder in VS Code. Choose
**Terminal â†’ New Terminal** and use a PowerShell terminal. From the repository
root, run:

```powershell
& .\support\scripts\start-local.ps1
```

Keep that terminal running. Press Ctrl+C to stop it. If a process is already
listening on 8765, stop that server before starting another. The PC must stay
awake. After editing the receiver code, stop and restart it. If your
PC's address changes, pass `-ListenAddress YOUR_NEW_ADDRESS` and update the phone
URL and firewall rule accordingly.

If PowerShell blocks the script, use this command from the same terminal:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\support\scripts\start-local.ps1
```

This applies the execution policy override to that process only.

## View the imported data

Uploads are stored immediately in the private SQLite database at
`data/health/health.sqlite3` by default. Each successful upload
also refreshes `daily_nutrition.csv` and `daily_nutrition.json` in that directory.
Both have one row per date with exactly these columns:

```text
date,calories,protein,carbs,fat
```

Calories are kcal; protein, carbs and fat are grams. Missing quantities are
blank in CSV and `null` in JSON; an explicitly uploaded zero stays zero. Days
are sorted oldest first. Your phone's grouped upload format stays the same.
In a SQLite viewer, select the `nutrition` table. This is the data source itself:
each date is a primary key, with `calories`, `protein`, `carbs`, and `fat` stored
as physical columns. Partial uploads update only the supplied columns; repeated
uploads replace totals rather than adding them. The old metric-row table is
automatically migrated transactionally on the next database access, and the old
`daily_nutrition` view is removed. Extra nutrients and source/receipt metadata
are retained separately in `nutrition_metadata` and exported to
`nutrition_details.json`.

To regenerate the exports from previously saved uploads without running Garmin
or Hevy, open another terminal and run:

```powershell
.\venv\Scripts\python.exe -m support.sync --only nutrition
```

Use `.venv-health\Scripts\python.exe` instead if that's your environment.
Inspect `data/health/daily_nutrition.csv` or `data/health/daily_nutrition.json`.
Before the first upload, or if
yesterday's data is absent, this command reports a warning and exits nonzero.
The local tests cover both grouped and daily upload formats. The first phone
test verifies your actual JSON and network connection.
