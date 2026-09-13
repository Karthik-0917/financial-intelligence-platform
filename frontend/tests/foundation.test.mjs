import assert from 'node:assert/strict';
import {readFileSync, readdirSync} from 'node:fs';
import {createHash} from 'node:crypto';
import test from 'node:test';
import ts from 'typescript';
import postcss from 'postcss';

const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const style = read('src/style.css');
const ui = read('src/ui.tsx');
const main = read('src/main.tsx');
const expected = {
  canvas: '#F7F7F8', surface: '#FFFFFF', 'surface-muted': '#FAFAFB',
  'surface-inset': '#F2F3F5', 'border-subtle': '#EFF0F2', border: '#E2E4E8',
  'border-strong': '#858B96', 'text-primary': '#18191D',
  'text-secondary': '#5F646E', 'text-tertiary': '#707580',
  action: '#18191D', 'action-hover': '#303238', accent: '#4562E8',
  'accent-tint': '#EEF1FF', focus: '#3951D8', positive: '#16734D',
  'positive-soft': '#EAF8F0', negative: '#B33E43', 'negative-soft': '#FDEEEF',
  warning: '#8A5B0A', 'warning-soft': '#FFF5DF', info: '#3656B0',
  'info-soft': '#EEF3FF', evidence: '#176C64', 'evidence-soft': '#EAF6F3',
  research: '#4D5668', 'research-soft': '#F0F2F6', neutral: '#5F646E',
  'neutral-soft': '#F2F3F5', 'company-aapl': '#4562E8',
  'company-msft': '#23857C', 'company-amzn': '#B07B24',
};

test('canonical colors have exactly one declaration in the consumed stylesheet', () => {
  const root = postcss.parse(style);
  for (const [name, value] of Object.entries(expected)) {
    const found = [];
    root.walkDecls(`--fi-${name}`, declaration => found.push(declaration.value));
    assert.deepEqual(found, [value]);
  }
  assert.match(main, /import '\.\/style\.css'/);
});

