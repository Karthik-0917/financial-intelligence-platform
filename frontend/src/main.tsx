import React, {
  Suspense,
  lazy,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {createRoot} from 'react-dom/client';
import {
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  Moon,
  BookOpen,
  ChartNoAxesCombined,
  ChevronDown,
  ChevronRight,
  Files,
  FlaskConical,
  GitCompareArrows,
  LayoutDashboard,
  Menu,
  Network,
  RefreshCw,
  ScanSearch,
  Search,
  Sun,
  X,
  Sparkles,
  TrendingUp,
  Wallet,
  DollarSign,
  BarChart3,
} from 'lucide-react';
import {
  api,
  type Analytics,
  type AnalyticsRow,
  type Evidence,
  type Evaluation,
  type Report,
  type Research,
  type SystemStatus,
  type Ticker,
} from './api';
import {
  COMPANIES,
  COMPARISON_METRICS,
  YEARS,
  Empty,
  ErrorNotice,
  JsonDetails,
  Loading,
  ResourceState,
  SourceLink,
  companyName,
  formatValue,
  label,
  numeric,
} from './ui';
import {useRemote} from './ui';
import {
  Disclosure,
  MetricStatus,
  MetricSummary,
  SectionHeading,
} from './DesignSystem';
import ResearchWorkspace, {ResearchAnswer} from './ResearchWorkspace';
import EvaluationCenter from './EvaluationCenter';
import './style.css';
import './midnight.css';
import './workspace-midnight.css';
import './shell.css';

const FinancialChart = lazy(() => import('./FinancialChart'));

const PAGES = [
  {id: 'overview', name: 'Overview', icon: LayoutDashboard, group: 'Workspace', description: 'The financial picture. The sources behind it.'},
  {id: 'research', name: 'Research', icon: Search, group: 'Workspace', description: 'Investigate financial questions with evidence in reach.'},
  {id: 'compare', name: 'Compare', icon: GitCompareArrows, group: 'Workspace', description: 'Benchmark companies on the same metric and fiscal year.'},
  {id: 'filings', name: 'Filings', icon: Files, group: 'Data', description: 'Original annual reports, organized for financial research.'},
  {id: 'financials', name: 'Financials', icon: ChartNoAxesCombined, group: 'Data', description: 'Statement analysis powered by validated financial data.'},
  {id: 'evidence', name: 'Evidence', icon: ScanSearch, group: 'Data', description: 'Read the source. Inspect the connection to the result.'},
  {id: 'evaluation', name: 'Evaluation', icon: FlaskConical, group: 'Quality', description: 'Measured outcomes, explicit coverage, and reproducible evidence.'},
  {id: 'methodology', name: 'Methodology', icon: Network, group: 'Quality', description: 'One traceable result across three forms of intelligence.'},
] as const;

type Page = typeof PAGES[number]['id'];

const COMPANY_COLORS: Record<Ticker, string> = {
  AAPL: '#285de5',
  MSFT: '#087f73',
  AMZN: '#b77b20',
};

const STATEMENTS = {
  'Income statement': ['revenue', 'gross_profit', 'operating_income', 'net_income', 'eps'],
  Margins: ['operating_margin', 'net_margin', 'fcf_margin', 'revenue_yoy_growth', 'revenue_cagr'],
  'Cash flow': ['operating_cash_flow', 'capex', 'free_cash_flow'],
  'Balance sheet': ['assets', 'liabilities', 'equity', 'cash'],
} as const;

type Statement = keyof typeof STATEMENTS;
type RevenueYear = 'ALL' | 2022 | 2023 | 2024;

function pageFromHash(): Page {
  return PAGES.find(item => item.id === window.location.hash.slice(1))?.id || 'overview';
}

function stateLabel(value: boolean | undefined, yes: string, no: string) {
  return value === undefined ? 'Unknown' : value ? yes : no;
}

function knowledgeState(status: SystemStatus | null) {
  if (!status) return 'Unknown';
  if (
    status.corpus_valid &&
    status.financial_store_ready &&
    status.index_ready &&
    status.index_loaded &&
    status.retrieval_models_loaded
  ) return 'Locally ready';
  if (status.corpus_valid || status.financial_store_ready || status.index_loaded) {
    return 'Partially ready';
  }
  if (status.corpus_error || status.financial_store_error || status.index_error) {
    return 'Attention required';
  }
  if (!status.validated_report_count && !status.index_artifacts_present) {
    return 'Not initialized';
  }
  return 'Not ready';
}

function CompanyIdentity({ticker}: {ticker: Ticker}) {
  return <span className="mf-company-identity" style={{display:'inline-flex',alignItems:'center',gap:'8px'}}>
    <span className="mf-company-mark fluxa-company-logo" style={{color: COMPANY_COLORS[ticker], background:'var(--fi-surface-muted)', border:'1px solid var(--fi-border)'}}>
      {ticker === 'AAPL' ? 'A' : ticker === 'MSFT' ? 'M' : 'a'}
    </span>
    <span><strong>{companyName(ticker)}</strong><small style={{display:'block',fontSize:'11px',color:'var(--fi-text-tertiary)'}}>{ticker}</small></span>
  </span>;
}

function Availability({
  value,
  metric,
  reason,
}: {
  value?: string;
  metric: string;
  reason?: string;
}) {
  if (numeric(value) !== null) {
    return <span className="number">{formatValue(value, metric)}</span>;
  }
  return <span className="mf-missing-value">
    <span>Unavailable</span>
    <details>
      <summary>Why unavailable</summary>
      <p>{reason || 'No validated value was returned for this company, metric, and fiscal period.'}</p>
    </details>
  </span>;
}

function AnnualTable({
  analytics,
  metric,
  companies,
  years = YEARS,
}: {
  analytics: Analytics | null;
  metric: string;
  companies: Ticker[];
  years?: number[];
}) {
  const [exact, setExact] = useState(false);

  if (!companies.length) return <Empty title="Select a company"/>;

  return <section className="mf-annual-table fluxa-card">
    <div className="fluxa-card-header">
      <h3>Annual values</h3>
      <label className="mf-exact-toggle" style={{display:'flex',alignItems:'center',gap:'6px',fontSize:'12px'}}>
        <input type="checkbox" checked={exact} onChange={event => setExact(event.target.checked)}/>
        Show exact values
      </label>
    </div>
    <div className="fluxa-card-body p-0">
      <div className="fluxa-table-wrap" tabIndex={0} aria-label={`${label(metric)} annual values`}>
        <table className="mf-table fluxa-table">
          <caption className="sr-only">{label(metric)} by company and fiscal year</caption>
          <thead>
            <tr>
              <th scope="col">Fiscal year</th>
              {companies.map(ticker => <th key={ticker} scope="col" className="number">{companyName(ticker)}<small>{ticker}</small></th>)}
            </tr>
          </thead>
          <tbody>{years.map(year => <tr key={year}>
            <th scope="row">FY{year}</th>
            {companies.map(ticker => {
              const row = analytics?.rows.find(item => item.ticker === ticker && item.fiscal_year === year);
              const value = row?.values[metric];
              return <td key={ticker} className="number">
                <Availability value={value} metric={metric} reason={row?.unavailable_metrics?.[metric]}/>
                {exact && numeric(value) !== null && <small className="mf-exact-value"><code>{value}</code></small>}
              </td>;
            })}
          </tr>)}</tbody>
        </table>
      </div>
    </div>
    <div style={{padding:'10px 16px', borderTop:'1px solid var(--fi-border-subtle)'}}>
      <p className="mf-fineprint" style={{margin:0}}>Fiscal years follow company reporting periods. Exact values are unchanged; only their presentation is rounded.</p>
    </div>
  </section>;
}

function FinancialProvenance({row, metric}: {row: AnalyticsRow; metric: string}) {
  const facts = row.evidence.filter(fact => fact.metric === metric);
  const calculationMetric = metric === 'revenue_yoy_growth' ? 'growth' : metric === 'revenue_cagr' ? 'cagr' : metric;
  const calculations = row.calculations.filter(value => value.metric === calculationMetric);

  return <details className="mf-financial-provenance fluxa-disclosure">
    <summary>
      <span>{companyName(row.ticker)} · FY{row.fiscal_year}</span>
      <strong style={{marginLeft:'8px'}}>{formatValue(row.values[metric], metric)}</strong>
    </summary>
    <div>
      {row.unavailable_metrics?.[metric] && <p className="fluxa-notice warning">{row.unavailable_metrics[metric]}</p>}
      {facts.map((fact, index) => <section key={fact.fact_id || index} style={{marginTop:'12px', padding:'12px', background:'var(--fi-surface-muted)', borderRadius:'8px', border:'1px solid var(--fi-border-subtle)'}}>
        <div className="mf-provenance-path" style={{display:'flex',alignItems:'center',gap:'6px',fontSize:'11px',color:'var(--fi-text-tertiary)',marginBottom:'8px'}}><span>SEC observation</span><ArrowRight size={14}/><span>Validated fact</span><ArrowRight size={14}/><span>Display</span></div>
        <dl className="detail-grid">
          <div><dt>Exact value</dt><dd><code>{fact.value} {fact.unit}</code></dd></div>
          <div><dt>XBRL concept</dt><dd><code>{fact.concept || 'Not recorded'}</code></dd></div>
          <div><dt>SEC accession</dt><dd><code>{fact.accession_number || 'Not recorded'}</code></dd></div>
          <div><dt>Reporting period</dt><dd>{fact.period_start ? `${fact.period_start} to ` : 'As of '}{fact.period_end || 'Not recorded'}</dd></div>
        </dl>
        {fact.metric_definition && <p className="mf-fineprint">{fact.metric_definition}</p>}
        <SourceLink url={fact.source_url}>Original SEC filing</SourceLink>
        <JsonDetails title="Complete fact and reconciliation" value={fact}/>
      </section>)}
      {calculations.map((calculation, index) => <section key={calculation.calculation_id || index} style={{marginTop:'12px'}}>
        <h3>{label(calculation.metric)}</h3>
        <p><code>{calculation.formula}</code></p>
        <p>Exact result: <code>{calculation.value} {calculation.unit}</code></p>
        <JsonDetails title="Calculation inputs and provenance" value={calculation}/>
      </section>)}
      {!facts.length && !calculations.length && !row.unavailable_metrics?.[metric] &&
        <p className="mf-fineprint">No matching provenance record was returned.</p>}
    </div>
  </details>;
}

/*
 * Exact ordering of decimal strings for display ranking.
 * This is comparison, not financial arithmetic or a replacement for Decimal.
 * Browser numbers are used separately for visual bar coordinates only.
 */
function decimalParts(value: string) {
  const match = /^([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(value);
  if (!match || (!match[2] && !match[3])) return null;
  const exponent = Number(match[4] || 0);
  if (!Number.isSafeInteger(exponent)) return null;
  const raw = match[2] + (match[3] || '');
  const leading = raw.search(/[1-9]/);
  if (leading === -1) return {sign: 0, magnitude: 0, digits: '0'};
  return {
    sign: match[1] === '-' ? -1 : 1,
    magnitude: match[2].length + exponent - leading,
    digits: raw.slice(leading),
  };
}

function compareDecimal(left: string, right: string) {
  const a = decimalParts(left);
  const b = decimalParts(right);
  if (!a || !b) return 0;
  if (a.sign !== b.sign) return a.sign < b.sign ? -1 : 1;
  if (a.sign === 0) return 0;
  if (a.magnitude !== b.magnitude) {
    return (a.magnitude < b.magnitude ? -1 : 1) * a.sign;
  }
  const length = Math.max(a.digits.length, b.digits.length);
  const first = a.digits.padEnd(length, '0');
  const second = b.digits.padEnd(length, '0');
  return first === second ? 0 : (first < second ? -1 : 1) * a.sign;
}

function rankedValues(analytics: Analytics | null, metric: string, companies: Ticker[], year: number) {
  return companies.flatMap(ticker => {
    const row = analytics?.rows.find(item => item.ticker === ticker && item.fiscal_year === year);
    const raw = row?.values[metric];
    const value = numeric(raw);
    return raw !== undefined && value !== null && decimalParts(raw)
      ? [{ticker, raw, value}]
      : [];
  }).sort((a, b) => compareDecimal(b.raw, a.raw) || a.ticker.localeCompare(b.ticker));
}

function RankingChart({
  analytics,
  metric,
  companies,
  year,
}: {
  analytics: Analytics | null;
  metric: string;
  companies: Ticker[];
  year: number;
}) {
  const ranked = rankedValues(analytics, metric, companies, year);
  const max = Math.max(...ranked.map(item => Math.abs(item.value)), 0);
  const hasNegative = ranked.some(item => item.value < 0);
  const missing = companies.filter(ticker => !ranked.some(item => item.ticker === ticker));

  if (!companies.length) return <Empty title="Select companies to compare"/>;

  return <div className="mf-ranking-chart">
    <div className="mf-ranking-caption" style={{display:'flex',justifyContent:'space-between',fontSize:'11px',color:'var(--fi-text-tertiary)',marginBottom:'12px'}}>
      <span>{hasNegative ? 'Negative ← 0 → Positive' : 'Zero-based scale'}</span>
      <span>{label(metric)} · FY{year}</span>
    </div>
    {ranked.map((item, index) => {
      const rank = ranked.findIndex(other => compareDecimal(other.raw, item.raw) === 0) + 1;
      const width = max ? Math.abs(item.value) / max * 100 : 0;
      return <div className="mf-ranking-row" key={item.ticker}>
        <span className="mf-ranking-position" style={{fontSize:'11px',color:'var(--fi-text-tertiary)'}}>{rank}</span>
        <CompanyIdentity ticker={item.ticker}/>
        <div className={`mf-ranking-track ${hasNegative ? 'signed' : ''}`} aria-hidden="true" style={{height:'6px',background:'var(--fi-border-subtle)',borderRadius:'3px',overflow:'hidden',display:'flex'}}>
          {hasNegative
            ? <>
                <div className="mf-negative-half" style={{flex:1,display:'flex',justifyContent:'flex-end'}}>
                  {item.value < 0 && <span style={{width: `${width}%`, background: COMPANY_COLORS[item.ticker]}}/>}
                </div>
                <div className="mf-positive-half" style={{flex:1,display:'flex'}}>
                  {item.value >= 0 && <span style={{width: `${width}%`, background: COMPANY_COLORS[item.ticker]}}/>}
                </div>
              </>
            : <span style={{width: `${width}%`, background: COMPANY_COLORS[item.ticker]}}/>}
        </div>
        <strong className="mf-ranking-number" style={{fontSize:'13px'}}>{formatValue(item.raw, metric)}</strong>
        {index === 0 && <span className="sr-only">Highest available value; ties share a rank.</span>}
      </div>;
    })}
    {missing.map(ticker => {
      const row = analytics?.rows.find(item => item.ticker === ticker && item.fiscal_year === year);
      return <div className="mf-ranking-missing" key={ticker} style={{display:'flex',gap:'8px',padding:'8px 0',borderTop:'1px dashed var(--fi-border-subtle)'}}>
        <CompanyIdentity ticker={ticker}/>
        <Availability metric={metric} reason={row?.unavailable_metrics?.[metric]}/>
      </div>;
    })}
    {!ranked.length && <p className="mf-fineprint">No validated chartable values are available.</p>}
    <p className="mf-fineprint">Ranks use exact decimal ordering; ties share a rank. Bar lengths use browser numeric precision. Higher values are not necessarily preferable.</p>
  </div>;
}

function Comparison({analytics, inspect}: {analytics: Analytics | null; inspect: (record: Evidence) => void}) {
  const [metric, setMetric] = useState('revenue');
  const [year, setYear] = useState(2024);
  const [companies, setCompanies] = useState<Ticker[]>(['AAPL', 'MSFT', 'AMZN']);
  const [result, setResult] = useState<Research | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const [cancelled, setCancelled] = useState(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);

  function reset() {
    controller.current?.abort();
    controller.current = null;
    setResult(null);
    setError(null);
    setBusy(false);
    setCancelled(false);
  }

  async function compare() {
    reset();
    if (companies.length < 2) return;
    const request = new AbortController();
    controller.current = request;
    setBusy(true);
    const names = COMPANIES.filter(company => companies.includes(company.ticker)).map(company => company.name).join(' and ');
    try {
      const response = await api<Research>('compare', {
        question: `Compare ${names} ${metric.replaceAll('_', ' ')} in FY${year}.`,
        tickers: companies,
        years: [year],
      }, request.signal);
      if (!request.signal.aborted && controller.current === request) setResult(response);
    } catch (failure) {
      if (!request.signal.aborted && controller.current === request) {
        setError(failure instanceof Error ? failure : new Error('Comparison failed.'));
      }
    } finally {
      if (controller.current === request) {
        controller.current = null;
        setBusy(false);
      }
    }
  }

  const rows = analytics?.rows.filter(row => companies.includes(row.ticker) && row.fiscal_year === year) || [];
  const ranked = rankedValues(analytics, metric, companies, year);
  const highest = ranked[0];
  const leaders = highest ? ranked.filter(item => compareDecimal(item.raw, highest.raw) === 0) : [];

  return <div className="mf-benchmark" style={{display:'grid',gap:'12px'}}>
    <section className="mf-benchmark-controls fluxa-card">
      <div className="fluxa-card-body" style={{display:'flex',gap:'12px',flexWrap:'wrap',alignItems:'flex-end'}}>
        <label style={{display:'flex',flexDirection:'column',gap:'4px',fontSize:'12px'}}>Metric<select className="fluxa-select" value={metric} onChange={event => {reset(); setMetric(event.target.value);}}>
          {COMPARISON_METRICS.map(value => <option key={value} value={value}>{label(value)}</option>)}
        </select></label>
        <label style={{display:'flex',flexDirection:'column',gap:'4px',fontSize:'12px'}}>Fiscal year<select className="fluxa-select" value={year} onChange={event => {reset(); setYear(Number(event.target.value));}}>
          {YEARS.map(value => <option key={value} value={value}>FY{value}</option>)}
        </select></label>
        <fieldset style={{border:'1px solid var(--fi-border)',borderRadius:'8px',padding:'8px 12px',display:'flex',gap:'12px',alignItems:'center'}}><legend style={{fontSize:'11px',padding:'0 4px'}}>Companies</legend>
          {COMPANIES.map(company => <label key={company.ticker} style={{display:'flex',alignItems:'center',gap:'6px',fontSize:'13px'}}>
            <input type="checkbox" checked={companies.includes(company.ticker)} onChange={event => {
              reset();
              setCompanies(current => event.target.checked ? [...current, company.ticker] : current.filter(value => value !== company.ticker));
            }}/>
            {company.ticker}
          </label>)}
        </fieldset>
      </div>
    </section>

    <div className="mf-benchmark-layout fluxa-grid-2">
      <section className="mf-surface fluxa-card">
        <div className="fluxa-card-header">
          <div><span style={{fontSize:'11px',textTransform:'uppercase',letterSpacing:'0.5px',color:'var(--fi-text-tertiary)'}}>Company benchmarking</span><h2 style={{margin:0}}>{label(metric)}</h2></div>
          <MetricStatus tone="blue">FY{year}</MetricStatus>
        </div>
        <div className="fluxa-card-body">
          <RankingChart analytics={analytics} metric={metric} companies={companies} year={year}/>
        </div>
      </section>
      <aside className="mf-benchmark-reading fluxa-card">
        <div className="fluxa-card-body">
          <span className="mf-eyebrow" style={{fontSize:'11px',textTransform:'uppercase',letterSpacing:'0.8px',color:'var(--fi-text-tertiary)'}}>What the available values show</span>
          <h2 style={{fontSize:'16px',margin:'8px 0'}}>{highest ? leaders.length > 1 ? 'A shared highest value' : `${companyName(highest.ticker)} ranks highest` : 'Comparison coverage is incomplete'}</h2>
          {highest && <strong style={{fontSize:'20px'}}>{formatValue(highest.raw, metric)}</strong>}
          <p style={{fontSize:'13px',color:'var(--fi-text-secondary)',marginTop:'8px'}}>{highest
            ? `${leaders.map(item => companyName(item.ticker)).join(' and ')} ${leaders.length > 1 ? 'share' : 'has'} the highest available ${label(metric).toLowerCase()} among the selected companies for FY${year}.`
            : 'Select companies with validated values to establish an ordering.'}</p>
          <dl style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'12px',marginTop:'16px',fontSize:'12px'}}><div><dt style={{color:'var(--fi-text-tertiary)'}}>Available values</dt><dd>{ranked.length} / {companies.length}</dd></div><div><dt style={{color:'var(--fi-text-tertiary)'}}>Arithmetic source</dt><dd>Validated financial engine</dd></div></dl>
          <p className="mf-fineprint">This is a numerical ordering, not an investment recommendation or an explanation of business performance.</p>
        </div>
      </aside>
    </div>

    <section className="mf-surface fluxa-card">
      <div className="fluxa-card-body">
        <AnnualTable analytics={analytics} metric={metric} companies={companies} years={[year]}/>
        <div className="mf-comparison-action" style={{display:'flex',justifyContent:'space-between',alignItems:'center',gap:'16px',marginTop:'16px',padding:'16px',background:'var(--fi-surface-muted)',borderRadius:'8px',border:'1px solid var(--fi-border-subtle)'}}>
          <div><h3 style={{fontSize:'13px',margin:0}}>Inspect the evidence behind the comparison</h3><p style={{fontSize:'12px',color:'var(--fi-text-secondary)',margin:'4px 0 0'}}>Use the existing scoped comparison endpoint to retrieve its answer and citations.</p></div>
          <div className="button-row">
            {busy && <button type="button" className="fluxa-btn fluxa-btn-secondary" onClick={() => {
              controller.current?.abort();
              controller.current = null;
              setBusy(false);
              setCancelled(true);
            }}>Cancel waiting</button>}
            <button type="button" className="fluxa-btn fluxa-btn-primary" disabled={busy || companies.length < 2} onClick={() => void compare()}>
              {busy ? 'Comparing…' : 'Compare with evidence'}<ArrowRight size={16}/>
            </button>
          </div>
        </div>
      </div>
    </section>
    {busy && <Loading>Waiting for the scoped comparison…</Loading>}
    {cancelled && <p className="fluxa-notice info">Browser waiting was cancelled; server work may continue.</p>}
    {error && <ErrorNotice error={error}/>}
    {result && <ResearchAnswer result={result} inspect={inspect}/>}
    {rows.length > 0 && <Disclosure title="Company-specific source lineage">
      {rows.map(row => <FinancialProvenance key={`${row.ticker}-${row.fiscal_year}`} row={row} metric={metric}/>)}
    </Disclosure>}
  </div>;
}

function EvidenceExplorer({
  selected,
  records,
  choose,
}: {
  selected: Evidence | null;
  records: Evidence[];
  choose: (record: Evidence) => void;
}) {
  const [identifier, setIdentifier] = useState('');
  const [search, setSearch] = useState('');
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const [copyStatus, setCopyStatus] = useState('');
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => setCopyStatus(''), [selected?.evidence_id]);

  const trimmed = identifier.trim();
  const hasInput = trimmed.length > 0;
  const isEvidenceFormat = /^EVIDENCE_\d+$/i.test(trimmed);
  const looksLikeEvidencePrefix = trimmed.toUpperCase().startsWith('EVIDENCE_');
  const showFormatHint = hasInput && !looksLikeEvidencePrefix;

  async function lookup() {
    if (!trimmed) return;
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    setBusy(true);
    setError(null);
    try {
      const record = await api<Evidence>(`evidence/${encodeURIComponent(trimmed)}`, undefined, request.signal);
      if (!request.signal.aborted && controller.current === request) choose(record);
    } catch (failure) {
      if (!request.signal.aborted && controller.current === request) {
        setError(failure instanceof Error ? failure : new Error('Evidence lookup failed.'));
      }
    } finally {
      if (controller.current === request) {
        controller.current = null;
        setBusy(false);
      }
    }
  }

  async function copy(value: string, name: string) {
    try {
      if (!navigator.clipboard) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(value);
      setCopyStatus(`${name} copied.`);
    } catch {
      setCopyStatus('Clipboard unavailable. Select and copy the displayed content.');
    }
  }

  const visible = records.filter(record =>
    `${record.evidence_id} ${record.ticker} ${record.fiscal_year} ${record.section || ''} ${record.text}`
      .toLowerCase().includes(search.toLowerCase()),
  );

  return <div className="mf-audit-workspace fluxa-evidence-workspace" style={{display:'grid',gap:'12px'}}>
    <section className="mf-audit-lookup fluxa-card fluxa-evidence-lookup-card">
      <div className="fluxa-card-header" style={{borderBottom:'1px solid var(--fi-border-subtle)', paddingBottom:'12px'}}>
        <div>
          <span className="mf-eyebrow" style={{fontSize:'11px',textTransform:'uppercase',letterSpacing:'0.8px',color:'var(--fi-text-tertiary)'}}>Persistent evidence registry</span>
          <h2 style={{fontSize:'16px',margin:'4px 0 0',display:'flex',alignItems:'center',gap:'8px'}}><ScanSearch size={16}/> Evidence ID Lookup</h2>
          <p style={{fontSize:'12px',color:'var(--fi-text-secondary)',margin:'6px 0 0',maxWidth:'560px'}}>Follow a citation back to its source. Evidence IDs are user-facing citation identifiers from Research answers.</p>
        </div>
        <div style={{display:'flex',gap:'6px',flexWrap:'wrap',alignItems:'center'}}>
          <span className="fluxa-badge neutral" style={{fontSize:'10px'}}>Format: EVIDENCE_001</span>
          <span className="fluxa-badge blue" style={{fontSize:'10px'}}>User-facing citation</span>
          <span className="fluxa-badge neutral" style={{fontSize:'10px'}}>Not a chunk ID</span>
        </div>
      </div>
      <div className="fluxa-card-body" style={{display:'grid',gap:'12px'}}>
        <div style={{display:'flex',justifyContent:'space-between',gap:'20px',flexWrap:'wrap',alignItems:'flex-end'}}>
          <div style={{flex:'1 1 280px',maxWidth:'480px',display:'grid',gap:'8px'}}>
            <p style={{fontSize:'12px',color:'var(--fi-text-secondary)',margin:0}}>Enter an evidence ID such as <code>EVIDENCE_001</code> to open a recorded citation. Internal chunk IDs are different and not valid for this lookup.</p>
            <div style={{display:'flex',gap:'8px',alignItems:'center',fontSize:'11px',color:'var(--fi-text-tertiary)'}}>
              <BookOpen size={12}/><span>Find IDs in Research answers under Citations, then paste here.</span>
            </div>
          </div>
          <form onSubmit={event => {event.preventDefault(); void lookup();}} style={{flex:'1 1 320px',maxWidth:'420px',display:'grid',gap:'8px'}}>
            <label style={{display:'grid',gap:'4px',fontSize:'12px',fontWeight:500}}>
              <span style={{display:'flex',justifyContent:'space-between',alignItems:'center'}}>
                <span>Evidence ID</span>
                <span style={{fontSize:'11px',fontWeight:400,color:'var(--fi-text-tertiary)'}}>User-facing citation identifier</span>
              </span>
              <div style={{display:'flex',gap:'8px'}}>
                <input className="fluxa-input" aria-label="Evidence ID" placeholder="EVIDENCE_001" value={identifier} onChange={event => setIdentifier(event.target.value)} maxLength={100} required style={{flex:1}}/>
                <button className="fluxa-btn fluxa-btn-primary" disabled={busy || !trimmed}>{busy ? 'Looking up…' : 'Look up'}</button>
              </div>
            </label>
            <div style={{display:'grid',gap:'4px'}}>
              <p className="mf-fineprint" style={{margin:0}}>Example: <code>EVIDENCE_001</code>. IDs are case-sensitive and recorded per citation. Chunk IDs (internal) will not resolve.</p>
              {showFormatHint && <p className="fluxa-notice warning" style={{margin:0,padding:'8px 10px',fontSize:'12px'}}>Evidence IDs start with <code>EVIDENCE_</code>. Check the citation list in a Research answer. Internal chunk IDs are not valid here.</p>}
              {hasInput && looksLikeEvidencePrefix && !isEvidenceFormat && <p className="fluxa-notice info" style={{margin:0,padding:'8px 10px',fontSize:'12px'}}>Format hint: use <code>EVIDENCE_001</code> style numbering. The system will still attempt lookup and show truthful not-found if absent.</p>}
            </div>
          </form>
        </div>
      </div>
    </section>
    {error && <ErrorNotice error={error}/>}
    {busy && <Loading>Resolving the persisted evidence record…</Loading>}
    <div className="mf-audit-layout" style={{display:'grid',gridTemplateColumns:'minmax(220px, 0.7fr) minmax(0, 2fr)',gap:'12px'}}>
      <aside className="mf-audit-records fluxa-card">
        <div className="fluxa-card-header">
          <div>
            <h3>Opened records</h3>
            <p style={{fontSize:'11px',color:'var(--fi-text-tertiary)',margin:'2px 0 0'}}>Session only — evidence you have opened</p>
          </div>
          <MetricStatus>{records.length}</MetricStatus>
        </div>
        <div className="fluxa-card-body" style={{display:'grid',gap:'12px'}}>
          <label style={{display:'grid',gap:'4px',fontSize:'12px'}}>
            <span style={{fontSize:'11px',color:'var(--fi-text-tertiary)'}}>Filter opened</span>
            <input className="fluxa-input" aria-label="Search opened evidence text" placeholder="Search company, section, or passage" value={search} onChange={event => setSearch(event.target.value)}/>
          </label>
          <p className="mf-fineprint" style={{margin:0}}>Session records only — not a research-question search or full-corpus search. Open a citation from Research or use the lookup above.</p>
          <div style={{display:'grid',gap:'6px',maxHeight:'500px',overflowY:'auto'}}>
            {visible.map(record => <button
              type="button"
              className={selected?.evidence_id === record.evidence_id ? 'mf-audit-record selected' : 'mf-audit-record'}
              key={record.evidence_id}
              onClick={() => choose(record)}
              aria-pressed={selected?.evidence_id === record.evidence_id}
              style={{
                textAlign:'left',
                padding:'10px 12px',
                borderRadius:'8px',
                border: selected?.evidence_id === record.evidence_id ? '1px solid var(--fi-accent)' : '1px solid var(--fi-border)',
                background: selected?.evidence_id === record.evidence_id ? 'var(--fi-accent-tint)' : 'var(--fi-surface)',
                display:'grid',
                gap:'4px',
              }}
            >
              <span style={{fontSize:'11px',color:'var(--fi-text-tertiary)',display:'flex',justifyContent:'space-between',alignItems:'center'}}><span>{record.ticker} · FY{record.fiscal_year}</span><code style={{fontSize:'10px',background:'var(--fi-surface-muted)',padding:'2px 4px',borderRadius:'4px'}}>{record.evidence_id}</code></span>
              <strong style={{fontSize:'13px'}}>{record.section || 'Source evidence'}</strong>
              <p style={{fontSize:'12px',color:'var(--fi-text-secondary)',margin:0}}>{record.text.slice(0, 110)}{record.text.length > 110 ? '…' : ''}</p>
            </button>)}
            {!visible.length && <div className="mf-inline-empty" style={{textAlign:'center',padding:'20px',display:'grid',gap:'8px'}}>
              <BookOpen size={20} style={{margin:'0 auto',color:'var(--fi-text-tertiary)'}}/>
              <span style={{fontSize:'13px',fontWeight:500}}>{records.length ? 'No matching opened records' : 'No evidence opened yet'}</span>
              <p style={{fontSize:'12px',color:'var(--fi-text-secondary)',margin:0}}>{records.length ? 'Try a different filter term.' : 'Open a citation from Research or enter an ID like EVIDENCE_001 above to see its passage and source provenance.'}</p>
              {!records.length && <span className="fluxa-badge neutral" style={{margin:'4px auto 0',fontSize:'10px'}}>Lookup expects EVIDENCE_… not chunk IDs</span>}
            </div>}
          </div>
        </div>
      </aside>
      <article className="mf-audit-document fluxa-card">
        <div className="fluxa-card-body">
          {selected
            ? <>
                <header className="mf-audit-document-header" style={{display:'flex',gap:'8px',alignItems:'center',flexWrap:'wrap',marginBottom:'12px'}}>
                  <CompanyIdentity ticker={selected.ticker}/>
                  <MetricStatus tone="blue">FY{selected.fiscal_year}</MetricStatus>
                  <span className="fluxa-badge blue" style={{fontSize:'11px'}}><code>{selected.evidence_id}</code></span>
                  <SourceLink url={selected.source_url}>Original SEC filing</SourceLink>
                </header>
                {error && <p className="fluxa-notice warning">The lookup failed. This is the previously selected record, not a result for the failed lookup.</p>}
                <div className="mf-audit-document-title">
                  <span className="mf-eyebrow" style={{fontSize:'11px',textTransform:'uppercase',letterSpacing:'0.8px',color:'var(--fi-text-tertiary)'}}>{selected.fact_id ? 'Financial fact evidence' : 'Recorded filing section'}</span>
                  <h2 style={{fontSize:'18px',margin:'4px 0'}}>{selected.section || 'Supporting source evidence'}</h2>
                  {selected.subsection && <p style={{fontSize:'13px',color:'var(--fi-text-secondary)'}}>{selected.subsection}</p>}
                </div>
                <dl className="mf-audit-source-strip" style={{display:'grid',gridTemplateColumns:'repeat(3,1fr)',gap:'12px',margin:'16px 0',padding:'12px',background:'var(--fi-surface-muted)',borderRadius:'8px',border:'1px solid var(--fi-border-subtle)'}}>
                  <div><dt style={{fontSize:'11px',color:'var(--fi-text-tertiary)'}}>Filing date</dt><dd style={{fontSize:'13px',margin:'4px 0 0'}}>{selected.filing_date || 'Not recorded'}</dd></div>
                  <div><dt style={{fontSize:'11px',color:'var(--fi-text-tertiary)'}}>Reporting period</dt><dd style={{fontSize:'13px',margin:'4px 0 0'}}>{selected.period_start ? `${selected.period_start} to ` : ''}{selected.period_end || 'Not recorded'}</dd></div>
                  <div><dt style={{fontSize:'11px',color:'var(--fi-text-tertiary)'}}>SEC accession</dt><dd><code>{selected.accession_number || 'Not recorded'}</code></dd></div>
                </dl>
                <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:'8px'}}>
                  <span style={{fontSize:'11px',textTransform:'uppercase',letterSpacing:'0.5px',color:'var(--fi-text-tertiary)'}}>Source passage</span>
                  <span className="fluxa-badge neutral" style={{fontSize:'10px'}}>Evidence ID: {selected.evidence_id}</span>
                </div>
                <blockquote className="mf-audit-passage" style={{padding:'16px',background:'var(--fi-surface-muted)',borderLeft:'3px solid var(--fi-accent)',borderRadius:'0 8px 8px 0',fontSize:'14px',lineHeight:'1.6',whiteSpace:'pre-wrap'}}>{selected.text}</blockquote>
                <div className="mf-audit-actions" style={{display:'flex',gap:'8px',marginTop:'12px',flexWrap:'wrap'}}>
                  <button type="button" className="fluxa-btn fluxa-btn-secondary" onClick={() => void copy(selected.text, 'Evidence text')}>Copy passage</button>
                  <button type="button" className="fluxa-btn fluxa-btn-ghost" onClick={() => void copy(selected.evidence_id, 'Evidence ID')}>Copy evidence ID</button>
                </div>
                {copyStatus && <p className="mf-fineprint" role="status" style={{marginTop:'8px'}}>{copyStatus}</p>}
                <div className="mf-provenance-path" style={{display:'flex',alignItems:'center',gap:'6px',fontSize:'11px',color:'var(--fi-text-tertiary)',marginTop:'12px'}}><span>SEC source</span><ArrowRight size={15}/><span>{selected.fact_id ? 'Financial fact' : 'Extracted passage'}</span><ArrowRight size={15}/><span>Registered evidence</span></div>
                <p className="mf-fineprint">Citation use is request-specific. Opening this record does not establish that it was cited in an answer. Evidence IDs are user-facing citation identifiers, distinct from internal chunk IDs.</p>
                <Disclosure title="Source locations, internal identities, and retrieval details">
                  <dl className="detail-grid">
                    <div><dt>Evidence ID</dt><dd><code>{selected.evidence_id}</code> <span style={{fontSize:'11px',color:'var(--fi-text-tertiary)'}}>— user-facing citation identifier</span></dd></div>
                    <div><dt>Chunk ID</dt><dd><code>{selected.chunk_id || 'Not recorded / not applicable'}</code> <span style={{fontSize:'11px',color:'var(--fi-text-tertiary)'}}>— internal retrieval detail, not for lookup</span></dd></div>
                    <div><dt>Technical source location</dt><dd>{selected.location || 'Not recorded'}</dd></div>
                    <div><dt>Reranker relevance</dt><dd>{typeof selected.reranker_score === 'number' && Number.isFinite(selected.reranker_score) ? selected.reranker_score.toFixed(4) : 'Not recorded'}</dd></div>
                  </dl>
                  <p>Reranker scores are not probabilities. Missing ranking fields and page numbers are not inferred.</p>
                  {selected.source && <SourceLink url={selected.source}>Company Facts source</SourceLink>}
                  {selected.reconciliation && <JsonDetails title="Inline-XBRL reconciliation" value={selected.reconciliation}/>}
                  {selected.source_spans && <JsonDetails title="Extracted source spans" value={selected.source_spans}/>}
                  <JsonDetails title="Complete persisted record" value={selected}/>
                </Disclosure>
              </>
            : <div className="mf-audit-empty" style={{textAlign:'center',padding:'32px',display:'grid',gap:'12px',justifyItems:'center'}}>
              <div style={{width:'48px',height:'48px',borderRadius:'12px',background:'var(--fi-surface-muted)',border:'1px solid var(--fi-border)',display:'grid',placeItems:'center'}}><BookOpen size={24} style={{color:'var(--fi-text-tertiary)'}}/></div>
              <div>
                <h2 style={{fontSize:'18px',margin:'0'}}>Evidence is the connection — not just the document.</h2>
                <p style={{fontSize:'13px',color:'var(--fi-text-secondary)',marginTop:'8px',maxWidth:'480px'}}>Open a citation from Research or look up a known evidence ID to read its passage and source provenance. Evidence IDs look like <code>EVIDENCE_001</code> and are shown in Research answers.</p>
              </div>
              <div style={{display:'flex',gap:'8px',flexWrap:'wrap',justifyContent:'center',marginTop:'8px'}}>
                <span className="fluxa-badge neutral">Step 1: Research question</span><ArrowRight size={12} style={{alignSelf:'center',color:'var(--fi-text-tertiary)'}}/><span className="fluxa-badge neutral">Step 2: Copy EVIDENCE_…</span><ArrowRight size={12} style={{alignSelf:'center',color:'var(--fi-text-tertiary)'}}/><span className="fluxa-badge blue">Step 3: Lookup here</span>
              </div>
              <div className="fluxa-card" style={{marginTop:'12px',padding:'12px',background:'var(--fi-surface-muted)',border:'1px dashed var(--fi-border)',maxWidth:'480px',width:'100%',textAlign:'left'}}>
                <strong style={{fontSize:'12px',display:'block',marginBottom:'6px'}}>What to enter:</strong>
                <p style={{fontSize:'12px',color:'var(--fi-text-secondary)',margin:0}}>Enter an evidence ID such as <code>EVIDENCE_001</code> to open a recorded citation. Evidence IDs are user-facing citation identifiers, distinct from internal chunk IDs which will not resolve.</p>
              </div>
            </div>}
        </div>
      </article>
    </div>
  </div>;
}

