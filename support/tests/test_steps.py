from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from garmin_extract import get_steps as steps


class StepsTests(unittest.TestCase):
    def test_last_seven_days_are_fetched_even_if_all_dates_already_exist(self):
        existing=[{'date':f'2026-10-{day:02d}','steps':53} for day in range(1,9)]
        self.assertEqual(steps.get_missing_dates(existing,'2026-10-01','2026-10-08'),
                         [f'2026-10-{day:02d}' for day in range(2,9)])

    def test_recent_totals_replace_stale_counts_and_targeted_historical_day_is_repaired(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'daily_steps.json'
            old=[{'date':'2026-09-29','steps':53}, {'date':'2026-10-01','steps':4000}]
            old.extend({'date':f'2026-10-{day:02d}','steps':53} for day in range(2,9))
            output.write_text(json.dumps(old),encoding='utf-8')
            client=Mock()
            client.get_daily_steps.side_effect=[
                [{'calendarDate':'2026-09-29','totalSteps':7072}],
                [{'calendarDate':f'2026-10-{day:02d}','totalSteps':7000+day} for day in range(2,9)]]
            with patch.object(steps,'OUTPUT_FILE',output), patch.object(steps,'today',return_value=date(2026,10,8)), \
                 patch.dict(steps.os.environ,{'START_DATE':'2026-09-29'}):
                # The two intervening missing dates are fetched with September 29.
                result=steps.get_step_data(client,refresh_dates=['2026-09-29'])
            by_date={row['date']:row['steps'] for row in result}
            self.assertEqual(by_date['2026-09-29'],7072)
            self.assertEqual(by_date['2026-10-01'],4000)
            self.assertEqual([by_date[f'2026-10-{day:02d}'] for day in range(2,9)],list(range(7002,7009)))
            self.assertEqual(json.loads(output.read_text()),result)
