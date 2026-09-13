

import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

function sourceFile(relativePath) {
  const url = new URL(relativePath, import.meta.url);
  const content = readFileSync(url, 'utf8');
  return ts.createSourceFile(
    url.pathname,
    content,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
}

function functionSource(source, name) {
  const matches = source.statements.filter(statement =>
    ts.isFunctionDeclaration(statement) &&
    statement.name?.text === name,
  );

  assert.equal(
    matches.length,
    1,
    `Expected one actual ${name} function in the source`,
  );

  return matches[0].getText(source);
}

function constantSource(source, name) {
  const matches = source.statements.filter(statement =>
    ts.isVariableStatement(statement) &&
    statement.declarationList.declarations.some(declaration =>
      ts.isIdentifier(declaration.name) && declaration.name.text === name,
    ),
  );

  assert.equal(
    matches.length,
    1,
    `Expected one actual ${name} constant in the source`,
  );

  return matches[0].getText(source);
}

const mainSource = sourceFile('../src/main.tsx');
const uiSource = sourceFile('../src/ui.tsx');

const selectedSource = [
  constantSource(uiSource, 'DECIMAL'),
  functionSource(uiSource, 'numeric'),
  functionSource(mainSource, 'decimalParts'),
  functionSource(mainSource, 'compareDecimal'),
  functionSource(mainSource, 'rankedValues'),
  'module.exports = {numeric, decimalParts, compareDecimal, rankedValues};',
].join('\n\n');

const compiled = ts.transpileModule(selectedSource, {
  compilerOptions: {
    target: ts.ScriptTarget.ES2020,
    module: ts.ModuleKind.CommonJS,
    strict: true,
  },
  reportDiagnostics: true,
});

const errors = (compiled.diagnostics || []).filter(
  diagnostic => diagnostic.category === ts.DiagnosticCategory.Error,
);

assert.equal(
  errors.length,
  0,
  ts.formatDiagnosticsWithColorAndContext(errors, {
    getCanonicalFileName: value => value,
    getCurrentDirectory: () => '',
    getNewLine: () => '\n',
  }),
);

const sandboxModule = {exports: {}};
const sandbox = {
  module: sandboxModule,
  exports: sandboxModule.exports,
};

vm.runInNewContext(compiled.outputText, sandbox, {
  filename: 'actual-decimal-ranking-implementation.js',
  timeout: 1000,
});

const {
  numeric,
  decimalParts,
  compareDecimal,
  rankedValues,
} = sandboxModule.exports;

function row(ticker, fiscalYear, values) {
  return {
    ticker,
    fiscal_year: fiscalYear,
    values,
    evidence: [],
    calculations: [],
    unavailable_metrics: {},
  };
}

function analytics(rows) {
  return {
    rows,
    issues: [],
    corpus_version: 'synthetic-test-corpus',
  };
}

test('numeric accepts decimal values but not missing data or alternate syntax', () => {
  assert.equal(numeric('0'), 0);
  assert.equal(numeric('-12.5'), -12.5);
  assert.equal(numeric('1.2e3'), 1200);
  assert.equal(numeric(undefined), null);
  assert.equal(numeric(null), null);
  assert.equal(numeric(''), null);
  assert.equal(numeric('   '), null);
  assert.equal(numeric('0x10'), null);
  assert.equal(numeric('Infinity'), null);
  assert.equal(numeric('NaN'), null);
});

test('decimal ordering distinguishes values above browser integer precision', () => {
  const smaller = '9007199254740992';
  const larger = '9007199254740993';

  assert.equal(Number(smaller), Number(larger));
  assert.equal(compareDecimal(smaller, larger), -1);
  assert.equal(compareDecimal(larger, smaller), 1);
});

test('decimal ordering distinguishes close fractional values', () => {
  assert.equal(compareDecimal('31.510000000000000001', '31.51'), 1);
  assert.equal(compareDecimal('0.000000000000000001', '0'), 1);
  assert.equal(compareDecimal('-0.000000000000000001', '0'), -1);
});

test('equivalent decimal representations compare equally', () => {
  for (const [left, right] of [
    ['1', '1.000'],
    ['+001.5000', '1.5'],
    ['1e3', '1000'],
    ['0.001', '1e-3'],
    ['.5', '0.500'],
    ['-0', '0'],
    ['-0.000e20', '+0'],
  ]) {
    assert.equal(compareDecimal(left, right), 0, `${left} versus ${right}`);
  }
});

test('signed ordering is correct for negative, zero, and positive values', () => {
  assert.equal(compareDecimal('-100', '-2'), -1);
  assert.equal(compareDecimal('-2', '-100'), 1);
  assert.equal(compareDecimal('-1', '0'), -1);
  assert.equal(compareDecimal('0', '1'), -1);
  assert.equal(compareDecimal('-1e3', '-999'), -1);
});

test('decimal parser rejects unsupported syntax', () => {
  for (const value of ['', '.', 'abc', 'NaN', 'Infinity', '1.2.3', '0x10']) {
    assert.equal(decimalParts(value), null, value);
  }
});

test('ranking isolates company, fiscal year, and selected metric', () => {
  const data = analytics([
    row('AAPL', 2023, {revenue: '999'}),
    row('AAPL', 2024, {revenue: '20', operating_income: '900'}),
    row('MSFT', 2024, {revenue: '30', operating_income: '1'}),
    row('AMZN', 2024, {revenue: '100'}),
  ]);

  const result = rankedValues(data, 'revenue', ['AAPL', 'MSFT'], 2024);

  assert.equal(result.map(item => item.ticker).join(','), 'MSFT,AAPL');
  assert.equal(result.map(item => item.raw).join(','), '30,20');
});

test('ranking preserves raw strings rather than rounded representations', () => {
  const data = analytics([
    row('AAPL', 2024, {revenue: '9007199254740992'}),
    row('MSFT', 2024, {revenue: '9007199254740993'}),
  ]);

  const result = rankedValues(data, 'revenue', ['AAPL', 'MSFT'], 2024);

  assert.equal(result[0].ticker, 'MSFT');
  assert.equal(result[0].raw, '9007199254740993');
  assert.equal(result[1].raw, '9007199254740992');
});

test('missing observations are excluded from ranking rather than made zero', () => {
  const data = analytics([
    row('AAPL', 2024, {}),
    row('MSFT', 2024, {revenue: '0'}),
    row('AMZN', 2024, {revenue: '-5'}),
  ]);

  const result = rankedValues(data, 'revenue', ['AAPL', 'MSFT', 'AMZN'], 2024);

  assert.equal(result.map(item => item.ticker).join(','), 'MSFT,AMZN');
  assert.equal(result[0].value, 0);
  assert.equal(result[1].value, -5);
});

test('equal values share the rank calculation used by the UI', () => {
  const data = analytics([
    row('MSFT', 2024, {revenue: '10.00'}),
    row('AAPL', 2024, {revenue: '1e1'}),
    row('AMZN', 2024, {revenue: '5'}),
  ]);

  const result = rankedValues(data, 'revenue', ['MSFT', 'AAPL', 'AMZN'], 2024);
  const ranks = result.map(item =>
    result.findIndex(other => compareDecimal(other.raw, item.raw) === 0) + 1,
  );

  assert.equal(result.map(item => item.ticker).join(','), 'AAPL,MSFT,AMZN');
  assert.equal(ranks.join(','), '1,1,3');
});

test('absent analytics and empty selection produce no fabricated ranking', () => {
  assert.equal(rankedValues(null, 'revenue', ['AAPL'], 2024).length, 0);
  assert.equal(rankedValues(analytics([]), 'revenue', ['AAPL'], 2024).length, 0);
  assert.equal(
    rankedValues(
      analytics([row('AAPL', 2024, {revenue: '100'})]),
      'revenue',
      [],
      2024,
    ).length,
    0,
  );
});

test('ranking does not mutate the persisted analytics object', () => {
  const data = analytics([
    row('AAPL', 2024, {revenue: '1'}),
    row('MSFT', 2024, {revenue: '2'}),
  ]);
  const before = JSON.stringify(data);

  rankedValues(data, 'revenue', ['AAPL', 'MSFT'], 2024);

  assert.equal(JSON.stringify(data), before);
});