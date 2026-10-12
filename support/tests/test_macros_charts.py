from datetime import date
from copy import deepcopy
import unittest

from publish.macros_charts import chart_rows, plan_charts, serial, chart_window


class ChartTests(unittest.TestCase):
    def metadata(self):
        diary = {"properties": {"sheetId": 12, "title": "MACROS & WEIGHT"}, "charts": [
            {"chartId": 1, "position": {"overlayPosition": {"anchorCell": {"rowIndex": 21}}}},
            {"chartId": 2, "position": {"overlayPosition": {"anchorCell": {"rowIndex": 13, "columnIndex": 13}}}}]}
        def data(column):
            return {'sourceRange':{'sources':[{'sheetId':13,'startRowIndex':0,'endRowIndex':366,
                                               'startColumnIndex':column,'endColumnIndex':column+1}]}}
        for chart in diary['charts']:
            bottom = chart['chartId']==1
            chart['spec'] = {'title':'CALORIE INTAKE & BODY WEIGHT',
                'subtitle':'09 Oct 2025 – 08 Oct 2026', 'fontName':'Roboto',
                'basicChart':{'chartType':'LINE','interpolateNulls':False,
                    'axis':[{'position':'BOTTOM_AXIS','viewWindowOptions':{'viewWindowMode':'EXPLICIT',
                              'viewWindowMin':serial(date(2025,10,9)),'viewWindowMax':serial(date(2026,10,8))}},
                            {'position':'LEFT_AXIS','viewWindowOptions':{'viewWindowMode':'EXPLICIT',
                              'viewWindowMin':1500,'viewWindowMax':3000}}],
                    'domains':[{'domain':data(3 if bottom else 0)}],
                    'series':[{'series':data(4 if bottom else 1),'targetAxis':'LEFT_AXIS','lineStyle':{'width':2,'type':'SOLID'}}]}}
            if bottom:
                chart['spec']['basicChart']['axis'].append({'position':'RIGHT_AXIS',
                    'viewWindowOptions':{'viewWindowMin':95,'viewWindowMax':103}})
                chart['spec']['basicChart']['series'].append({'series':data(10),'targetAxis':'RIGHT_AXIS',
                    'lineStyle':{'width':2,'type':'SOLID'},'pointStyle':{'size':0}})
        return {"sheets": [diary]}, diary

    def test_window_is_60_days_including_today_across_leap_and_year_boundaries(self):
        self.assertEqual(chart_window(date(2026,10,8)), (date(2026,8,10),date(2026,10,8)))
        self.assertEqual(chart_window(date(2024,2,29)), (date(2024,1,1),date(2024,2,29)))
        self.assertEqual(chart_window(date(2026,10,9))[0],date(2026,8,11))
        self.assertEqual(chart_window(date(2026,1,1))[0],date(2025,11,3))

    def test_daily_sources_cover_only_window_and_weekly_edges_are_clipped(self):
        rows, count = chart_rows("MACROS & WEIGHT",date(2025,7,29),486,date(2026,10,8))
        self.assertEqual(len(rows),61)
        self.assertEqual(rows[1][3],serial(date(2026,8,10)))
        self.assertEqual(rows[-1][3],serial(date(2026,10,8)))
        self.assertIn(f'">={serial(date(2026,8,10))}"',rows[1][1])
        self.assertIn(f'"<={serial(date(2026,10,8))}"',rows[count][1])
        self.assertIn('$I$39:$I$486',rows[1][4])
        self.assertIn('$D$39:$D$486',rows[-1][5])
        self.assertIn('">0"',rows[1][5])

    def test_two_charts_split_calories_and_weight_by_horizontal_position(self):
        metadata,diary = self.metadata()
        requests = plan_charts(metadata,diary,date(2025,7,29),486,date(2026,10,8), include_chart_specs=True)
        charts = {r['updateChartSpec']['chartId']:r['updateChartSpec']['spec'] for r in requests if 'updateChartSpec' in r}
        self.assertEqual(set(charts),{1,2})
        self.assertEqual(charts[1]['title'],'CALORIE INTAKE')
        self.assertEqual(charts[2]['title'],'BODY WEIGHT')
        self.assertEqual([series['targetAxis'] for series in charts[1]['basicChart']['series']],['LEFT_AXIS'])
        self.assertFalse(charts[1]['basicChart']['interpolateNulls'])
        self.assertEqual(charts[1]['basicChart']['series'][0]['series']['sourceRange']['sources'][0]['startColumnIndex'],4)
        self.assertEqual(charts[2]['basicChart']['series'][0]['series']['sourceRange']['sources'][0]['startColumnIndex'],10)
        rows,_ = chart_rows('MACROS & WEIGHT',date(2025,7,29),486,date(2026,10,8))
        self.assertIn('ISNUMBER(G2)',rows[1][10])
        self.assertIn('ISNUMBER(I2)',rows[1][10])
        self.assertEqual(charts[1]['basicChart']['axis'][1]['viewWindowOptions'],
                         {'viewWindowMode':'EXPLICIT','viewWindowMin':1500,'viewWindowMax':3000})
        self.assertEqual(charts[2]['basicChart']['axis'][1]['viewWindowOptions'],
                         {'viewWindowMode':'EXPLICIT','viewWindowMin':95,'viewWindowMax':105})
        self.assertTrue(all(len(spec['basicChart']['axis']) == 2 for spec in charts.values()))
        self.assertFalse(any('updateEmbeddedObjectPosition' in r for r in requests))
        self.assertEqual(charts[1]['basicChart']['axis'][0]['viewWindowOptions']['viewWindowMode'],'EXPLICIT')

    def test_split_preserves_metadata_styling_and_daily_window(self):
        metadata,diary = self.metadata()
        before=deepcopy(diary)
        requests=plan_charts(metadata,diary,date(2025,7,29),493,date(2026,10,9), include_chart_specs=True)
        self.assertEqual(diary,before)
        for request in requests:
            if 'updateChartSpec' not in request:
                continue
            update=request['updateChartSpec']
            expected=deepcopy(next(c['spec'] for c in before['charts'] if c['chartId']==update['chartId']))
            actual=deepcopy(update['spec'])
            self.assertEqual(actual['subtitle'],'11 Aug 2026 – 09 Oct 2026')
            self.assertEqual(actual['fontName'],expected['fontName'])
            axis=actual['basicChart']['axis'][0]
            self.assertEqual(axis['viewWindowOptions']['viewWindowMax'],serial(date(2026,10,9)))
            self.assertEqual(axis['viewWindowOptions']['viewWindowMode'],'EXPLICIT')
            basic=actual['basicChart']
            sources=[d['domain'] for d in basic['domains']]+[s['series'] for s in basic['series']]
            for source in sources:
                grid=source['sourceRange']['sources'][0]
                self.assertEqual(grid['startRowIndex'],0)
                self.assertEqual(grid['endRowIndex'],61)
                self.assertEqual(grid['sheetId'],13)

    def test_existing_helper_is_reused_and_old_leap_day_cleared(self):
        metadata,diary = self.metadata()
        metadata['sheets'].append({'properties':{'sheetId':20,'title':'_Sparkes chart data'}})
        requests = plan_charts(metadata,diary,date(2025,7,29),493,date(2026,10,9))
        self.assertFalse(any('addSheet' in r for r in requests))
        cells = next(r['updateCells'] for r in requests if 'updateCells' in r)
        self.assertEqual(len(cells['rows']),370)
        self.assertEqual(cells['range']['sheetId'],20)
        self.assertEqual(cells['rows'][-1]['values'][0]['userEnteredValue'],{'stringValue':''})

    def test_publishing_source_data_does_not_depend_on_chart_count_or_position(self):
        for charts in ([], [{"chartId": 1}], [{"chartId": i} for i in range(3)]):
            with self.subTest(charts=charts):
                metadata, diary = self.metadata()
                diary['charts'] = charts
                before = deepcopy(diary)
                requests = plan_charts(metadata, diary, date(2025,7,29), 486, date(2026,10,8))
                cells = next(request['updateCells'] for request in requests if 'updateCells' in request)
                self.assertEqual(cells['rows'][60]['values'][3]['userEnteredValue'],
                                 {'numberValue': serial(date(2026,10,8))})
                self.assertFalse(any('updateChartSpec' in request for request in requests))
                self.assertEqual(diary, before)

    def test_three_chart_specs_use_one_60_day_window_and_weekly_step_data(self):
        metadata, diary = self.metadata()
        steps = deepcopy(diary['charts'][1])
        steps['chartId'] = 3
        steps['spec']['title'] = 'AVERAGE WEEKLY STEPS'
        diary['charts'].append(steps)
        requests = plan_charts(metadata, diary, date(2025,7,29), 486,
                               date(2026,10,8), include_chart_specs=True)
        specs = {r['updateChartSpec']['chartId']: r['updateChartSpec']['spec']
                 for r in requests if 'updateChartSpec' in r}
        self.assertEqual(set(specs), {1, 2, 3})
        self.assertEqual(specs[3]['title'], 'AVERAGE WEEKLY STEPS')
        rows, weekly_count = chart_rows('MACROS & WEIGHT', date(2025,7,29), 486, date(2026,10,8))
        grid = specs[3]['basicChart']['series'][0]['series']['sourceRange']['sources'][0]
        self.assertEqual(grid['startColumnIndex'], 1)
        self.assertEqual(grid['endRowIndex'], weekly_count + 1)
        for spec in specs.values():
            self.assertEqual(spec['subtitle'], '10 Aug 2026 – 08 Oct 2026')
            window = spec['basicChart']['axis'][0]['viewWindowOptions']
            self.assertEqual(window['viewWindowMin'], serial(date(2026,8,10)))
            self.assertEqual(window['viewWindowMax'], serial(date(2026,10,8)))
