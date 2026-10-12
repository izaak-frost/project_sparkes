from copy import deepcopy
import unittest
from unittest.mock import MagicMock

from publish.export_checkins import plan_blank_week


class CheckinTests(unittest.TestCase):
    def layout(self, filled=True):
        rows = [[""] * 18 for _ in range(20)]
        for column, label in {1: "WEEK", 2: "QUESTION", 4: "CLIENT RESPONSE", 15: "Complete?", 16: "Response"}.items():
            rows[7][column] = label
        for start, week in ((8, 61), (14, 62)):
            rows[start][1] = week
            for offset in range(6):
                rows[start + offset][2] = f"Question {offset + 1}"
                rows[start + offset][15] = False
        if filled:
            rows[14][4] = "Keep this answer"
            rows[16][16] = "Keep coach feedback"
            rows[15][15] = True
        meta = {"merges": [{"sheetId": 123, "startRowIndex": 14, "endRowIndex": 20,
                            "startColumnIndex": 1, "endColumnIndex": 2}],
                "data": [{"startRow": 14, "rowMetadata": [{"pixelSize": 40 + i} for i in range(6)]}]}
        return MagicMock(id=123, row_count=20), rows, meta

    def test_filled_week_appends_blank_week_preserving_old_answers_and_questions(self):
        worksheet, rows, meta = self.layout()
        before = deepcopy(rows)
        requests, week = plan_blank_week(worksheet, rows, meta)
        self.assertEqual(week, 63)
        self.assertEqual(rows, before)
        self.assertEqual(requests[0]['appendDimension']['length'], 6)
        copy = requests[1]['copyPaste']
        self.assertEqual(copy['pasteType'], 'PASTE_NORMAL')
        self.assertEqual(copy['destination']['startRowIndex'], 20)
        # Simulate the value operations; copied questions stay, answers don't.
        result = deepcopy(rows) + deepcopy(rows[14:20])
        for request in requests:
            if 'updateCells' not in request:
                continue
            update = request['updateCells']
            if 'range' in update:
                grid = update['range']
                for row in range(grid['startRowIndex'], grid['endRowIndex']):
                    for column in range(grid['startColumnIndex'], grid['endColumnIndex']):
                        result[row][column] = False if column == 15 else ''
            else:
                result[update['start']['rowIndex']][update['start']['columnIndex']] = week
        self.assertEqual(result[:20], before)
        self.assertEqual(result[20][1], 63)
        self.assertEqual([row[2] for row in result[20:]], [f'Question {i}' for i in range(1, 7)])
        self.assertTrue(all(row[4] == '' and row[16] == '' and row[15] is False for row in result[20:]))
        # A second run must not append another blank week.
        meta['merges'].append({**meta['merges'][0], 'startRowIndex': 20, 'endRowIndex': 26})
        self.assertEqual(plan_blank_week(MagicMock(id=123, row_count=26), result, meta), ([], None))
        heights = [r['updateDimensionProperties']['properties']['pixelSize']
                   for r in requests if 'updateDimensionProperties' in r]
        self.assertEqual(heights, list(range(40, 46)))

    def test_blank_week_with_unchecked_boxes_is_left_untouched(self):
        self.assertEqual(plan_blank_week(*self.layout(False)), ([], None))

    def test_coach_feedback_or_checked_box_requires_a_new_week(self):
        for column, value in ((16, 'Coach feedback'), (15, True), (4, 0)):
            worksheet, rows, meta = self.layout(False)
            rows[19][column] = value
            self.assertEqual(plan_blank_week(worksheet, rows, meta)[1], 63)

    def test_invalid_template_or_content_below_is_rejected(self):
        worksheet, rows, meta = self.layout()
        rows[19][2] = ''
        with self.assertRaisesRegex(ValueError, 'six questions'):
            plan_blank_week(worksheet, rows, meta)
        worksheet, rows, meta = self.layout()
        rows.append(['', '', 'Unrelated content'])
        with self.assertRaisesRegex(ValueError, 'Content follows'):
            plan_blank_week(worksheet, rows, meta)
