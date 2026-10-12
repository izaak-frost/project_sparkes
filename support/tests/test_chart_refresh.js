// Run with node support/tests/test_chart_refresh.js. No live spreadsheet access.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const dates = Array.from({length: 60}, (_, i) => 46000 + i);
const weeklyDates = Array.from({length: 9}, (_, i) => 46000 + i * 7);
const source = {
  getRange(...args) {
    return {args, getValues: () => (args[0] === 'A2:A370' ? weeklyDates : dates).map(value => [value])};
  }
};
function chart(column, offset = 0) {
  const options = {hAxis: {format: 'MMM yy'}, vAxes: {1: {viewWindow: {min: 0, max: 125}}}};
  const result = {ranges: ['old combined ranges'], options};
  const builder = {
    clearRanges() {result.ranges = []; return this;},
    setChartType(value) {result.type = value; return this;},
    setNumHeaders(value) {result.headers = value; return this;},
    addRange(value) {result.ranges.push(value.args); return this;},
    setOption(key, value) {options[key] = value; return this;},
    build() {return result;}
  };
  return {
    result,
    getContainerInfo: () => ({getAnchorColumn: () => column, getOffsetX: () => offset, getAnchorRow: () => 1}),
    getOptions: () => ({get: key => options[key]}),
    modify: () => builder
  };
}
const left = chart(1), right = chart(13);
left.result.options.title = 'CALORIE INTAKE & BODY WEIGHT';
right.result.options.title = 'CALORIE INTAKE & BODY WEIGHT';
const steps = chart(20);
steps.result.options.title = 'AVERAGE WEEKLY STEPS';
let charts = [right, steps, left]; // Reversed enumeration must still select by position.
const updates = [];
const diary = {getName: () => 'MACROS & WEIGHT', getCharts: () => charts, updateChart: value => updates.push(value)};
const context = vm.createContext({
  SpreadsheetApp: {openById: () => ({getSheets: () => [diary], getSheetByName: () => source})},
  Charts: {ChartType: {LINE: 'LINE'}},
  Utilities: {formatDate: value => value.toISOString().slice(0, 10)}
});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../../publish/refresh_chart_dates.gs'), 'utf8'), context);
vm.runInContext('refreshSparkesCharts()', context);
assert.equal(updates.length, 3);
// Normalise cross-context objects for strict comparison.
const clean = value => JSON.parse(JSON.stringify(value));
assert.deepEqual(clean(left.result.ranges), [[1, 4, 61, 1], [1, 5, 61, 1]]);
assert.deepEqual(clean(right.result.ranges), [[1, 4, 61, 1], [1, 11, 61, 1]]);
assert.deepEqual(clean(steps.result.ranges), [[1, 1, 10, 2]]);
assert.deepEqual(clean(steps.result.options.hAxis.viewWindow), {min: 46000, max: 46059});
assert.equal(steps.result.options.subtitle, left.result.options.subtitle);
assert.equal(steps.result.options.title, 'AVERAGE WEEKLY STEPS');
assert.equal(left.result.options.title, 'CALORIE INTAKE');
assert.equal(right.result.options.title, 'BODY WEIGHT');
assert.deepEqual(clean(left.result.options.vAxes[0].viewWindow), {min: 1500, max: 3000});
assert.deepEqual(clean(right.result.options.vAxes[0].viewWindow), {min: 95, max: 105});
assert.equal(right.result.options.vAxes[1], undefined);
assert.equal(right.result.options.series[0].targetAxisIndex, 0);
assert.equal(left.result.options.interpolateNulls, false);
assert.equal(left.result.options.hAxis.format, 'MMM yy');
assert.deepEqual(clean(left.result.options.hAxis.viewWindow), {min: 46000, max: 46059});
// Repeated refreshes must not accumulate ranges or resurrect the second axis.
vm.runInContext('refreshSparkesCharts()', context);
assert.equal(left.result.ranges.length, 2);
assert.equal(right.result.ranges.length, 2);
const unrelated = chart(20);
unrelated.result.options.title = 'OTHER DASHBOARD CHART';
charts = [unrelated, right, steps, left];
const previousUpdates = updates.length;
vm.runInContext('refreshSparkesCharts()', context);
assert.equal(updates.length, previousUpdates + 3);
assert.deepEqual(unrelated.result.ranges, ['old combined ranges']);
charts = [left];
assert.throws(() => vm.runInContext('refreshSparkesCharts()', context), /exactly two/);
charts = [left, right, steps];
const unrelatedTrigger = {getHandlerFunction: () => 'otherJob'};
let triggers = [{getHandlerFunction: () => 'refreshSparkesCharts'}, unrelatedTrigger];
let schedule;
context.ScriptApp = {
  getProjectTriggers: () => triggers.slice(),
  deleteTrigger: trigger => {triggers = triggers.filter(item => item !== trigger);},
  newTrigger(handler) {
    schedule = {handler};
    const builder = {
      timeBased() {return this;},
      inTimezone(value) {schedule.timezone = value; return this;},
      atHour(value) {schedule.hour = value; return this;},
      nearMinute(value) {schedule.minute = value; return this;},
      everyDays(value) {schedule.days = value; return this;},
      create() {triggers.push({getHandlerFunction: () => handler});}
    };
    return builder;
  }
};
vm.runInContext('installSparkesChartRefresh(); installSparkesChartRefresh();', context);
assert.deepEqual(schedule, {handler: 'refreshSparkesCharts', timezone: 'Europe/London', hour: 6, minute: 0, days: 1});
assert.equal(triggers.length, 2);
assert.ok(triggers.includes(unrelatedTrigger));
console.log('Chart refresh checks passed');
