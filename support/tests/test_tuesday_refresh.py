from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import main
from garmin_extract import get_steps as steps, get_sleep_data as sleep, get_weight as weight
from support.config import Settings


class TuesdayRefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.tuesday = date(2026, 10, 13)
        self.week = [(self.tuesday - timedelta(days=offset)).isoformat() for offset in range(7, 0, -1)]

    def test_tuesday_fetches_previous_tuesday_steps_even_though_it_is_cached(self):
        output = self.root / 'steps.json'
        output.write_text(json.dumps([{'date': f'2026-10-{day:02d}', 'steps': 100}
                                     for day in range(1, 14)]))
        client = Mock()
        client.get_daily_steps.return_value = [
            {'calendarDate': f'2026-10-{day:02d}', 'totalSteps': 1000 + day} for day in range(6, 14)]
        with patch.object(steps, 'OUTPUT_FILE', output), patch.object(steps, 'today', return_value=self.tuesday), \
             patch.dict(steps.os.environ, {'START_DATE': '2026-10-01'}):
            readings = steps.get_step_data(client, refresh_dates=self.week)
        client.get_daily_steps.assert_called_once_with('2026-10-06', '2026-10-13')
        by_date = {row['date']: row['steps'] for row in readings}
        self.assertEqual(by_date['2026-10-06'], 1006)
        self.assertEqual(by_date['2026-10-12'], 1012)
        self.assertEqual(by_date['2026-10-05'], 100)

    def test_corrected_sleep_replaces_the_entire_cached_week_without_losing_older_history(self):
        output = self.root / 'sleep.json'
        output.write_text(json.dumps([{'calendarDate': f'2026-10-{day:02d}', 'sleepTime': '06:00'}
                                     for day in range(1, 14)]))
        client = Mock()
        client.get_sleep_data.side_effect = lambda day: {'dailySleepDTO': {
            'calendarDate': day, 'sleepTimeSeconds': 28800}}
        with patch.object(sleep, 'OUTPUT_FILE', output), patch.object(sleep, 'today', return_value=self.tuesday), \
             patch.dict(sleep.os.environ, {'START_DATE': '2026-10-01', 'SLEEP_REFRESH_DAYS': '3'}):
            readings = sleep.get_sleep_data(client, refresh_dates=self.week)
        self.assertEqual([call.args[0] for call in client.get_sleep_data.call_args_list],
                         self.week + ['2026-10-13'])
        by_date = {row['calendarDate']: row['sleepTime'] for row in readings}
        self.assertTrue(all(by_date[day] == '08:00' for day in self.week))
        self.assertEqual(by_date['2026-10-05'], '06:00')

    def test_weight_already_refetches_and_replaces_previous_week(self):
        output = self.root / 'weight.json'
        output.write_text('[{"date":"2026-10-06","weight":100}]')
        client = Mock()
        client.get_weigh_ins.return_value = {'dailyWeightSummaries': [
            {'summaryDate': '2026-10-06', 'latestWeight': {'weight': 98500}}]}
        with patch.object(weight, 'OUTPUT_FILE', output), patch.object(weight, 'today', return_value=self.tuesday), \
             patch.dict(weight.os.environ, {'START_DATE': '2026-10-01'}):
            readings = weight.get_weight_data(client)
        client.get_weigh_ins.assert_called_once_with('2026-10-01', '2026-10-13')
        self.assertEqual(readings, [{'date': '2026-10-06', 'weight': 98.5}])
        self.assertEqual(json.loads(output.read_text()), readings)

    def test_daily_job_forces_the_completed_week_only_on_tuesdays(self):
        for run_date, expected in ((self.tuesday, self.week), (date(2026,10,12), [])):
            with self.subTest(run_date=run_date), \
                 patch.object(main, 'DATA_DIR', self.root), \
                 patch.object(main, 'today', return_value=run_date), \
                 patch.object(main, 'load_settings', return_value=Settings(self.root / 'health')), \
                 patch.dict(main.os.environ, {'START_DATE': '2026-10-01'}), \
                 patch('garmin_extract.authentication.authenticate', return_value='client'), \
                 patch.object(weight, 'get_weight_data') as weights, \
                 patch.object(steps, 'get_step_data') as step_data, \
                 patch.object(sleep, 'get_sleep_data') as sleep_data:
                self.assertEqual(main.run_daily(only='garmin', skip_sheets=True), 0)
                weights.assert_called_once_with('client')
                step_data.assert_called_once_with('client', refresh_dates=expected)
                sleep_data.assert_called_once_with('client', refresh_dates=expected)