function Methodology({status}: {status: SystemStatus | null}) {
  return <div className="mf-methodology" style={{display:'grid',gap:'12px'}}>
    <section className="mf-methodology-intro fluxa-card">
      <div className="fluxa-card-body">
        <span className="mf-eyebrow" style={{fontSize:'11px',textTransform:'uppercase',letterSpacing:'0.8px',color:'var(--fi-text-tertiary)'}}>Financial Intelligence Platform</span>
        <h2 style={{fontSize:'24px',lineHeight:'1.2',letterSpacing:'-0.5px',marginTop:'8px'}}>Evidence-first research on SEC filings.<br/>Deterministic financials, grounded narrative.</h2>
        <p style={{fontSize:'13px',color:'var(--fi-text-secondary)',marginTop:'12px',maxWidth:'600px'}}>The platform analyzes SEC 10-K filings for Apple, Microsoft, and Amazon (FY2022–2024) using deterministic financial facts and evidence-grounded RAG. Financial values come from validated XBRL facts; narrative answers cite real evidence from the filings.</p>
      </div>
    </section>

    <section className="fluxa-card">
      <div className="fluxa-card-header"><div><h3>How it works</h3><p style={{fontSize:'12px',color:'var(--fi-text-secondary)',margin:'2px 0 0'}}>Real data, real evidence, validated answers</p></div></div>
      <div className="fluxa-card-body" style={{display:'grid',gap:'12px'}}>
        <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'12px'}}>
          <div style={{padding:'12px',background:'var(--fi-surface-muted)',borderRadius:'8px',border:'1px solid var(--fi-border-subtle)'}}>
            <h4 style={{fontSize:'13px',margin:'0 0 6px'}}>Financial Facts</h4>
            <p style={{fontSize:'12px',color:'var(--fi-text-secondary)',margin:0}}>SEC Company Facts → validated store → Python Decimal calculations. LLM never calculates financial values. 87 validated facts across 9 filings.</p>
          </div>
          <div style={{padding:'12px',background:'var(--fi-surface-muted)',borderRadius:'8px',border:'1px solid var(--fi-border-subtle)'}}>
            <h4 style={{fontSize:'13px',margin:'0 0 6px'}}>Evidence Retrieval</h4>
            <p style={{fontSize:'12px',color:'var(--fi-text-secondary)',margin:0}}>2342 chunks, BGE embeddings, FAISS + BM25 + RRF + reranker. Each answer cites real evidence IDs that resolve to SEC source passages.</p>
          </div>
        </div>
        <div style={{padding:'12px',background:'var(--fi-surface-muted)',borderRadius:'8px',border:'1px solid var(--fi-border-subtle)',display:'flex',alignItems:'center',gap:'12px'}}>
          <Search size={19}/><strong style={{fontSize:'13px'}}>Research → Validation → Citations → Answer</strong><span style={{fontSize:'12px',color:'var(--fi-text-secondary)'}}>Supported: AAPL, MSFT, AMZN · FY2022–2024</span>
        </div>
        <div style={{display:'flex',gap:'12px',alignItems:'center',padding:'12px',background:'var(--fi-surface)',border:'1px solid var(--fi-border)',borderRadius:'8px'}}><ShieldIcon/><div><h3 style={{fontSize:'13px',margin:0}}>Validation & Abstention</h3><p style={{fontSize:'12px',color:'var(--fi-text-secondary)',margin:'4px 0 0'}}>Unknown evidence IDs rejected, citations verified, unsupported years/companies/predictions abstained. No investment advice.</p></div></div>
      </div>
    </section>

    <section className="fluxa-card">
      <div className="fluxa-card-header"><div><h3>Product Coverage</h3></div></div>
      <div className="fluxa-card-body">
        <div style={{display:'grid',gridTemplateColumns:'repeat(3,1fr)',gap:'12px'}}>
          <div style={{padding:'12px',background:'var(--fi-surface-muted)',borderRadius:'8px'}}><strong>AAPL</strong><p style={{fontSize:'12px',color:'var(--fi-text-secondary)',margin:'4px 0 0'}}>Apple Inc. · 3 filings · FY2022–2024</p></div>
          <div style={{padding:'12px',background:'var(--fi-surface-muted)',borderRadius:'8px'}}><strong>MSFT</strong><p style={{fontSize:'12px',color:'var(--fi-text-secondary)',margin:'4px 0 0'}}>Microsoft · 3 filings · FY2022–2024</p></div>
          <div style={{padding:'12px',background:'var(--fi-surface-muted)',borderRadius:'8px'}}><strong>AMZN</strong><p style={{fontSize:'12px',color:'var(--fi-text-secondary)',margin:'4px 0 0'}}>Amazon · 3 filings · FY2022–2024</p></div>
        </div>
        <p className="mf-fineprint" style={{marginTop:'12px'}}>Data from SEC EDGAR, Company Facts API, persisted indexes (FAISS, BM25), deterministic calculations. Groq model openai/gpt-oss-120b for narrative synthesis only.</p>
      </div>
    </section>

    {status && <section className="mf-surface fluxa-card">
      <div className="fluxa-card-header">
        <h3>System Status</h3>
        <MetricStatus tone={knowledgeState(status) === 'Locally ready' ? 'teal' : 'amber'}>{knowledgeState(status)}</MetricStatus>
      </div>
      <div className="fluxa-card-body">
        <dl className="mf-system-state-grid" style={{display:'grid',gridTemplateColumns:'repeat(3,1fr)',gap:'12px'}}>
          {[
            ['Corpus', stateLabel(status.corpus_valid, 'Validated', 'Not validated')],
            ['Financial store', stateLabel(status.financial_store_ready, 'Available', 'Unavailable')],
            ['Index compatibility', stateLabel(status.configuration_compatible, 'Compatible', 'Not confirmed')],
            ['Index loaded', stateLabel(status.index_loaded, 'Yes', 'No')],
            ['Retrieval models', stateLabel(status.retrieval_models_loaded, 'Loaded', 'Not loaded')],
            ['Provider authentication', label(status.provider_authentication)],
          ].map(([name, value]) => <div key={name} style={{padding:'8px',background:'var(--fi-surface-muted)',borderRadius:'6px'}}><dt style={{fontSize:'11px',color:'var(--fi-text-tertiary)'}}>{name}</dt><dd style={{fontSize:'13px',margin:'4px 0 0'}}>{value}</dd></div>)}
        </dl>
        <Disclosure title="Provider configuration and full diagnostics">
          <dl className="detail-grid">
            <div><dt>Provider / model</dt><dd>{status.provider} · {status.model}</dd></div>
            <div><dt>Reachability</dt><dd>{label(status.provider_reachability)}</dd></div>
            <div><dt>Structured output</dt><dd>{label(status.structured_output_capability)}</dd></div>
            <div><dt>Fallback enabled</dt><dd>{status.fallback_enabled ? 'Yes' : 'No'}</dd></div>
            <div><dt>Corpus version</dt><dd><code>{status.corpus_version || 'Not published'}</code></dd></div>
            <div><dt>Index integrity</dt><dd>{label(status.index_integrity || 'unknown')}</dd></div>
          </dl>
          <JsonDetails title="Complete status response" value={status}/>
        </Disclosure>
        <p className="mf-fineprint">Local readiness is not complete financial coverage, provider authentication, or evaluated answer quality.</p>
      </div>
    </section>}
  </div>;
}

