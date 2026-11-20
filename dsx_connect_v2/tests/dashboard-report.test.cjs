const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const context = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../dsx_connect_v2/ui/assets/dashboard-report.js'), 'utf8'), context);
const sample = () => ({
  title:'DSX-Connect Operator Report', generatedAt:'2026-11-20T02:00:00Z', days:7,
  start:'2026-11-14T00:00:00Z', end:'2026-11-20T02:00:00Z', connectorSelection:'All connectors',
  connectors:[{name:'AWS <test>', enabled:true},{name:'GCS', enabled:false}],
  warnings:['Inventory incomplete <3 connectors>'], captureNote:'Fixed snapshot; refresh times may differ.',
  sections:[{id:'coverage',title:'Protection coverage',scope:'Recorded inventory.',asOf:'2026-11-20T01:59:00Z',available:true,
    description:'Known assets.',graphicHtml:'<svg viewBox="0 0 450 140"><polyline points="0,0 20,20"/></svg>',
    supportingHtml:'<p>Discovered = Unprotected + Protected.</p>',text:'101 discovered\n9 protected\n92 unprotected'},
    {id:'worker',title:'Scan worker time',scope:'Selected window.',available:false,
      graphicHtml:'<p>Timing data unavailable.</p>',supportingHtml:'',text:'Timing data unavailable.'}]
});

test('HTML report preserves order, graphics, Info, UTC scope, and completeness warnings', () => {
  const html = context.dashboardReportHtml(sample());
  assert.ok(html.indexOf('data-report-widget="coverage"') < html.indexOf('data-report-widget="worker"'));
  for (const expected of ['<svg', '<polyline', 'Discovered = Unprotected + Protected.', 'Range covered',
    '2026-11-14 00:00:00 UTC', '2026-11-20 01:59:00 UTC', 'GCS (disabled)', 'Source data unavailable at capture time.']) assert.ok(html.includes(expected), expected);
  assert.ok(!html.includes('<script'));
  assert.ok(!html.includes('src="http'));
});

test('untrusted headings and connector names remain text in the exported document', () => {
  const report = sample();
  report.sections[0].title = '<script>alert(1)</script>';
  const html = context.dashboardReportHtml(report);
  assert.ok(html.includes('&lt;script&gt;alert(1)&lt;/script&gt;'));
  assert.ok(html.includes('AWS &lt;test&gt;'));
  assert.ok(html.includes('Inventory incomplete &lt;3 connectors&gt;'));
  assert.ok(!html.includes('<script>'));
});

test('plain-text copy includes the same ordered sections, counts, warnings and scope', () => {
  const text = context.dashboardReportText(sample());
  assert.ok(text.indexOf('1. Protection coverage') < text.indexOf('2. Scan worker time'));
  for (const expected of ['All connectors','101 discovered','9 protected','92 unprotected',
    'Inventory incomplete','Source unavailable at capture time.','Data through: 2026-11-20 01:59:00 UTC']) assert.ok(text.includes(expected), expected);
  assert.ok(!text.includes('<svg'));
  assert.ok(!text.includes('undefined'));
});