test('all authoritative styles parse and all foundation variable references resolve', () => {
  const files = ['style.css', 'midnight.css', 'research-midnight.css', 'workspace-midnight.css'];
  const declarations = new Set();
  const references = new Set();
  for (const file of files) {
    const root = postcss.parse(read(`src/${file}`));
    root.walkDecls(declaration => {
      if (declaration.prop.startsWith('--fi-')) declarations.add(declaration.prop);
      for (const match of declaration.value.matchAll(/var\((--fi-[\w-]+)/g)) references.add(match[1]);
    });
  }
  for (const reference of references) assert.ok(declarations.has(reference), reference);
});

test('font bytes and license match verified official Inter 4.1 assets', () => {
  for (const [name, expectedHash] of [
    ['InterVariable-4.1.woff2', '693b77d4f32ee9b8bfc995589b5fad5e99adf2832738661f5402f9978429a8e3'],
    ['Inter-LICENSE.txt', '262481e844521b326f5ecd053e59b98c8b2da78c8ee1bdbb6e8174305e54935a'],
  ]) {
    const bytes = readFileSync(new URL(`../src/assets/fonts/${name}`, import.meta.url));
    assert.equal(createHash('sha256').update(bytes).digest('hex'), expectedHash);
  }
  assert.match(style, /@font-face\s*\{\s*font-family: Inter;/);
  assert.match(style, /src: url\('\.\/assets\/fonts\/InterVariable-4\.1\.woff2'\)/);
  assert.match(style, /font-family: Inter, ui-sans-serif/);
});

test('loading delay belongs only to CSS visual presentation, not request state', () => {
  const source = ts.createSourceFile('ui.tsx', ui, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const loading = source.statements.find(node => ts.isFunctionDeclaration(node) && node.name.text === 'Loading').getText(source);
  assert.match(loading, /className="sr-only">\{children\}/);
  assert.match(loading, /className="loading-visual" aria-hidden="true"/);
  assert.doesNotMatch(loading, /setTimeout|useEffect|useState|api\(/);
  assert.match(style, /--fi-loading-delay: 150ms/);
  assert.match(style, /animation: loading-appear.*var\(--fi-loading-delay\)/);
  assert.equal((style.match(/var\(--fi-loading-delay\)/g) || []).length, 1);
  assert.doesNotMatch(read('src/api.ts'), /fi-loading|150ms|loading-visual/);
});

test('reduced-motion presentation is visible without animation and no looping spinner remains', () => {
  assert.match(style, /prefers-reduced-motion: reduce/);
  assert.match(style, /\.loading-visual \{ opacity: 1; animation: none; \}/);
  assert.match(style, /animation: none !important; transition: none !important;/);
  assert.doesNotMatch(style, /animation: spin|linear infinite/);
});

function luminance(hex) {
  const values = hex.match(/[\da-f]{2}/gi).map(value => parseInt(value, 16) / 255)
    .map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
  return values[0] * .2126 + values[1] * .7152 + values[2] * .0722;
}
function contrast(first, second) {
  const values = [luminance(first), luminance(second)].sort((a, b) => b - a);
  return (values[0] + .05) / (values[1] + .05);
}

test('small navigation text and semantic status pairs meet 4.5:1 calculated contrast', () => {
  for (const background of [expected.surface, expected['surface-inset']]) {
    assert.ok(contrast(expected['text-secondary'], background) >= 4.5);
  }
  for (const background of [expected.action, expected['action-hover']]) {
    assert.ok(contrast(expected.surface, background) >= 4.5);
  }
  assert.ok(contrast(expected['text-secondary'], expected.canvas) >= 4.5);
  for (const name of ['positive', 'negative', 'warning', 'info', 'neutral']) {
    assert.ok(contrast(expected[name], expected[`${name}-soft`]) >= 4.5, name);
  }
  assert.match(style, /\.nav-label \{\s*color: var\(--fi-text-secondary\)/);
  assert.match(style, /box-shadow: 0 0 0 3px var\(--fi-surface\)/);
});

test('shell breakpoints, root size, mounted routes and native dialogs remain', () => {
  assert.match(style, /font-size: 15px;/);
  assert.match(style, /@media \(max-width: 960px\)/);
  assert.match(style, /\[hidden\] \{ display: none !important;/);
  assert.match(main, /addEventListener\('hashchange'/);
  for (const page of ['research', 'compare', 'evidence']) assert.ok(main.includes(`hidden={page !== '${page}'}`));
  assert.match(main, /showModal\(/);
  assert.doesNotMatch(style, /\bzoom\s*:|scale\(/);
});

test('authoritative entry does not import removed staging and source has no svg-prefixed files', () => {
  for (const file of ['main.tsx', 'ui.tsx', 'DesignSystem.tsx', 'ResearchWorkspace.tsx', 'EvaluationCenter.tsx', 'FinancialChart.tsx']) {
    assert.doesNotMatch(read(`src/${file}`), /from ['"]\.\/(?:Foundation|Overlays|motion|designTokens)['"]/);
  }
  for (const name of readdirSync(new URL('../src/', import.meta.url))) assert.ok(!name.toLowerCase().startsWith('svg'));
  assert.match(read('index.html'), /src="\/src\/main\.tsx"/);
});


test('shell has one authoritative geometry owner and intentional mobile framing', () => {
  const root = postcss.parse(style);
  const rule = selector => {
    const matches = [];
    root.walkRules(selector, node => { if (node.parent.type === 'root') matches.push(node); });
    assert.equal(matches.length, 1, selector);
    return Object.fromEntries(matches[0].nodes.filter(node => node.type === 'decl').map(node => [node.prop, node.value]));
  };
  assert.equal(rule('.app.app .sidebar').background, 'var(--fi-surface)');
  assert.equal(rule('.app.app .topbar').display, 'grid');
  assert.equal(rule('.app.app .page-heading')['flex-wrap'], 'wrap');
  assert.equal(rule('.app.app :is(.sidebar, .navigation-dialog) nav button.active').background, 'var(--fi-action)');
  assert.equal(rule('.app.app :is(.sidebar, .navigation-dialog) nav button')['min-height'], '36px');
  assert.match(style, /--sidebar-width: 216px/);
  assert.match(style, /grid-template-columns: minmax\(0, 1fr\) auto/);
  assert.match(style, /\.command-trigger \{ grid-column: 1 \/ -1; grid-row: 2;/);
  assert.match(style, /@media \(pointer: coarse\)/);
  assert.doesNotMatch(style, /overflow-x: hidden/);
});

test('all eight routes and authoritative local imports remain wired', () => {
  const source = ts.createSourceFile('main.tsx', main, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const pages = source.statements.find(node => ts.isVariableStatement(node) && node.declarationList.declarations.some(declaration => declaration.name.getText(source) === 'PAGES'));
  const ids = [...pages.getText(source).matchAll(/id: '([^']+)'/g)].map(match => match[1]);
  assert.deepEqual(ids, ['overview', 'research', 'compare', 'filings', 'financials', 'evidence', 'evaluation', 'methodology']);
  assert.match(main, /window\.location\.hash = next/);
  assert.match(main, /aria-current=\{page === item\.id \? 'page' : undefined\}/);
  for (const filename of readdirSync(new URL('../src/', import.meta.url)).filter(name => /\.tsx?$/.test(name))) {
    const text = read(`src/${filename}`);
    for (const match of text.matchAll(/(?:from\s*|import\s*\(?\s*)['"](\.\/[^'"]+)['"]/g)) {
      const path = match[1].slice(2);
      const names = readdirSync(new URL('../src/', import.meta.url));
      assert.ok(names.some(name => name === path || name === `${path}.ts` || name === `${path}.tsx`), `${filename}: ${path}`);
    }
  }
});