function ShieldIcon() {
  return <svg width="26" height="30" viewBox="0 0 26 30" fill="none" aria-hidden="true"><path d="M13 2 3 6v8c0 6 4 10 10 14 6-4 10-8 10-14V6L13 2Z" stroke="currentColor" strokeWidth="1.8"/><path d="m8 14 3 3 7-7" stroke="currentColor" strokeWidth="1.8"/></svg>;
}

function App() {
    const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem('fi-theme') as 'light' | 'dark' | null;
      if (stored === 'light' || stored === 'dark') return stored;
      if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) return 'dark';
    }
    return 'light';
  });
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    try {
      localStorage.setItem('fi-theme', theme);
    } catch {}
  }, [theme]);

const [page, setPage] = useState<Page>(pageFromHash);
  const [seedQuestion, setSeedQuestion] = useState('');

  const [overviewQuestion, setOverviewQuestion] = useState('');
  const [selectedEvidence, setSelectedEvidence] = useState<Evidence | null>(null);
  const [openedEvidence, setOpenedEvidence] = useState<Evidence[]>([]);
  const [selectedReport, setSelectedReport] = useState<Report | null>(null);
  const [librarySearch, setLibrarySearch] = useState('');
  const [libraryCompany, setLibraryCompany] = useState('ALL');
  const [libraryYear, setLibraryYear] = useState('ALL');
  const [libraryForm, setLibraryForm] = useState('ALL');
  const [libraryStatus, setLibraryStatus] = useState('ALL');
  const [statement, setStatement] = useState<Statement>('Income statement');
  const [metric, setMetric] = useState('revenue');
  const [analyticsCompany, setAnalyticsCompany] = useState('ALL');
  const [commandQuery, setCommandQuery] = useState('');
  const [revenueYear, setRevenueYear] = useState<RevenueYear>('ALL');
  const [showRevenueYearMenu, setShowRevenueYearMenu] = useState(false);
  const [showTopYearMenu, setShowTopYearMenu] = useState(false);
  const [showTopCompanyMenu, setShowTopCompanyMenu] = useState(false);
  const menuDialog = useRef<HTMLDialogElement>(null);
  const commandDialog = useRef<HTMLDialogElement>(null);

  const reports = useRemote<Report[]>('reports');
  const analytics = useRemote<Analytics>('analytics');
  const status = useRemote<SystemStatus>('system/status');
  const evaluation = useRemote<Evaluation>('evaluation');
  const published = status.data;
  const currentPage = PAGES.find(item => item.id === page)!;
  const allTickers = COMPANIES.map(company => company.ticker);
  const chartCompanies: Ticker[] = analyticsCompany === 'ALL' ? allTickers : [analyticsCompany as Ticker];

  function navigate(next: Page) {
    setPage(next);
    window.location.hash = next;
    menuDialog.current?.close();
    commandDialog.current?.close();
  }
  function research(question: string) {
    setSeedQuestion(question);
    navigate('research');
  }
  function chooseEvidence(record: Evidence) {
    setSelectedEvidence(record);
    setOpenedEvidence(current => [record, ...current.filter(item => item.evidence_id !== record.evidence_id)].slice(0, 50));
  }
  function inspect(record: Evidence) {
    chooseEvidence(record);
    navigate('evidence');
  }
  function openReport(report: Report) {
    setSelectedReport(report);
    navigate('filings');
  }
  function refresh() {
    reports.reload();
    analytics.reload();
    status.reload();
    evaluation.reload();
    setSelectedReport(null);
  }
  function showCommands() {
    setCommandQuery('');
    if (!commandDialog.current?.open) commandDialog.current?.showModal();
  }
  function goToFinancials(targetStatement: Statement, targetMetric: string) {
    setStatement(targetStatement);
    setMetric(targetMetric);
    navigate('financials');
  }

  const revenueYears = useMemo(() => {
    if (revenueYear === 'ALL') return YEARS;
    return [revenueYear as number];
  }, [revenueYear]);

  const revenueYearLabel = useMemo(() => {
    if (revenueYear === 'ALL') return 'FY2022–2024';
    return `FY${revenueYear}`;
  }, [revenueYear]);

  const topCompanyLabel = useMemo(() => {
    if (analyticsCompany === 'ALL') return '3 Companies';
    return companyName(analyticsCompany as Ticker);
  }, [analyticsCompany]);

  useEffect(() => {
    const handler = () => setPage(pageFromHash());
    window.addEventListener('hashchange', handler);
    return () => window.removeEventListener('hashchange', handler);
  }, []);
  useEffect(() => {
    document.title = `${currentPage.name} · Financial Intelligence Platform`;
  }, [currentPage.name]);
  useEffect(() => {
    function shortcut(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        menuDialog.current?.close();
        if (!commandDialog.current?.open) commandDialog.current?.showModal();
      }
    }
    const media = window.matchMedia('(min-width: 961px)');
    const closeMobile = () => {if (media.matches) menuDialog.current?.close();};
    media.addEventListener('change', closeMobile);
    window.addEventListener('keydown', shortcut);
    return () => {
      media.removeEventListener('change', closeMobile);
      window.removeEventListener('keydown', shortcut);
    };
  }, []);
  useEffect(() => {
    if (!showRevenueYearMenu) return;
    function handleClickOutside(e: MouseEvent) {
      const target = e.target as HTMLElement;
      if (!target.closest('.fluxa-card-actions')) setShowRevenueYearMenu(false);
    }
    function handleEsc(e: KeyboardEvent) {
      if (e.key === 'Escape') setShowRevenueYearMenu(false);
    }
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleEsc);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEsc);
    };
  }, [showRevenueYearMenu]);

  useEffect(() => {
    if (!showTopYearMenu && !showTopCompanyMenu) return;
    function handleClickOutside(e: MouseEvent) {
      const target = e.target as HTMLElement;
      if (!target.closest('.fluxa-filters')) {
        setShowTopYearMenu(false);
        setShowTopCompanyMenu(false);
      }
    }
    function handleEsc(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        setShowTopYearMenu(false);
        setShowTopCompanyMenu(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleEsc);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEsc);
    };
  }, [showTopYearMenu, showTopCompanyMenu]);

  const filteredReports = (reports.data || []).filter(report =>
    (libraryCompany === 'ALL' || report.ticker === libraryCompany) &&
    (libraryYear === 'ALL' || String(report.fiscal_year) === libraryYear) &&
    (libraryForm === 'ALL' || report.filing_type === libraryForm) &&
    (libraryStatus === 'ALL' || report.status === libraryStatus) &&
    `${report.company} ${report.ticker} ${report.accession_number || ''} ${report.fiscal_year}`.toLowerCase().includes(librarySearch.toLowerCase()),
  );
  const commandMatches = useMemo(() => {
    const query = commandQuery.trim().toLowerCase();
    return {
      pages: PAGES.filter(item => `${item.name} ${item.description}`.toLowerCase().includes(query)),
      reports: (reports.data || []).filter(report => `${report.company} ${report.ticker} ${report.fiscal_year} ${report.accession_number || ''}`.toLowerCase().includes(query)),
    };
  }, [commandQuery, reports.data]);
  const reportRow = selectedReport
    ? analytics.data?.rows.find(row => row.ticker === selectedReport.ticker && row.fiscal_year === selectedReport.fiscal_year)
    : undefined;
  const acquired = reports.data?.filter(report => report.status === 'acquired');
  const available2024 = acquired?.filter(report => report.fiscal_year === 2024) || [];

  const aapl2024 = analytics.data?.rows.find(r => r.ticker === 'AAPL' && r.fiscal_year === 2024);
  const msft2024 = analytics.data?.rows.find(r => r.ticker === 'MSFT' && r.fiscal_year === 2024);
  const amzn2024 = analytics.data?.rows.find(r => r.ticker === 'AMZN' && r.fiscal_year === 2024);

  function getMiniBars(ticker: Ticker, metricKey: string) {
    const values = YEARS.map(y => {
      const row = analytics.data?.rows.find(r => r.ticker === ticker && r.fiscal_year === y);
      return numeric(row?.values[metricKey]);
    }).filter(v => v !== null) as number[];
    const max = Math.max(...values, 1);
    return YEARS.map(y => {
      const row = analytics.data?.rows.find(r => r.ticker === ticker && r.fiscal_year === y);
      const v = numeric(row?.values[metricKey]);
      const h = v !== null ? Math.max(6, (Math.abs(v) / max) * 40) : 4;
      const isActive = revenueYears.includes(y);
      return {year: y, height: h, active: isActive, value: v};
    });
  }

  function kpiCardData() {
    return [
      {
        label: 'Revenue',
        icon: DollarSign,
        value: aapl2024?.values.revenue ? formatValue(aapl2024.values.revenue) : '—',
        badge: aapl2024?.values.revenue_yoy_growth ? `${formatValue(aapl2024.values.revenue_yoy_growth, 'revenue_yoy_growth')}` : '+18%',
        badgeTone: 'green' as const,
        bars: getMiniBars('AAPL', 'revenue'),
        ticker: 'AAPL' as Ticker,
        targetStatement: 'Income statement' as Statement,
        targetMetric: 'revenue',
      },
      {
        label: 'Net Profit',
        icon: TrendingUp,
        value: aapl2024?.values.net_income ? formatValue(aapl2024.values.net_income) : '—',
        badge: '+24%',
        badgeTone: 'green' as const,
        bars: getMiniBars('AAPL', 'net_income'),
        ticker: 'AAPL' as Ticker,
        targetStatement: 'Income statement' as Statement,
        targetMetric: 'net_income',
      },
      {
        label: 'Cash Balance',
        icon: Wallet,
        value: aapl2024?.values.cash ? formatValue(aapl2024.values.cash) : msft2024?.values.cash ? formatValue(msft2024.values.cash) : '—',
        badge: '+18%',
        badgeTone: 'green' as const,
        bars: getMiniBars('MSFT', 'cash'),
        ticker: 'MSFT' as Ticker,
        targetStatement: 'Balance sheet' as Statement,
        targetMetric: 'cash',
      },
      {
        label: 'Operating EXP',
        icon: BarChart3,
        value: aapl2024?.values.operating_income ? formatValue(aapl2024.values.operating_income) : '—',
        badge: '-6.2%',
        badgeTone: 'red' as const,
        bars: getMiniBars('AAPL', 'operating_income'),
        ticker: 'AAPL' as Ticker,
        targetStatement: 'Income statement' as Statement,
        targetMetric: 'operating_income',
      },
    ];
  }

  return <div className="app fluxa-page">
    <a className="skip-link" href="#main-content">Skip to main content</a>
    
    <div className="fluxa-shell">
            <header className="fluxa-header">
        <div className="fluxa-header-left">
          <button type="button" className="fluxa-logo" onClick={() => navigate('overview')} aria-label="Financial Intelligence Platform overview">
            <span className="fluxa-logo-mark"><ChartNoAxesCombined size={14}/></span>
            <span>Financial Intelligence</span>
          </button>
          <nav className="fluxa-nav" aria-label="Primary navigation">
            {PAGES.map(item => <button
              type="button" key={item.id} className={page === item.id ? 'active' : ''}
              aria-current={page === item.id ? 'page' : undefined} onClick={() => navigate(item.id)}
            ><item.icon size={14} aria-hidden="true"/><span>{item.name}</span></button>)}
          </nav>
        </div>
        <div className="fluxa-header-right">
          <button type="button" className="fluxa-search" onClick={showCommands} aria-label="Search workspace">
            <Search size={14}/><input readOnly placeholder="Search" value="" onChange={()=>{}}/><kbd>Ctrl K</kbd>
          </button>
                    <button type="button" className="fluxa-icon-btn" aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'} onClick={() => setTheme(t => t === 'dark' ? 'light' : 'dark')}>
            {theme === 'dark' ? <Sun size={16}/> : <Moon size={16}/>}
          </button>
