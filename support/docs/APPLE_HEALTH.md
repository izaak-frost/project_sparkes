# Push Nutracheck nutrition with free Apple Shortcuts

Already have grouped JSON? Use [the local upload guide](LOCAL.md) to send all
nutrients and dates from one Shortcuts action. The receiver accepts both grouped
JSON and the individual-day format described below.

For the complete OCI deployment, including daily Garmin sleep, Google Sheets,
Hevy and this upload receiver, follow [the OCI walkthrough](../deploy/OCI.md).
The server files are ready locally; no live account or OCI connection has been
established yet. Use .env for the complete deployment.

## Enable nutrition sharing on the iPhone

1. Enable Nutracheck's Apple Health integration and its permission to **write**
   calories and your chosen nutrients.
2. In Health, inspect yesterday's **Dietary Energy** and **Protein** under
   Nutrition. Use Show All Data to check values and the source app. Nutracheck
   may appear under its app name **Calorie Counter +**.
3. Run the shortcut manually and grant Shortcuts permission to **read** those
   categories when prompted.

Nutracheck documents sending calories and nutrients to Health. This route
provides daily nutrient totals, not food names or a meal-by-meal diary.
[Nutracheck support](https://www.nutracheck.co.uk/MemberSupport/FAQs?key=3vd0wHxUSIk8mequAcaGUq)

## Build the free iPhone shortcut

Create a shortcut called **Send nutrition to Sparkes**. The following is an
action recipe to build in the Shortcuts editor, not an installed or signed
shortcut file. Action labels and Health category names can vary by iOS version.

Start with yesterday and calories only. Once that matches Health and successfully
uploads, duplicate the nutrient block and expand the repeat to seven days.

### Date loop

1. Add **Current Date**.
2. Add **Adjust Date**, choose **Get Start of Day**, and save it as `TodayStart`.
3. Add **Repeat**, set to **7**. (Use **1** for the first test.)
4. Inside Repeat: **Adjust Date**, subtract `Repeat Index` **days** from
   `TodayStart`. Save as `DayStart`. Use calendar days, not 24-hour intervals,
   so daylight saving changes are handled correctly.
5. **Adjust Date**: add 1 day to `DayStart`; then subtract 1 second. Save as
   `DayLastSecond`.
6. **Format Date** on `DayStart`, Custom format `yyyy-MM-dd`. Save as `DayText`.
   Use lowercase `yyyy`, not week-year `YYYY`.

The phone's day boundary must match Europe/London. If you travel across time
zones, pause this automation or adjust the date boundaries before sending a
backfill; the server cannot infer a different timezone from a date-only payload.

### Nutrient block (repeat this block for each nutrient)

1. **Find Health Samples**: select the nutrient Type; filter Start Date between
   `DayStart` and `DayLastSecond`. Turn **Limit OFF** so every sample for that
   day is included. Restrict **Source** to the Nutracheck/Calorie Counter app if
   the action exposes that filter. Use the actual source name shown in Health.
2. If your iOS version doesn't expose source filtering, only enable Nutracheck
   to write these nutrition categories to Health, and check that the dates you
   export have no entries from another app. Changing permissions doesn't remove
   historical entries. Do not sum several apps that log the same food.
3. **Count** the found samples. **If Count is greater than 0**, get their
   **Value** using **Get Details of Health Samples** and use **Calculate
   Statistics â†’ Sum** on the numeric values.
4. Check the units in the Health action/output against the table; convert before
   summing if necessary. Save the sum as `NutrientTotal` and add the upload
   actions below **inside this If**, using this nutrient's JSON key.
5. If Count is zero, skip this nutrient's upload. No samples may mean missing
   permissions or an unsynced diary; it does not establish zero intake.

| Health nutrient | JSON key | Required units |
|---|---|---|
| Dietary Energy / calories consumed | `calories_kcal` | kcal |
| Protein | `protein_g` | g |
| Carbohydrates | `carbs_g` | g |
| Total Fat | `fat_g` | g |
| Saturated Fat | `saturated_fat_g` | g |
| Dietary Sugar | `sugar_g` | g |
| Fibre / Fiber | `fibre_g` | g |
| Sodium | `sodium_mg` | mg |
| Dietary Water | `water_ml` | mL |

Start with calories, protein, carbs and fat. Only add other fields if Nutracheck
actually writes them to your Health store. Sodium is not salt; do not send a
salt value under `sodium_mg`. If values are in kJ, divide by 4.184 for kcal;
multiply sodium in grams by 1000 for mg; multiply litres by 1000 for mL.

### Upload actions inside each nutrient block

Add these after Calculate Statistics, inside the If checking Count > 0:

1. Add **URL**: `https://health.YOUR-DOMAIN/apple-health`.
2. **Get Contents of URL**: method **POST**. Set header **Authorization** to
   `Bearer YOUR_UPLOAD_TOKEN`, using the token from the receiver's `.env`.
   Set **Content-Type** to `application/json`.
3. Set Request Body to **JSON** and add these three fields:
   - `date` (**Text**) = the `DayText` variable.
   - `source` (**Text**) = `nutracheck`.
   - `calories_kcal` (**Number**) = `NutrientTotal` for the calorie block.
     Use `protein_g`, `carbs_g`, etc. instead when duplicating the block for
     another nutrient. Don't send a JSON string inside another key.
4. For the first manual test, add **Show Result** for the response; expect
   `{"accepted_totals":1}` for each nutrient upload. Remove Show
   Result before making the automation run unattended.

This simple recipe sends one request per nutrient per day (28 requests for seven
days and four nutrients). If a request fails, rerun the shortcut: previously
accepted totals won't be doubled. You can later combine the found totals into
one daily request; the receiver also accepts a dictionary like this:

```json
{
  "date": "2026-10-07",
  "source": "nutracheck",
  "calories_kcal": 2200,
  "protein_g": 160,
  "carbs_g": 230,
  "fat_g": 70
}
```

Use actual sums, not the example numbers. Totals can be uploaded independently
(e.g. a dictionary containing only `protein_g`) and other stored nutrients will
be retained. Never send an individual sample as if it were the day's total.

Apple documents [finding Health samples](https://support.apple.com/en-gb/guide/shortcuts/apd3c845e881/ios)
and [sending JSON requests](https://support.apple.com/guide/shortcuts/request-your-first-api-apd58d46713f/ios).
The particular action recipe above still needs its first check on your phone;
the local tests exercise the receiving side, not your iPhone's Health permissions.

### Automate it

Run manually once with the phone unlocked. Compare the uploaded calories/macros
to Health before relying on the pipeline. In **Shortcuts â†’ Automation**, add
**App â†’ Nutracheck/Calorie Counter â†’ Is Closed**, choose **Run Immediately**, and
run **Send nutrition to Sparkes**. This generally runs while you're using the
phone and after you've finished the diary. A **Time of Day** trigger can also
run the shortcut, but Health access while locked is restricted; a scheduled
trigger does not guarantee a successful read. Keep a Home Screen shortcut for
manual retries. Re-running the last seven days picks up corrections.
[Apple automation guide](https://support.apple.com/guide/shortcuts/add-automations-apdfbdbd7123/ios)


## Check the result

Run the server daily job (`python main.py`) after the first upload. Check
`data/health/daily_nutrition.json` against Apple Health. The receiver refreshes
this file and `daily_nutrition.csv` after each successful upload. Both contain
one row per day with `date, calories, protein, carbs, fat` (kcal and grams).
Missing quantities are JSON nulls or CSV blanks. SQLite's `nutrition` table
stores these five columns directly, with one row per date. Existing metric-row
databases are migrated automatically in a transaction; the old view is removed.
`nutrition_metadata` retains extra nutrients and source/receipt details, which
are exported in `nutrition_details.json`. Repeated uploads
replace each nutrient/date rather than adding another copy. Missing fields
retain earlier values; missing samples must not be sent as zero. If every
sample for a previously uploaded day is deleted, explicitly correct that day
on the server or send a verified zero. The latest received total wins.

The endpoint checks the private token, allowed fields, date and numeric values.
It cannot verify that the shortcut used the correct source, units or a complete
day; verify those on the phone. The receiver runs continuously on OCI; the
combined processing job runs daily.

To test the receiver and pipeline locally from the repository root:

```bash
python -m unittest discover -s support/tests -v
```
