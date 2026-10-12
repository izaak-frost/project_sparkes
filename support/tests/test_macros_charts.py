from datetime import date
from copy import deepcopy
import unittest

from publish.macros_charts import chart_rows, plan_charts, serial, year_window


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
            chart['spec'] = {'title':'CALORIE INTAKE & BODY WEIGHT' if bottom else 'AVERAGE WEEKLY STEPS',
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

    def test_window_moves_daily_and_handles_leap_year(self):
        self.assertEqual(year_window(date(2026,10,8)), (date(2025,10,9),date(2026,10,8)))
        self.assertEqual(year_window(date(2024,2,29)), (date(2023,3,1),date(2024,2,29)))
        self.assertEqual(year_window(date(2026,10,9))[0],date(2025,10,10))

    def test_daily_sources_cover_only_window_and_weekly_edges_are_clipped(self):
        rows, count = chart_rows("MACROS & WEIGHT",date(2025,7,29),486,date(2026,10,8))
        self.assertEqual(len(rows),366)
        self.assertEqual(rows[1][3],serial(date(2025,10,9)))
        self.assertEqual(rows[-1][3],serial(date(2026,10,8)))
        self.assertIn(f'">={serial(date(2025,10,9))}"',rows[1][1])
        self.assertIn(f'"<={serial(date(2026,10,8))}"',rows[count][1])
        self.assertIn('$I$39:$I$486',rows[1][4])
        self.assertIn('$D$39:$D$486',rows[-1][5])
        self.assertIn('">0"',rows[1][5])

    def test_two_charts_keep_positions_and_combined_chart_has_separate_axes(self):
        metadata,diary = self.metadata()
        requests = plan_charts(metadata,diary,date(2025,7,29),486,date(2026,10,8))
        charts = {r['updateChartSpec']['chartId']:r['updateChartSpec']['spec'] for r in requests if 'updateChartSpec' in r}
        self.assertEqual(set(charts),{1,2})
        self.assertEqual(charts[2]['title'],'AVERAGE WEEKLY STEPS')
        self.assertEqual([series['targetAxis'] for series in charts[1]['basicChart']['series']],['LEFT_AXIS','RIGHT_AXIS'])
        self.assertFalse(charts[1]['basicChart']['interpolateNulls'])
        self.assertEqual(charts[1]['basicChart']['series'][1]['series']['sourceRange']['sources'][0]['startColumnIndex'],10)
        rows,_ = chart_rows('MACROS & WEIGHT',date(2025,7,29),486,date(2026,10,8))
        self.assertIn('ISNUMBER(G2)',rows[1][10])
        self.assertIn('ISNUMBER(I2)',rows[1][10])
        self.assertEqual(charts[1]['basicChart']['axis'][1]['viewWindowOptions'],
                         {'viewWindowMode':'EXPLICIT','viewWindowMin':1500,'viewWindowMax':3000})
        self.assertEqual(charts[1]['basicChart']['axis'][2]['viewWindowOptions'],
                         {'viewWindowMin':95,'viewWindowMax':103})
        self.assertFalse(any('updateEmbeddedObjectPosition' in r for r in requests))
        self.assertEqual(charts[1]['basicChart']['axis'][0]['viewWindowOptions']['viewWindowMode'],'EXPLICIT')

    def test_refresh_changes_only_dates_and_source_ranges_preserving_user_settings(self):
        metadata,diary = self.metadata()
        before=deepcopy(diary)
        requests=plan_charts(metadata,diary,date(2025,7,29),493,date(2026,10,9))
        self.assertEqual(diary,before)
        for request in requests:
            if 'updateChartSpec' not in request:
                continue
            update=request['updateChartSpec']
            expected=deepcopy(next(c['spec'] for c in before['charts'] if c['chartId']==update['chartId']))
            actual=deepcopy(update['spec'])
            self.assertEqual(actual['subtitle'],'10 Oct 2025 – 09 Oct 2026')
            actual['subtitle']=expected['subtitle']
            for axis,old in zip(actual['basicChart']['axis'],expected['basicChart']['axis']):
                if axis['position']=='BOTTOM_AXIS':
                    self.assertEqual(axis['viewWindowOptions']['viewWindowMax'],serial(date(2026,10,9)))
                    axis['viewWindowOptions']=old['viewWindowOptions']
            def chart_data(spec):
                basic=spec['basicChart']
                return [d['domain'] for d in basic['domains']]+[s['series'] for s in basic['series']]
            for new,old in zip(chart_data(actual),chart_data(expected)):
                new['sourceRange']=old['sourceRange']
            self.assertEqual(actual,expected)

    def test_existing_helper_is_reused_and_old_leap_day_cleared(self):
        metadata,diary = self.metadata()
        metadata['sheets'].append({'properties':{'sheetId':20,'title':'_Sparkes chart data'}})
        requests = plan_charts(metadata,diary,date(2025,7,29),493,date(2026,10,9))
        self.assertFalse(any('addSheet' in r for r in requests))
        cells = next(r['updateCells'] for r in requests if 'updateCells' in r)
        self.assertEqual(len(cells['rows']),370)
        self.assertEqual(cells['range']['sheetId'],20)
        self.assertEqual(cells['rows'][-1]['values'][0]['userEnteredValue'],{'stringValue':''})
