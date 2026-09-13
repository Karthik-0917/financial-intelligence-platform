import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import postcss from 'postcss';

const read = path => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');
const workspace = read('workspace-midnight.css');
const research = read('research-midnight.css');
const quality = read('midnight.css');
const roots = [workspace, research, quality].map(css => postcss.parse(css));
const base = selector => roots.flatMap(root => root.nodes).find(node => node.type === 'rule' && node.selector === `.app ${selector}`);
const value = (selector, property) => base(selector)?.nodes.find(node => node.prop === property)?.value;

test('analytical layouts change composition, not just palette', () => {
  assert.equal(value('.mf-research-composer', 'display'), 'grid');
  assert.equal(value('.mf-research-starting-points', 'grid-template-columns'), 'minmax(0, 1fr)');
  assert.equal(value('.mf-benchmark-layout', 'grid-template-columns'), 'minmax(0, 1fr)');
  assert.equal(value('.mf-metric-navigation', 'display'), 'flex');
  assert.equal(value('.mf-library-filters', 'display'), 'grid');
  assert.equal(value('.mf-audit-layout', 'grid-template-columns'), 'minmax(220px, .7fr) minmax(0, 2fr)');
  assert.equal(value('.mf-quality-empty', 'grid-template-columns'), 'minmax(0, 1fr)');
  assert.equal(value('.mf-acquisition-flow', 'grid-template-columns'), 'repeat(2, minmax(0, 1fr))');
});

test('presentation references defined canonical tokens without redefining the foundation', () => {
  const foundation = postcss.parse(read('style.css'));
  const defined = new Set();
  foundation.walkDecls(declaration => { if (declaration.prop.startsWith('--fi-')) defined.add(declaration.prop); });
  for (const root of roots) root.walkDecls(declaration => {
    assert.ok(!declaration.prop.startsWith('--fi-'));
    for (const [, name] of declaration.value.matchAll(/var\((--fi-[\w-]+)/g)) assert.ok(defined.has(name), name);
  });
});

test('analytical shared paint excludes Overview and never changes financial widths', () => {
  const shared = postcss.parse(workspace.slice(workspace.indexOf('/* Shared analytical presentation')));
  shared.walkRules(rule => {
    if (/mf-table|recharts|mf-ranking|mf-company-mark|\.notice|:is\(h2/.test(rule.selector)) assert.ok(rule.selector.includes('main:not(:has(.mf-overview))'));
    rule.walkDecls(declaration => {
      if (declaration.important) assert.ok(['color', 'background', 'border', 'border-radius', 'box-shadow'].includes(declaration.prop));
    });
  });
  for (const company of ['aapl', 'msft', 'amzn']) assert.ok(shared.toString().includes(`var(--fi-company-${company})`));
  assert.doesNotMatch(shared.toString(), /nth-child|nth-of-type|overflow-x:\s*hidden|scale\(/);
});

test('responsive layouts and distinct evidence/calculation treatments remain present', () => {
  for (const css of [workspace, research, quality]) assert.ok(css.includes('@media (max-width: 720px)'));
  for (const selector of ['.mf-calculation-record', '.mf-source-reader', '.mf-evidence-reference.selected', '.mf-research-abstention h3']) assert.ok(base(selector), selector);
  assert.equal(value('.mf-calculation-record', 'border-left'), '2px solid var(--fi-evidence)');
  assert.equal(value('.mf-research-abstention h3', 'color'), 'var(--fi-warning)');
});

test('all seven routes and data-gated evaluation controls are retained', () => {
  const main = read('main.tsx');
  for (const page of ['research', 'compare', 'filings', 'financials', 'evidence', 'evaluation', 'methodology']) assert.ok(main.includes(`id: '${page}'`));
  const evaluation = read('EvaluationCenter.tsx');
  for (const marker of ['ResourceState', 'data &&', 'Download', 'Search evaluation records', 'Pagination', 'onPageChange={setPage}', 'Selected evaluation record']) assert.ok(evaluation.includes(marker), marker);
  const answer = read('ResearchWorkspace.tsx');
  for (const marker of ['minLength={5}', 'maxLength={2000}', 'Optional scope defaults', 'AbortController', 'mf-source-reader', 'mf-calculation-record']) assert.ok(answer.includes(marker), marker);
});