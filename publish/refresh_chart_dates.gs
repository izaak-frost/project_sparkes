// Paste into this spreadsheet's Extensions > Apps Script editor.
// Run installSparkesChartRefresh once. Google asks you to authorise sheet access.
// The data publisher updates the hidden source table; this script updates only
// the native chart ranges/date window, preserving the chart editor's settings.
const SPARKES_SHEET_ID = '1lnMCo6npQcJkEFk61mT6M2FoDABxZcbrfqEXQtRzHsU';

function refreshSparkesCharts() {
  const book = SpreadsheetApp.openById(SPARKES_SHEET_ID);
  const diary = book.getSheets().find(sheet => sheet.getName().trim() === 'MACROS & WEIGHT');
  const source = book.getSheetByName('_Sparkes chart data');
  const dates = source.getRange('D2:D370').getValues().flat().filter(value => value !== '');
  const weekly = source.getRange('A2:A370').getValues().flat().filter(value => value !== '');
  if (!dates.length || !weekly.length) throw new Error('Chart source dates are missing');
  // Read the serial values without DATE formatting or Apps Script timezone shifts.
  const serial = value => value instanceof Date ? Math.round(value.getTime() / 86400000 + 25569) : Number(value);
  const lower = serial(dates[0]), upper = serial(dates[dates.length - 1]);
  const label = value => Utilities.formatDate(new Date((value - 25569) * 86400000), 'UTC', 'dd MMM yyyy');
  for (const chart of diary.getCharts()) {
    const isSteps = chart.getChartId() === 720531623;
    const isCombined = chart.getChartId() === 2060008229;
    if (!isSteps && !isCombined) continue;
    const builder = chart.modify();
    const count = isSteps ? weekly.length : dates.length;
    const ranges = chart.getRanges();
    if (ranges.some(range => range.getNumRows() !== count + 1)) {
      builder.clearRanges();
      if (isSteps) builder.addRange(source.getRange(1, 1, count + 1, 2));
      else {
        builder.addRange(source.getRange(1, 4, count + 1, 2));
        builder.addRange(source.getRange(1, 11, count + 1, 1));
      }
    }
    const options = chart.getOptions();
    const horizontal = JSON.parse(JSON.stringify(options.get('hAxis') || {}));
    horizontal.viewWindow = {min: lower, max: upper};
    horizontal.viewWindowMode = 'explicit';
    builder.setOption('hAxis', horizontal).setOption('subtitle', label(lower) + ' – ' + label(upper));
    if (isCombined) {
      const axes = JSON.parse(JSON.stringify(options.get('vAxes') || {}));
      axes[0] = axes[0] || {};
      axes[1] = axes[1] || {};
      // Recover the user's captured bounds if an earlier REST refresh removed them.
      axes[0].viewWindow = axes[0].viewWindow || {};
      axes[1].viewWindow = axes[1].viewWindow || {};
      if (!Number.isFinite(axes[0].viewWindow.min)) axes[0].viewWindow.min = 1500;
      if (!Number.isFinite(axes[0].viewWindow.max)) axes[0].viewWindow.max = 3000;
      if (!Number.isFinite(axes[1].viewWindow.min)) axes[1].viewWindow.min = 95;
      if (!Number.isFinite(axes[1].viewWindow.max)) axes[1].viewWindow.max = 103;
      builder.setOption('vAxes', axes);
    }
    diary.updateChart(builder.build());
  }
}

function installSparkesChartRefresh() {
  refreshSparkesCharts();
  if (!ScriptApp.getProjectTriggers().some(trigger => trigger.getHandlerFunction() === 'refreshSparkesCharts')) {
    ScriptApp.newTrigger('refreshSparkesCharts').timeBased().everyHours(1).create();
  }
}
