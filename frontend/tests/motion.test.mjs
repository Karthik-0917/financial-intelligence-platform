import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

const chart = readFileSync(new URL('../src/FinancialChart.tsx', import.meta.url), 'utf8');
const source = ts.createSourceFile('FinancialChart.tsx', chart, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const hook = source.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'useChartMotion');
assert.ok(hook);
const code = ts.transpileModule(hook.getText(source), {
  compilerOptions: {target: ts.ScriptTarget.ES2022},
}).outputText;

// Policy-level tests of the actual hook, not chart rendering or financial data.
// Hook primitives and the media-query host are isolated so subscription cleanup
// and reduced-motion configuration can be checked without a new dependency.
function inspectMotion(reduced, token = '420ms') {
  const updates = [];
  let listener;
  let cleanup;
  const media = {
    matches: reduced,
    addEventListener(type, callback) {
      assert.equal(type, 'change');
      listener = callback;
    },
    removeEventListener(type, callback) {
      assert.equal(type, 'change');
      assert.equal(callback, listener);
      listener = undefined;
    },
  };
  const context = vm.createContext({
    window: {matchMedia(query) {
      assert.equal(query, '(prefers-reduced-motion: reduce)');
      return media;
    }},
    document: {documentElement: {}},
    getComputedStyle: () => ({getPropertyValue(name) {
      assert.equal(name, '--fi-motion-chart');
      return token;
    }}),
    useState: initializer => [initializer(), value => updates.push(value)],
    useEffect: effect => { cleanup = effect(); },
  });
  const result = vm.runInContext(`${code}\nuseChartMotion()`, context);
  return {result, updates, media, change: () => listener?.(), close: () => cleanup(), subscribed: () => !!listener};
}

test('chart motion uses the canonical duration with immediate animation start', () => {
  const state = inspectMotion(false, '360ms');
  assert.equal(state.result.isAnimationActive, true);
  assert.equal(state.result.animationBegin, 0);
  assert.equal(state.result.animationDuration, 360);
  assert.equal(state.result.animationEasing, 'ease-in-out');
  state.close();
});

test('reduced motion disables chart animation and its listener is cleaned up', () => {
  const state = inspectMotion(true);
  assert.equal(state.result.isAnimationActive, false);
  assert.deepEqual(state.updates, [true]);
  state.media.matches = false;
  state.change();
  assert.deepEqual(state.updates, [true, false]);
  state.close();
  assert.equal(state.subscribed(), false);
});

test('chart motion retains missing-value and exact-value safeguards', () => {
  assert.match(chart, /connectNulls=\{false\}/);
  assert.match(chart, /<code>\{value\}<\/code>/);
  assert.match(chart, /<Tooltip\s+isAnimationActive=\{false\}/);
  assert.equal((chart.match(/\{\.\.\.chartMotion\}/g) || []).length, 2);
  assert.doesNotMatch(hook.getText(source), /api\(|setTimeout|requestAnimationFrame/);
});

test('unchanged chart scope does not restart animation on parent input edits', () => {
  const assignment = source.statements.find(node => ts.isExportAssignment(node));
  const comparator = assignment.expression.arguments[1];
  const sameInputs = vm.runInNewContext(ts.transpileModule(`(${comparator.getText(source)})`, {
    compilerOptions: {target: ts.ScriptTarget.ES2022},
  }).outputText);
  const input = {analytics: {}, metric: 'revenue', companies: ['AAPL']};
  assert.equal(sameInputs(input, {...input, companies: ['AAPL']}), true);
  assert.equal(sameInputs(input, {...input, metric: 'net_income'}), false);
  assert.equal(sameInputs(input, {...input, companies: ['MSFT']}), false);
  assert.equal(sameInputs(input, {...input, analytics: {}}), false);
  assert.equal(sameInputs(input, {...input, kind: 'bar'}), false);
  assert.equal(sameInputs(input, {...input, years: [2023]}), false);
});