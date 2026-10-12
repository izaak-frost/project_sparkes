// Paste into this spreadsheet's Extensions > Apps Script editor.
// Run installSparkesChartRefresh once. Google asks you to authorise sheet access.
// The publisher updates the hidden source table. This script keeps the existing
// chart positions: weekly steps above, calories left and weight right below.
const SPARKES_SHEET_ID = '1lnMCo6npQcJkEFk61mT6M2FoDABxZcbrfqEXQtRzHsU';

function refreshSparkesCharts() {
  const book = SpreadsheetApp.openById(SPARKES_SHEET_ID);
  const diary = book.getSheets().find(sheet => sheet.getName().trim() === 'MACROS & WEIGHT');
  const source = book.getSheetByName('_Sparkes chart data');
  if (!diary || !source) throw new Error('Macros diary or chart source sheet is missing');
  const dates = source.getRange('D2:D370').getValues().flat().filter(value => value !== '');
  const weekly = source.getRange('A2:A370').getValues().flat().filter(value => value !== '');
  if (!dates.length || !weekly.length) throw new Error('Chart source dates are missing');
  const allCharts = diary.getCharts();
  const stepsCharts = allCharts.filter(chart =>
    /^AVERAGE WEEKLY STEPS$/i.test(String(chart.getOptions().get('title') || '').trim()));
  const charts = allCharts.filter(chart =>
    /^(CALORIE INTAKE(?: & BODY WEIGHT)?|BODY WEIGHT)$/i
      .test(String(chart.getOptions().get('title') || '').trim()));
  if (charts.length !== 2 || stepsCharts.length !== 1) throw new Error(
    'Expected exactly two calorie/weight charts and one AVERAGE WEEKLY STEPS chart; found ' +
    charts.length + ' calorie/weight and ' + stepsCharts.length + ' steps charts. Check the titles.');
  charts.sort((a, b) => {
    const left = a.getContainerInfo(), right = b.getContainerInfo();
    return left.getAnchorColumn() - right.getAnchorColumn() ||
      left.getOffsetX() - right.getOffsetX() || left.getAnchorRow() - right.getAnchorRow();
  });
  // Read the serial values without DATE formatting or Apps Script timezone shifts.
  const serial = value => value instanceof Date ? Math.round(value.getTime() / 86400000 + 25569) : Number(value);
  const lower = serial(dates[0]), upper = serial(dates[dates.length - 1]);
  const label = value => Utilities.formatDate(new Date((value - 25569) * 86400000), 'UTC', 'dd MMM yyyy');
  const stepsChart = stepsCharts[0];
  const stepsBuilder = stepsChart.modify();
  const stepsHorizontal = JSON.parse(JSON.stringify(stepsChart.getOptions().get('hAxis') || {}));
  stepsHorizontal.viewWindow = {min: lower, max: upper};
  stepsHorizontal.viewWindowMode = 'explicit';
  stepsBuilder.clearRanges().setNumHeaders(1)
    .addRange(source.getRange(1, 1, weekly.length + 1, 2))
    .setOption('hAxis', stepsHorizontal)
    .setOption('subtitle', label(lower) + ' – ' + label(upper));
  diary.updateChart(stepsBuilder.build());
  for (const [index, chart] of charts.entries()) {
    const calories = index === 0;
    const builder = chart.modify();
    // Always replace the ranges: duplicated charts may have identical row counts
    // but still contain both old series. K is the interpolated weight trend.
    builder.clearRanges().setChartType(Charts.ChartType.LINE).setNumHeaders(1);
    builder.addRange(source.getRange(1, 4, dates.length + 1, 1));
    builder.addRange(source.getRange(1, calories ? 5 : 11, dates.length + 1, 1));
    const options = chart.getOptions();
    const horizontal = JSON.parse(JSON.stringify(options.get('hAxis') || {}));
    horizontal.viewWindow = {min: lower, max: upper};
    horizontal.viewWindowMode = 'explicit';
    builder.setOption('hAxis', horizontal).setOption('subtitle', label(lower) + ' – ' + label(upper));
    const vertical = {
      title: calories ? 'Calories (kcal)' : 'Body weight (kg)',
      viewWindowMode: 'explicit',
      viewWindow: {min: calories ? 1500 : 95, max: calories ? 3000 : 105},
      format: calories ? '#,##0' : '0.0'
    };
    builder.setOption('title', calories ? 'CALORIE INTAKE' : 'BODY WEIGHT')
      .setOption('vAxis', vertical)
      .setOption('vAxes', {0: vertical})
      .setOption('series', {0: {targetAxisIndex: 0, color: calories ? '#f56b17' : '#6e47cf',
        lineWidth: 2, pointSize: calories ? 2 : 0}})
      .setOption('interpolateNulls', false);
    diary.updateChart(builder.build());
  }
}

function installSparkesChartRefresh() {
  refreshSparkesCharts();
  // Replace previous hourly/daily triggers without touching other automations.
  for (const trigger of ScriptApp.getProjectTriggers()) {
    if (trigger.getHandlerFunction() === 'refreshSparkesCharts') ScriptApp.deleteTrigger(trigger);
  }
  // Google schedules nearMinute within +/- 15 minutes, rather than exactly 06:00.
  ScriptApp.newTrigger('refreshSparkesCharts').timeBased()
    .inTimezone('Europe/London').atHour(6).nearMinute(0).everyDays(1).create();
}
