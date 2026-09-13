import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import postcss from 'postcss';

const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const css = read('src/workspace-midnight.css');
const interior = css.slice(css.indexOf('/* Overview interior.'), css.indexOf('/* Benchmarking */'));
const root = postcss.parse(interior);
const main = read('src/main.tsx');

test('Overview presentation is scoped without changing shared shell or other page grids', () => {
  const shared = new Set([
    '.app .mf-chart-surface',
    '.app .mf-chart-surface .chart-frame',
    '.app .mf-chart-surface .financial-chart',
  ]);
  root.walkRules(rule => {
    assert.ok(rule.selector.includes('.mf-overview') || shared.has(rule.selector), rule.selector);
    assert.doesNotMatch(rule.selector, /sidebar|topbar|main-shell|navigation-dialog/);
  });
  assert.doesNotMatch(css.slice(css.indexOf('/* Internal page adaptation only */')), /mf-executive-header|mf-overview-question|mf-company-snapshots|mf-readiness-panel/);
  assert.doesNotMatch(interior, /--fi-[\w-]+\s*:/);
  root.walkDecls(declaration => assert.doesNotMatch(declaration.value, /#[\da-f]{3,8}\b/i));
});

test('Overview has deliberate desktop, tablet and narrow-screen compositions', () => {
  assert.match(interior, /grid-template-columns: minmax\(0, 2fr\) minmax\(260px, 1fr\)/);
  for (const width of [1100, 850, 600]) assert.ok(interior.includes(`@media (max-width: ${width}px)`));
  assert.match(interior, /\.mf-overview-question label \{[\s\S]*?position: static/);
  assert.match(interior, /\.mf-executive-header dl \{ grid-template-columns: minmax\(0, 1fr\)/);
  assert.match(interior, /\.mf-ranking-track \{[\s\S]*?grid-row: 2/);
  assert.doesNotMatch(interior, /\bzoom\s*:|scale\(|overflow-x:\s*hidden|animation:/);
});

test('company paint is mapped by existing identity, never rank, while bar widths stay data-owned', () => {
  for (const company of ['aapl', 'msft', 'amzn']) assert.ok(interior.includes(`var(--fi-company-${company})`));
  assert.match(interior, /\[stroke="#285de5"\]/);
  assert.match(interior, /\[style\*="rgb\(8, 127, 115\)"\]/);
  assert.doesNotMatch(interior, /nth-child|nth-of-type/);
  root.walkDecls(declaration => {
    if (declaration.important) assert.ok(['color', 'background', 'border-top-color', 'border', 'border-radius', 'box-shadow'].includes(declaration.prop));
  });
  assert.match(main, /width: `\$\{width\}%`, background: COMPANY_COLORS\[item.ticker\]/);
  assert.match(main, /compareDecimal\(b.raw, a.raw\)/);
});

test('Overview retains corpus, financial, readiness, source and research content bindings', () => {
  const overview = main.slice(main.indexOf("{page === 'overview' &&"), main.indexOf("<div hidden={page !== 'research'}>"));
  for (const binding of ['financial_validated_fact_count', 'operating_margin', 'revenue_yoy_growth', 'RankingChart', 'FinancialChart', 'knowledgeState(published)', 'available2024.map', 'openReport(report)', 'research(question)', 'setStatement(\'Margins\')']) assert.ok(overview.includes(binding), binding);
  assert.match(overview, /minLength=\{5\} maxLength=\{2000\} required/);
  assert.match(overview, /htmlFor="overview-question"/);
  const chart = read('src/FinancialChart.tsx');
  assert.match(chart, /connectNulls=\{false\}/);
  assert.match(chart, /isAnimationActive=\{false\}/);
  assert.match(chart, /Exact chart values and availability/);
});