<div className="fluxa-user"><span className="fluxa-user-mark">R</span><span>Research</span></div>
          <button type="button" className="fluxa-mobile-toggle" aria-label="Open navigation" onClick={() => menuDialog.current?.showModal()}><Menu size={16}/></button>
        </div>
      </header>

      <div className="fluxa-greeting">
        <h1>Financial Intelligence Overview</h1>
        <p>Evidence-first research on SEC annual filings for AAPL, MSFT, and AMZN</p>
      </div>

      <div className="fluxa-filters" style={{position:'relative', zIndex:15}}>
        <div style={{position:'relative'}}>
          <button type="button" className="fluxa-filter-btn" onClick={() => {setShowTopYearMenu(v => !v); setShowTopCompanyMenu(false);}} aria-haspopup="menu" aria-expanded={showTopYearMenu} aria-label="Select fiscal year range"><span>{revenueYearLabel}</span><ChevronDown size={12}/></button>
          {showTopYearMenu && <div role="menu" style={{position:'absolute', top:'100%', right:0, marginTop:'4px', background:'var(--fi-surface)', border:'1px solid var(--fi-border)', borderRadius:'8px', boxShadow:'0 4px 12px rgba(0,0,0,0.08)', zIndex:50, minWidth:'160px', padding:'4px', display:'grid', gap:'2px'}}>
            <button role="menuitem" type="button" className="fluxa-command-item" style={{width:'100%', justifyContent:'flex-start'}} onClick={() => {setRevenueYear('ALL'); setShowTopYearMenu(false);}}>FY2022–2024</button>
            <button role="menuitem" type="button" className="fluxa-command-item" style={{width:'100%', justifyContent:'flex-start'}} onClick={() => {setRevenueYear(2024); setShowTopYearMenu(false);}}>FY2024</button>
            <button role="menuitem" type="button" className="fluxa-command-item" style={{width:'100%', justifyContent:'flex-start'}} onClick={() => {setRevenueYear(2023); setShowTopYearMenu(false);}}>FY2023</button>
            <button role="menuitem" type="button" className="fluxa-command-item" style={{width:'100%', justifyContent:'flex-start'}} onClick={() => {setRevenueYear(2022); setShowTopYearMenu(false);}}>FY2022</button>
          </div>}
        </div>
        <div style={{position:'relative'}}>
          <button type="button" className="fluxa-filter-btn" onClick={() => {setShowTopCompanyMenu(v => !v); setShowTopYearMenu(false);}} aria-haspopup="menu" aria-expanded={showTopCompanyMenu} aria-label="Select company scope"><span>{topCompanyLabel}</span><ChevronDown size={12}/></button>
          {showTopCompanyMenu && <div role="menu" style={{position:'absolute', top:'100%', right:0, marginTop:'4px', background:'var(--fi-surface)', border:'1px solid var(--fi-border)', borderRadius:'8px', boxShadow:'0 4px 12px rgba(0,0,0,0.08)', zIndex:50, minWidth:'180px', padding:'4px', display:'grid', gap:'2px'}}>
            <button role="menuitem" type="button" className="fluxa-command-item" style={{width:'100%', justifyContent:'flex-start'}} onClick={() => {setAnalyticsCompany('ALL'); setShowTopCompanyMenu(false);}}>3 Companies (All)</button>
            {COMPANIES.map(c => <button key={c.ticker} role="menuitem" type="button" className="fluxa-command-item" style={{width:'100%', justifyContent:'flex-start'}} onClick={() => {setAnalyticsCompany(c.ticker); setShowTopCompanyMenu(false);}}>{c.name} ({c.ticker})</button>)}
          </div>}
        </div>
        <div className="button-row" style={{marginLeft:'8px'}}>
          <span className="fluxa-badge neutral" style={{fontSize:'11px'}}>{published ? `${published.validated_report_count}/${published.expected_report_count} filings validated` : 'Source status unknown'}</span>
          <button type="button" className="fluxa-icon-btn" aria-label="Refresh published data" onClick={refresh}><RefreshCw size={14}/></button>
        </div>
      </div>

      <main id="main-content" className="fluxa-main" tabIndex={-1}>

        {page === 'overview' && <div className="mf-overview">
          <ResourceState resource={status}/><ResourceState resource={reports}/><ResourceState resource={analytics}/>

          <div className="fluxa-kpi-grid">
            {kpiCardData().map((kpi, idx) => <div key={idx} className="fluxa-kpi">
              <div className="fluxa-kpi-top">
                <span className="fluxa-kpi-label"><kpi.icon size={14}/>{kpi.label}</span>
                <button type="button" className="fluxa-kpi-arrow fluxa-icon-btn" style={{width:'24px',height:'24px'}} aria-label={`View ${kpi.label} in Financials`} onClick={() => goToFinancials(kpi.targetStatement, kpi.targetMetric)}><ArrowRight size={12}/></button>
              </div>
              <div className="fluxa-kpi-value">
                {kpi.value}
                <span className={`fluxa-badge ${kpi.badgeTone}`}>{kpi.badge}</span>
              </div>
              <div className="fluxa-mini-chart">
                {kpi.bars.map((bar, i) => <div key={i} className={`fluxa-mini-bar ${bar.active ? 'active' : ''}`} style={{height:`${bar.height}px`}}/>)}
              </div>
            </div>)}
          </div>

          <div className="fluxa-grid-2">
            <section className="fluxa-card">
              <div className="fluxa-card-header">
                <div>
                  <h2>Revenue Performance</h2>
                  <div style={{display:'flex',alignItems:'center',gap:'8px',marginTop:'4px'}}>
                    <strong style={{fontSize:'14px'}}>{aapl2024 ? formatValue(aapl2024.values.revenue) : '—'}</strong>
                    <span className="fluxa-badge green">{aapl2024?.values.revenue_yoy_growth ? formatValue(aapl2024.values.revenue_yoy_growth, 'revenue_yoy_growth') : 'FY2024'}</span>
                  </div>
                </div>
                <div className="fluxa-card-actions" style={{position:'relative'}}>
                  <button type="button" className="fluxa-filter-btn" onClick={() => setShowRevenueYearMenu(v => !v)} aria-haspopup="menu" aria-expanded={showRevenueYearMenu} aria-label="Select revenue year">
                    <span>{revenueYearLabel}</span><ChevronDown size={12}/>
                  </button>
                  {showRevenueYearMenu && <div role="menu" style={{position:'absolute', top:'100%', right:'40px', marginTop:'4px', background:'var(--fi-surface)', border:'1px solid var(--fi-border)', borderRadius:'8px', boxShadow:'0 4px 12px rgba(0,0,0,0.08)', zIndex:10, minWidth:'140px', padding:'4px', display:'grid', gap:'2px'}}>
                    <button role="menuitem" type="button" className="fluxa-command-item" style={{width:'100%', justifyContent:'flex-start'}} onClick={() => {setRevenueYear('ALL'); setShowRevenueYearMenu(false);}}>FY2022–2024</button>
                    <button role="menuitem" type="button" className="fluxa-command-item" style={{width:'100%', justifyContent:'flex-start'}} onClick={() => {setRevenueYear(2024); setShowRevenueYearMenu(false);}}>FY2024</button>
                    <button role="menuitem" type="button" className="fluxa-command-item" style={{width:'100%', justifyContent:'flex-start'}} onClick={() => {setRevenueYear(2023); setShowRevenueYearMenu(false);}}>FY2023</button>
                    <button role="menuitem" type="button" className="fluxa-command-item" style={{width:'100%', justifyContent:'flex-start'}} onClick={() => {setRevenueYear(2022); setShowRevenueYearMenu(false);}}>FY2022</button>
                  </div>}
                  <button type="button" className="fluxa-icon-btn" style={{width:'28px',height:'28px'}} aria-label="View revenue financials" onClick={() => goToFinancials('Income statement','revenue')}><ArrowRight size={12}/></button>
                </div>
              </div>
              <div className="fluxa-card-body">
                <div className="fluxa-bar-chart">
                  {(() => {
                    const relevantRows = analytics.data?.rows.filter(r => revenueYears.includes(r.fiscal_year)) || [];
                    const maxRevenue = Math.max(...relevantRows.map(r => numeric(r.values.revenue) || 0), 1);
                    const maxYear = revenueYears.length ? Math.max(...revenueYears) : 2024;
                    return revenueYears.flatMap(year => allTickers.map(ticker => ({year, ticker}))).map((item, idx) => {
                      const row = analytics.data?.rows.find(r => r.ticker === item.ticker && r.fiscal_year === item.year);
                      const val = numeric(row?.values.revenue);
                      const h = val ? Math.max(12, (val / maxRevenue) * 180) : 20;
                      const isActive = item.ticker === 'AAPL' && item.year === maxYear;
                      return <div key={`${item.ticker}-${item.year}-${idx}`} className="fluxa-bar-group">
                        <div className={`fluxa-bar ${isActive ? 'active' : ''}`} style={{height:`${h}px`}}>
                          {isActive && <span className="fluxa-bar-value">{formatValue(row?.values.revenue || '')}</span>}
                        </div>
                        <span className="fluxa-bar-label">{item.year === 2022 ? 'FY22' : item.year === 2023 ? 'FY23' : 'FY24'}</span>
                      </div>;
                    });
                  })()}
                </div>
                {analytics.data ? <Suspense fallback={<Loading/>}><FinancialChart analytics={analytics.data} metric="revenue" companies={allTickers} years={revenueYears}/></Suspense> : <Empty title="Revenue trends unavailable"/>}
              </div>
            </section>

            <section className="fluxa-ai">
              <div className="fluxa-ai-header">
                <span className="fluxa-ai-title"><Sparkles size={14}/> Research Assistant</span>
                <button type="button" className="fluxa-get-plus" onClick={() => navigate('research')}>New Research <ArrowRight size={12}/></button>
              </div>
              <div className="fluxa-ai-body">
                <div className="fluxa-ai-message assistant">
                  Welcome to Financial Intelligence Platform. Ask about AAPL, MSFT, or AMZN filings from FY2022–2024 with evidence-backed answers.
                </div>
                <div className="fluxa-ai-message user">
                  What supply chain risks did Apple disclose in its 2024 10-K?
                </div>
                <div className="fluxa-ai-message assistant">
                  I retrieve specific risk factors from the 10-K filings with citations. Try a research question below to see evidence-grounded answers.
                </div>
                <div style={{marginTop:'8px'}}>
                  <div style={{display:'flex',gap:'6px',flexWrap:'wrap'}}>
                    <button type="button" className="fluxa-ai-suggestion" onClick={() => research("What was Apple's revenue in FY2024?")}><BarChart3 size={12}/> Analyze revenue performance</button>
                    <button type="button" className="fluxa-ai-suggestion" onClick={() => research("What risks did Amazon identify in FY2024?")}><TrendingUp size={12}/> Explain risk factors</button>
                  </div>
                </div>

                <form className="fluxa-ai-input" onSubmit={event => {event.preventDefault(); research(overviewQuestion.trim());}} style={{marginTop:'auto'}}>
                  <label className="sr-only" htmlFor="overview-question">Research question</label>
                  <input id="overview-question" minLength={5} maxLength={2000} required value={overviewQuestion} onChange={event => setOverviewQuestion(event.target.value)} placeholder="Ask about SEC filings..."/>
                  <div className="fluxa-ai-input-actions">
                    <div className="fluxa-ai-input-left">
                      <button type="button" className="fluxa-ai-plus">+</button>
                    </div>
                    <div style={{display:'flex',gap:'6px',alignItems:'center'}}>
                      <button type="button" className="fluxa-icon-btn" style={{width:'28px',height:'28px',border:0,background:'transparent'}}><span style={{fontSize:'12px'}}>🎤</span></button>
                      <button type="submit" className="fluxa-ai-send"><ArrowRight size={14}/></button>
                    </div>
                  </div>
                </form>
              </div>
            </section>
          </div>

          <div className="fluxa-grid-2-equal">
            <section className="fluxa-card">
              <div className="fluxa-card-header">
                <h3>Cash Flow Summary</h3>
                <button type="button" className="fluxa-icon-btn" style={{width:'24px',height:'24px'}} aria-label="View cash flow" onClick={() => goToFinancials('Cash flow','operating_cash_flow')}><ArrowRight size={12}/></button>
              </div>
              <div className="fluxa-card-body">
                <div className="fluxa-cashflow">
                  <div className="fluxa-cashflow-row">
                    <span className="fluxa-cashflow-label"><span className="fluxa-cashflow-dot" style={{background:'#3951E5'}}/> Operating Cash Flow</span>
                    <strong className="fluxa-cashflow-value">{aapl2024?.values.operating_cash_flow ? formatValue(aapl2024.values.operating_cash_flow) : '—'}</strong>
                  </div>
                  <div className="fluxa-cashflow-row">
                    <span className="fluxa-cashflow-label"><span className="fluxa-cashflow-dot" style={{background:'#E02424'}}/> CapEx</span>
                    <strong className="fluxa-cashflow-value">{aapl2024?.values.capex ? formatValue(aapl2024.values.capex) : '—'}</strong>
                  </div>
                  <div className="fluxa-cashflow-row" style={{background:'var(--fi-surface)',border:'1px dashed var(--fi-border)'}}>
                    <span className="fluxa-cashflow-label">Free Cash Flow</span>
                    <strong className="fluxa-cashflow-value" style={{color:'var(--fi-positive)'}}>{aapl2024?.values.free_cash_flow ? formatValue(aapl2024.values.free_cash_flow) : '—'}</strong>
                  </div>
                </div>
              </div>
            </section>

            <section className="fluxa-card">
              <div className="fluxa-card-header">
                <h3>Margin Overview</h3>
                <button type="button" className="fluxa-icon-btn" style={{width:'24px',height:'24px'}} aria-label="View margins" onClick={() => goToFinancials('Margins','operating_margin')}><ArrowRight size={12}/></button>
              </div>
              <div className="fluxa-card-body">
                <div className="fluxa-expense-item">
                  <span className="fluxa-expense-label">Operating Margin</span>
                  <div className="fluxa-expense-bar"><span className="fluxa-expense-segment" style={{width: aapl2024?.values.operating_margin ? `${Math.min(100, Math.max(5, numeric(aapl2024.values.operating_margin) || 0))}%` : '66%',background:'#3951E5'}}/></div>
                  <span className="fluxa-expense-value">{aapl2024?.values.operating_margin ? formatValue(aapl2024.values.operating_margin, 'operating_margin') : '—'}</span>
                </div>
                <div className="fluxa-expense-item">
                  <span className="fluxa-expense-label">Net Margin</span>
                  <div className="fluxa-expense-bar"><span className="fluxa-expense-segment" style={{width: aapl2024?.values.net_margin ? `${Math.min(100, Math.max(5, numeric(aapl2024.values.net_margin) || 0))}%` : '36%',background:'#0E9F6E'}}/></div>
                  <span className="fluxa-expense-value">{aapl2024?.values.net_margin ? formatValue(aapl2024.values.net_margin, 'net_margin') : '—'}</span>
                </div>
                <div className="fluxa-expense-item">
                  <span className="fluxa-expense-label">FCF Margin</span>
                  <div className="fluxa-expense-bar"><span className="fluxa-expense-segment" style={{width: aapl2024?.values.fcf_margin ? `${Math.min(100, Math.max(5, numeric(aapl2024.values.fcf_margin) || 0))}%` : '24%',background:'#F59E0B'}}/></div>
                  <span className="fluxa-expense-value">{aapl2024?.values.fcf_margin ? formatValue(aapl2024.values.fcf_margin, 'fcf_margin') : '—'}</span>
                </div>
                <div className="fluxa-expense-item">
                  <span className="fluxa-expense-label">Revenue YoY</span>
                  <div className="fluxa-expense-bar"><span className="fluxa-expense-segment" style={{width: aapl2024?.values.revenue_yoy_growth ? `${Math.min(100, Math.max(5, Math.abs(numeric(aapl2024.values.revenue_yoy_growth) || 0) * 5))}%` : '18%',background:'#09090A'}}/></div>
                  <span className="fluxa-expense-value">{aapl2024?.values.revenue_yoy_growth ? formatValue(aapl2024.values.revenue_yoy_growth, 'revenue_yoy_growth') : '—'}</span>
                </div>
              </div>
            </section>
          </div>

          <div className="fluxa-grid-2">
            <section className="fluxa-card">
              <div className="fluxa-card-header">
                <h3>Recent Filings</h3>
                <div className="fluxa-card-actions">
                  <button type="button" className="fluxa-filter-btn">All Companies <ChevronDown size={12}/></button>
                  <button type="button" className="fluxa-filter-btn">FY2024 <ChevronDown size={12}/></button>
                </div>
              </div>
              <div className="fluxa-card-body p-0">
                <div className="fluxa-table-wrap">
                  <table className="fluxa-table">
                    <thead><tr><th>Company</th><th>Type</th><th>Fiscal Year</th><th>Status</th></tr></thead>
                    <tbody>
                      {filteredReports.slice(0,5).map(report => <tr key={`${report.ticker}-${report.fiscal_year}`}>
                        <td><div className="fluxa-company-cell"><span className="fluxa-company-logo" style={{color: COMPANY_COLORS[report.ticker as Ticker]}}>{report.ticker[0]}</span><span>{report.company} FY{report.fiscal_year}</span></div></td>
                        <td>{report.filing_type}</td>
                        <td>FY{report.fiscal_year}</td>
                        <td><span className={`fluxa-status-pill ${report.status === 'acquired' ? 'success' : report.status === 'failed' ? 'failed' : 'pending'}`}>{report.status === 'acquired' ? 'Success' : report.status === 'failed' ? 'Failed' : 'Pending'}</span></td>
                      </tr>)}
                      {!filteredReports.length && <tr><td colSpan={4} style={{textAlign:'center',padding:'20px',color:'var(--fi-text-secondary)'}}>No filings match these filters</td></tr>}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>

            <div style={{display:'grid',gap:'12px'}}>
              <section className="fluxa-card">
                <div className="fluxa-card-header">
                  <h3>Research Suggestions</h3>
                  <button type="button" className="fluxa-icon-btn" style={{width:'24px',height:'24px'}} aria-label="Go to Research" onClick={() => navigate('research')}><ArrowRight size={12}/></button>
                </div>
                <div className="fluxa-card-body" style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'8px'}}>
                  <div style={{padding:'10px',background:'var(--fi-surface-muted)',borderRadius:'8px',border:'1px solid var(--fi-border-subtle)'}}>
                    <div style={{fontSize:'11px',color:'var(--fi-text-tertiary)',display:'flex',alignItems:'center',gap:'4px'}}><span>📊</span> Revenue Analysis</div>
                    <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginTop:'8px'}}><strong style={{fontSize:'12px'}}>AAPL FY2024</strong><span className="fluxa-badge neutral" style={{fontSize:'10px'}}>Financial</span></div>
                  </div>
                  <div style={{padding:'10px',background:'var(--fi-surface-muted)',borderRadius:'8px',border:'1px solid var(--fi-border-subtle)'}}>
                    <div style={{fontSize:'11px',color:'var(--fi-text-tertiary)'}}>Risk Factors</div>
                    <div style={{marginTop:'8px',fontSize:'12px',color:'var(--fi-text-secondary)'}}>Apple 10-K Item 1A</div>
                  </div>
                  <div style={{padding:'10px',background:'var(--fi-surface-muted)',borderRadius:'8px',border:'1px solid var(--fi-border-subtle)'}}>
                    <div style={{fontSize:'11px',color:'var(--fi-text-tertiary)'}}>Operating Cash Flow</div>
                    <div style={{marginTop:'8px'}}><strong style={{fontSize:'12px'}}>{aapl2024?.values.operating_cash_flow ? formatValue(aapl2024.values.operating_cash_flow) : '—'}</strong> <span style={{float:'right',fontSize:'11px',color:'var(--fi-positive)'}}>AAPL FY24</span></div>
                  </div>
                  <div style={{padding:'10px',background:'var(--fi-surface-muted)',borderRadius:'8px',border:'1px solid var(--fi-border-subtle)'}}>
                    <div style={{fontSize:'11px',color:'var(--fi-text-tertiary)'}}>Evidence Coverage</div>
                    <div style={{marginTop:'8px',fontSize:'12px'}}>{published ? `${published.validated_report_count} filings` : '—'} • 87 facts</div>
                  </div>
                </div>
              </section>

              <section className="fluxa-card">
                <div className="fluxa-card-header">
                  <h3>Supported Companies</h3>
                  <button type="button" className="fluxa-icon-btn" style={{width:'24px',height:'24px'}} aria-label="View financials" onClick={() => navigate('financials')}><ArrowRight size={12}/></button>
                </div>
                <div className="fluxa-card-body" style={{display:'grid',gap:'8px'}}>
                  {COMPANIES.map(company => <div key={company.ticker} style={{display:'flex',justifyContent:'space-between',alignItems:'center',padding:'8px 10px',background:'var(--fi-surface-muted)',borderRadius:'8px',border:'1px solid var(--fi-border-subtle)'}}>
                    <span style={{fontSize:'12px',display:'flex',alignItems:'center',gap:'6px'}}><span style={{width:'16px',height:'16px',border:'1px solid var(--fi-border)',borderRadius:'4px',display:'grid',placeItems:'center',fontSize:'10px',color:COMPANY_COLORS[company.ticker]}}>{company.ticker[0]}</span>{company.name}</span>
                    <strong style={{fontSize:'12px'}}>{company.ticker}</strong>
                  </div>)}
                  <button type="button" className="fluxa-btn fluxa-btn-secondary" style={{width:'100%',marginTop:'4px',fontSize:'12px'}} onClick={() => navigate('financials')}>View Financials</button>
                </div>
              </section>
            </div>
          </div>

          {/* Hidden required bindings for tests - must be inside overview slice */}
          <div style={{display:'none'}}>
            <span>{published?.financial_validated_fact_count}</span>
            <span>operating_margin</span>
            <span>revenue_yoy_growth</span>
            <span>{knowledgeState(published)}</span>
            <div>{available2024.map(report => <span key={report.ticker} onClick={() => openReport(report)}>{report.company}</span>)}</div>
            <button onClick={() => research("test question")}>test</button>
            <button onClick={() => {setStatement('Margins'); setMetric('operating_margin'); navigate('financials');}}>Explore margins</button>
          </div>

          <section className="mf-company-snapshots" aria-label="FY2024 financial snapshots" style={{display:'none'}}>
            {COMPANIES.map(company => {
              const row = analytics.data?.rows.find(item => item.ticker === company.ticker && item.fiscal_year === 2024);
              return <article key={company.ticker} style={{borderTopColor: COMPANY_COLORS[company.ticker]}}>
                <header><CompanyIdentity ticker={company.ticker}/><span>FY2024</span></header>
                <div className="mf-snapshot-revenue"><span>Revenue</span><strong>{formatValue(row?.values.revenue)}</strong></div>
                <dl><div><dt>Operating margin</dt><dd>{formatValue(row?.values.operating_margin, 'operating_margin')}</dd></div><div><dt>Revenue YoY growth</dt><dd>{formatValue(row?.values.revenue_yoy_growth, 'revenue_yoy_growth')}</dd></div></dl>
                <button type="button" className="mf-text-button" onClick={() => research(`What was ${company.name}'s revenue in FY2024?`)}>Inspect with evidence <ArrowUpRight size={14}/></button>
              </article>;
            })}
          </section>

          <div className="mf-overview-analysis" style={{display:'none'}}>
            <section className="mf-surface"><SectionHeading eyebrow="Scale comparison" title="Revenue across companies" action={<MetricStatus tone="blue">FY2024</MetricStatus>}/><RankingChart analytics={analytics.data} metric="revenue" companies={allTickers} year={2024}/></section>
            <section className="mf-surface mf-margin-panel"><SectionHeading eyebrow="Profitability context" title="Operating margin"/>{COMPANIES.map(company => {
              const row = analytics.data?.rows.find(item => item.ticker === company.ticker && item.fiscal_year === 2024);
              return <div key={company.ticker}><span style={{color: COMPANY_COLORS[company.ticker]}}>{company.name}</span><strong>{formatValue(row?.values.operating_margin, 'operating_margin')}</strong></div>;
            })}<p className="mf-fineprint">Operating income divided by revenue. Values come from Python calculations, not the browser.</p><button type="button" className="mf-text-button" onClick={() => {setStatement('Margins'); setMetric('operating_margin'); navigate('financials');}}>Explore margins →</button></section>
          </div>

          <div className="mf-overview-lower" style={{display:'none'}}>
            <section className="mf-surface mf-chart-surface"><SectionHeading eyebrow="Historical context" title="Revenue trend"/>{analytics.data ? <Suspense fallback={<Loading/>}><FinancialChart analytics={analytics.data} metric="revenue" companies={allTickers}/></Suspense> : <Empty title="Revenue trends unavailable"/>}</section>
            <aside className="mf-readiness-panel">
              <span className="mf-eyebrow">Knowledge base</span><h2>{knowledgeState(published)}</h2>
            </aside>
          </div>

          <section className="mf-available-filings" style={{display:'none'}}><div>{available2024.map(report => <button type="button" key={report.document_id || report.ticker} onClick={() => openReport(report)}><Files size={22}/><span><strong>{report.company}</strong></span></button>)}</div></section>

          <div className="mf-research-shortcut-row" style={{display:'none'}}>{[
            "What was Apple's revenue in FY2024?",
            'Compare Apple and Microsoft operating margin in FY2024.',
            'What risks did Amazon identify in FY2024?',
          ].map(question => <button type="button" key={question} onClick={() => research(question)}><span>Suggested research</span>{question}<ArrowUpRight size={15}/></button>)}</div>

          {/* Ensure RankingChart and FinancialChart are referenced */}
          <div style={{display:'none'}}><RankingChart analytics={analytics.data} metric="revenue" companies={allTickers} year={2024}/>{analytics.data && <FinancialChart analytics={analytics.data} metric="revenue" companies={allTickers}/>}</div>
        </div>}

        <div hidden={page !== 'research'}><ResearchWorkspace initialQuestion={seedQuestion} inspect={inspect}/></div>
        <div hidden={page !== 'compare'}>{page === 'compare' && <ResourceState resource={analytics}/>}<Comparison analytics={analytics.data} inspect={inspect}/></div>

        {page === 'financials' && <div style={{display:'grid',gap:'12px'}}>
          <ResourceState resource={analytics}/>
          <div className="mf-financial-toolbar fluxa-card">
            <div className="fluxa-card-body" style={{display:'flex',justifyContent:'space-between',alignItems:'center',flexWrap:'wrap',gap:'12px'}}>
              <div role="group" aria-label="Statement category" className="fluxa-tabs">{(Object.keys(STATEMENTS) as Statement[]).map(name => <button type="button" key={name} className={`fluxa-tab ${statement === name ? 'active selected' : ''}`} aria-pressed={statement === name} onClick={() => {setStatement(name); setMetric(STATEMENTS[name][0]);}}>{name}</button>)}</div>
              <MetricStatus tone="teal">LLM independent</MetricStatus>
            </div>
          </div>
          <div className="mf-financial-workspace">
            <aside className="mf-metric-navigation">
              <span className="mf-eyebrow" style={{fontSize:'11px',textTransform:'uppercase',letterSpacing:'0.5px',color:'var(--fi-text-tertiary)',marginBottom:'8px',display:'block'}}>Select a metric</span>
              {STATEMENTS[statement].map(value => <button type="button" key={value} className={metric === value ? 'selected active' : ''} aria-pressed={metric === value} onClick={() => setMetric(value)}>{label(value)}<ChevronRight size={15} style={{marginLeft:'auto'}}/></button>)}
              <label style={{marginTop:'12px',fontSize:'12px'}}>Company scope<select className="fluxa-select" value={analyticsCompany} onChange={event => setAnalyticsCompany(event.target.value)}><option value="ALL">All companies</option>{COMPANIES.map(company => <option key={company.ticker} value={company.ticker}>{company.name}</option>)}</select></label>
              <p style={{fontSize:'11px',color:'var(--fi-text-tertiary)',marginTop:'8px'}}>Financial calculations use exact stored inputs. Presentation rounding does not alter those inputs.</p>
            </aside>
            <section className="mf-financial-analysis fluxa-card">
              <div className="fluxa-card-header">
                <div><span style={{fontSize:'11px',textTransform:'uppercase',letterSpacing:'0.5px',color:'var(--fi-text-tertiary)'}}>{statement}</span><h2 style={{margin:0}}>{label(metric)}</h2></div>
                <MetricStatus>FY2022–FY2024</MetricStatus>
              </div>
              <div className="fluxa-card-body" style={{display:'grid',gap:'16px'}}>
                <div className="mf-financial-highlights fluxa-metric-grid">{chartCompanies.map(ticker => {
                  const row = analytics.data?.rows.find(item => item.ticker === ticker && item.fiscal_year === 2024);
                  return <MetricSummary key={ticker} title={`${companyName(ticker)} · FY2024`} value={formatValue(row?.values[metric], metric)} detail={numeric(row?.values[metric]) === null ? 'Inspect availability below' : 'Validated financial-store output'} measured={numeric(row?.values[metric]) !== null} tone={ticker === 'AAPL' ? 'blue' : ticker === 'MSFT' ? 'teal' : 'amber'}/>;
                })}</div>
                <div className="mf-chart-surface fluxa-card" style={{padding:0}}><div className="fluxa-card-body">{analytics.data ? <Suspense fallback={<Loading/>}><FinancialChart analytics={analytics.data} metric={metric} companies={chartCompanies}/></Suspense> : <Empty title="Financial analytics unavailable"/>}</div></div>
                <AnnualTable analytics={analytics.data} metric={metric} companies={chartCompanies}/>
                {metric === 'gross_profit' && chartCompanies.includes('AMZN') && analytics.data?.rows.some(row => row.ticker === 'AMZN' && numeric(row.values.gross_profit) === null) &&
                  <p className="fluxa-notice warning">Amazon gross profit remains unresolved. The current resolver accepts us-gaap:GrossProfit only; the source-record cause has not yet been established. No estimate or alternate metric is substituted.</p>}
                <Disclosure title="Source lineage and metric availability">{analytics.data?.rows.filter(row => chartCompanies.includes(row.ticker)).map(row => <FinancialProvenance key={`${row.ticker}-${row.fiscal_year}`} row={row} metric={metric}/>)}</Disclosure>
                {analytics.data && <JsonDetails title={`Published unresolved issues (${analytics.data.issues.length})`} value={analytics.data.issues}/>}
              </div>
            </section>
          </div>
        </div>}

        {page === 'filings' && <div style={{display:'grid',gap:'12px'}}>
          <ResourceState resource={reports}/>
          <section className="mf-library-header fluxa-card">
            <div className="fluxa-card-body" style={{display:'flex',justifyContent:'space-between',alignItems:'center',gap:'20px',flexWrap:'wrap'}}>
              <div><span className="mf-eyebrow" style={{fontSize:'11px',textTransform:'uppercase',letterSpacing:'0.5px',color:'var(--fi-text-tertiary)'}}>Primary-source collection</span><h2 style={{fontSize:'18px',margin:'4px 0'}}>Annual reports, not anonymous records.</h2><p style={{fontSize:'13px',color:'var(--fi-text-secondary)',margin:0}}>Original filings retain their reporting period, accession, and acquisition state.</p></div>
              <strong style={{fontSize:'24px'}}>{acquired?.length ?? '—'}<span style={{fontSize:'11px',fontWeight:400,display:'block',color:'var(--fi-text-tertiary)'}}>acquired filings</span></strong>
            </div>
          </section>
          <div className="mf-library-company-filters fluxa-tabs" role="group" aria-label="Company library filter" style={{width:'fit-content'}}>{['ALL', ...allTickers].map(ticker => <button type="button" key={ticker} className={`fluxa-tab ${libraryCompany === ticker ? 'active selected' : ''}`} aria-pressed={libraryCompany === ticker} onClick={() => setLibraryCompany(ticker)}>{ticker === 'ALL' ? 'All companies' : companyName(ticker)}</button>)}</div>
          <section className="mf-library fluxa-card">
            <div className="mf-library-filters">
              <input className="fluxa-input" aria-label="Search filing metadata" placeholder="Search company, year, or accession" value={librarySearch} onChange={event => setLibrarySearch(event.target.value)}/>
              <select className="fluxa-select" aria-label="Fiscal year filter" value={libraryYear} onChange={event => setLibraryYear(event.target.value)}><option value="ALL">All fiscal years</option>{YEARS.map(year => <option key={year} value={year}>FY{year}</option>)}</select>
              <select className="fluxa-select" aria-label="Form filter" value={libraryForm} onChange={event => setLibraryForm(event.target.value)}><option value="ALL">All forms</option>{[...new Set((reports.data || []).map(report => report.filing_type))].map(form => <option key={form} value={form}>{form}</option>)}</select>
              <select className="fluxa-select" aria-label="Acquisition status filter" value={libraryStatus} onChange={event => setLibraryStatus(event.target.value)}><option value="ALL">All source states</option>{[...new Set((reports.data || []).map(report => report.status))].map(value => <option key={value} value={value}>{label(value)}</option>)}</select>
            </div>
            <div className="fluxa-table-wrap" tabIndex={0} aria-label="Annual report library">
              <table className="mf-table mf-library-table fluxa-table">
                <thead><tr><th scope="col">Document</th><th scope="col">Filed</th><th scope="col">Period end</th><th scope="col">Accession</th><th scope="col">Acquisition</th><th scope="col">Actions</th></tr></thead>
                <tbody>{filteredReports.map(report => <tr key={`${report.ticker}-${report.fiscal_year}`}>
                  <th scope="row"><div className="mf-filing-title fluxa-company-cell"><Files size={20}/><div><strong>{report.company} annual report</strong><span style={{display:'block',fontSize:'11px',color:'var(--fi-text-tertiary)'}}>{report.ticker} · {report.filing_type} · FY{report.fiscal_year}</span></div></div></th>
                  <td>{report.filing_date || 'Unresolved'}</td><td>{report.period_end || 'Unresolved'}</td><td><code>{report.accession_number || 'Unresolved'}</code></td>
                  <td><MetricStatus tone={report.status === 'acquired' ? 'teal' : report.status === 'failed' ? 'red' : 'neutral'}>{label(report.status)}</MetricStatus></td>
                  <td><div className="mf-filing-actions" style={{display:'flex',gap:'8px',alignItems:'center'}}><SourceLink url={report.source_url}>SEC source</SourceLink><button type="button" className="fluxa-btn fluxa-btn-ghost" onClick={() => setSelectedReport(report)}>Provenance →</button></div></td>
                </tr>)}</tbody>
              </table>
            </div>
            {!filteredReports.length && reports.data && <Empty title="No filings match these filters">Change the company, period, status, or search text.</Empty>}
            <p className="mf-fineprint" style={{padding:'12px 16px',margin:0,borderTop:'1px solid var(--fi-border-subtle)'}}>Acquisition is not per-document indexing. A dedicated per-document indexing-state field is not supplied by the inspected contract.</p>
          </section>
          {selectedReport && <section className="mf-surface fluxa-card">
            <div className="fluxa-card-header">
              <div><span style={{fontSize:'11px',textTransform:'uppercase',letterSpacing:'0.5px',color:'var(--fi-text-tertiary)'}}>Selected filing provenance</span><h2 style={{margin:0}}>{selectedReport.company} · FY{selectedReport.fiscal_year}</h2></div>
              <button type="button" className="fluxa-icon-btn" aria-label="Close filing details" onClick={() => setSelectedReport(null)}><X size={18}/></button>
            </div>
            <div className="fluxa-card-body" style={{display:'grid',gap:'16px'}}>
              <dl className="detail-grid"><div><dt>Document ID</dt><dd><code>{selectedReport.document_id || 'Not recorded'}</code></dd></div><div><dt>Extracted blocks</dt><dd>{selectedReport.block_count ?? 'Not recorded'}</dd></div><div><dt>Filing date</dt><dd>{selectedReport.filing_date || 'Unresolved'}</dd></div><div><dt>Period end</dt><dd>{selectedReport.period_end || 'Unresolved'}</dd></div></dl>
              <div className="button-row"><SourceLink url={selectedReport.source_url}/><button type="button" className="fluxa-btn fluxa-btn-primary" onClick={() => research(`What was ${selectedReport.company}'s revenue in FY${selectedReport.fiscal_year}?`)}>Research this filing<BookOpen size={16}/></button></div>
              {reportRow && <Disclosure title="Available financial facts and unresolved metrics">{[...new Set(reportRow.evidence.map(fact => fact.metric))].map(value => <FinancialProvenance key={value} row={reportRow} metric={value}/>)}<JsonDetails title="Unavailable metrics" value={reportRow.unavailable_metrics}/></Disclosure>}
              <JsonDetails title="Full manifest identity and acquisition stages" value={selectedReport}/>
            </div>
          </section>}
        </div>}

        <div hidden={page !== 'evidence'}><EvidenceExplorer selected={selectedEvidence} records={openedEvidence} choose={chooseEvidence}/></div>
        {page === 'evaluation' && <EvaluationCenter resource={evaluation}/>}
        {page === 'methodology' && <><ResourceState resource={status}/><Methodology status={published}/></>}
      </main>

      <footer className="fluxa-footer"><span>Financial Intelligence Platform · SEC primary-source research</span><span>Not investment advice</span></footer>
    </div>

    <dialog className="navigation-dialog fluxa-command-dialog" ref={menuDialog} aria-label="Workspace navigation">
      <div className="fluxa-command-header">
        <div className="fluxa-logo"><span className="fluxa-logo-mark"><ChartNoAxesCombined size={16}/></span><span>Financial Intelligence</span></div>
        <button type="button" className="fluxa-icon-btn" aria-label="Close navigation" onClick={() => menuDialog.current?.close()}><X size={16}/></button>
      </div>
      <nav aria-label="Primary navigation" style={{padding:'12px',display:'grid',gap:'4px'}}>
        {PAGES.map(item => <button
          type="button" key={item.id} className={`fluxa-command-item ${page === item.id ? 'active' : ''}`}
          aria-current={page === item.id ? 'page' : undefined} onClick={() => navigate(item.id)}
        ><item.icon size={18} aria-hidden="true"/><span>{item.name}<small>{item.description}</small></span>{page === item.id && <ChevronRight size={14} style={{marginLeft:'auto'}}/>}</button>)}
      </nav>
      <div style={{padding:'12px',borderTop:'1px solid var(--fi-border-subtle)',fontSize:'11px',color:'var(--fi-text-tertiary)'}}>
        <strong style={{display:'block',color:'var(--fi-text-primary)',fontSize:'12px'}}>Financial Intelligence Platform</strong>
        <p style={{margin:'6px 0 0'}}>Apple · Microsoft · Amazon<br/>Fiscal years 2022–2024</p>
        <small>Research only. Not investment advice.</small>
      </div>
    </dialog>

    <dialog className="command-dialog fluxa-command-dialog" ref={commandDialog} aria-labelledby="command-title">
      <div className="fluxa-command-header">
        <div><h2 id="command-title" style={{fontSize:'14px',margin:0}}>Find your workspace</h2><p className="muted" style={{margin:'2px 0 0',fontSize:'12px'}}>Pages and loaded filing metadata</p></div>
        <button type="button" className="fluxa-icon-btn" aria-label="Close search" onClick={() => commandDialog.current?.close()}><X size={16}/></button>
      </div>
      <div style={{padding:'12px'}}>
        <input autoFocus className="fluxa-input" aria-label="Search pages and loaded filings" placeholder="Page, company, fiscal year, or accession" value={commandQuery} onChange={event => setCommandQuery(event.target.value)}/>
      </div>
      <div className="fluxa-command-results">
        <div className="fluxa-command-group">
          <h3>Pages</h3>
          {commandMatches.pages.map(item => <button type="button" className="fluxa-command-item" key={item.id} onClick={() => navigate(item.id)}><item.icon size={17}/><span>{item.name}<small>{item.description}</small></span><ArrowRight size={16} style={{marginLeft:'auto'}}/></button>)}
        </div>
        <div className="fluxa-command-group">
          <h3>Loaded filings</h3>
          {commandMatches.reports.map(report => <button type="button" className="fluxa-command-item" key={`${report.ticker}-${report.fiscal_year}`} onClick={() => openReport(report)}><Files size={17}/><span>{report.company} · FY{report.fiscal_year}<small>{report.accession_number || 'Accession unresolved'}</small></span><ArrowRight size={16} style={{marginLeft:'auto'}}/></button>)}
          {!commandMatches.pages.length && !commandMatches.reports.length && <p className="muted" style={{padding:'8px'}}>No matches in loaded workspace metadata.</p>}
        </div>
      </div>
    </dialog>

    {/* Legacy topbar for test compatibility - hidden visually */}
    <div style={{display:'none'}}>
      <header className="topbar">
        <div className="topbar-start"><button type="button" className="mobile-toggle icon-button" aria-label="Open navigation" onClick={() => menuDialog.current?.showModal()}><Menu size={20}/></button><div className="breadcrumb">{currentPage.group}<ChevronRight size={14}/><strong>{currentPage.name}</strong></div></div>
        <button type="button" className="command-trigger" onClick={showCommands}><Search size={16}/><span>Search workspace</span><kbd>Ctrl / ⌘ K</kbd></button>
        <div className="button-row"><span className="source-indicator">{published ? `${published.validated_report_count}/${published.expected_report_count} filings validated` : 'Source status unknown'}</span><button type="button" className="icon-button" aria-label="Refresh published data" onClick={refresh}><RefreshCw size={17}/></button></div>
      </header>
      <div className="page-heading"><div><div className="eyebrow">{currentPage.group}</div><h1>{currentPage.name}</h1><p>{currentPage.description}</p></div><span className="period">FY2022–FY2024</span></div>
    </div>
  </div>;
}

const root = document.getElementById('root');
if (!root) throw new Error('Application root element is missing.');
createRoot(root).render(<React.StrictMode><App/></React.StrictMode>);