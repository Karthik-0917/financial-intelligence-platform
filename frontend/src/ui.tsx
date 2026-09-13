import {
  useCallback,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import {
  AlertCircle,
  ArrowUpRight,
  Database,
  LoaderCircle,
} from 'lucide-react';
import {
  api,
  ApiError,
  type Evidence,
  type Ticker,
} from './api';

export const COMPANIES: {
  ticker: Ticker;
  name: string;
  color: string;
}[] = [
  {ticker: 'AAPL', name: 'Apple', color: '#426d91'},
  {ticker: 'MSFT', name: 'Microsoft', color: '#526158'},
  {ticker: 'AMZN', name: 'Amazon', color: '#a77b3e'},
];

export const YEARS = [2022, 2023, 2024];

export const METRICS = [
  'revenue',
  'gross_profit',
  'operating_income',
  'net_income',
  'eps',
  'assets',
  'liabilities',
  'equity',
  'cash',
  'operating_cash_flow',
  'capex',
  'free_cash_flow',
  'operating_margin',
  'net_margin',
  'fcf_margin',
  'revenue_yoy_growth',
  'revenue_cagr',
];

/*
 * Preserve the existing comparison request contract.
 * Growth/CAGR remain available through analytics and calculation research.
 * Do not pretend a one-year comparison request carries both endpoint years.
 */
export const COMPARISON_METRICS = METRICS.filter(
  metric => !['revenue_yoy_growth', 'revenue_cagr'].includes(metric),
);

const LABELS: Record<string, string> = {
  revenue: 'Revenue',
  gross_profit: 'Gross profit',
  operating_income: 'Operating income',
  net_income: 'Net income',
  eps: 'Diluted EPS',
  assets: 'Total assets',
  liabilities: 'Total liabilities',
  equity: 'Stockholders’ equity',
  cash: 'Cash & cash equivalents',
  operating_cash_flow: 'Operating cash flow',
  capex: 'Capital expenditure',
  free_cash_flow: 'Free cash flow',
  operating_margin: 'Operating margin',
  net_margin: 'Net margin',
  fcf_margin: 'Free cash flow margin',
  revenue_yoy_growth: 'Revenue YoY growth',
  revenue_cagr: 'Revenue CAGR',
  growth: 'Growth',
  cagr: 'CAGR',
  FACT: 'Financial fact',
  CALCULATION: 'Financial calculation',
  COMPARISON: 'Financial comparison',
  MULTI_DOCUMENT: 'Multi-filing research',
  EXPLANATION: 'Filing explanation',
  RISK: 'Risk research',
  UNSUPPORTED: 'Unsupported request',
};

const DECIMAL = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;

const DISPLAY_NUMBER = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const DISPLAY_CURRENCY = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  notation: 'compact',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function label(value: string): string {
  return LABELS[value] ??
    value.replaceAll('_', ' ').replace(
      /\b\w/g,
      character => character.toUpperCase(),
    );
}

export function companyName(ticker: string): string {
  return COMPANIES.find(company => company.ticker === ticker)?.name ?? ticker;
}

/*
 * Number conversion is for visualization and display only.
 * It must not become the financial calculation source of truth.
 * Reject blank strings and non-decimal JavaScript numeric syntax.
 */
export function numeric(
  value: string | number | null | undefined,
): number | null {
  if (value == null) return null;
  if (typeof value === 'string' && !DECIMAL.test(value.trim())) return null;

  const converted = Number(value);
  return Number.isFinite(converted) ? converted : null;
}

export function formatValue(
  value: string | null | undefined,
  metric = 'revenue',
): string {
  const converted = numeric(value);
  if (converted === null) return 'Unavailable';

  const number = Object.is(converted, -0) ? 0 : converted;

  if (/margin|growth|cagr/i.test(metric)) {
    // The financial API supplies percentage points, not fractional ratios.
    return `${DISPLAY_NUMBER.format(number)}%`;
  }

  if (metric === 'eps') {
    const sign = number < 0 ? '-' : '';
    return `${sign}$${DISPLAY_NUMBER.format(Math.abs(number))}/share`;
  }

  return DISPLAY_CURRENCY.format(number);
}

export function formatAmount(
  value: string | null | undefined,
  unit: string,
  metric: string,
): string {
  if (value == null || numeric(value) === null) return 'Unavailable';
  if (unit === 'percentage') return formatValue(value, 'growth');
  if (unit === 'USD/shares') return formatValue(value, 'eps');
  if (unit === 'USD') return formatValue(value, 'revenue');

  // Unknown units are preserved, not silently relabeled as dollars.
  return `${value} ${unit || label(metric)}`;
}

export function secURL(value?: string | null): string | null {
  if (!value) return null;

  try {
    const url = new URL(value);
    if (
      url.protocol !== 'https:' ||
      !['www.sec.gov', 'data.sec.gov'].includes(url.hostname) ||
      url.username ||
      url.password ||
      (url.port !== '' && url.port !== '443')
    ) return null;
    return url.href;
  } catch {
    return null;
  }
}

export function SourceLink({
  url,
  children = 'Open SEC source',
}: {
  url?: string | null;
  children?: ReactNode;
}) {
  const href = secURL(url);

  return href
    ? <a href={href} target="_blank" rel="noopener noreferrer">
        {children}
        <ArrowUpRight size={14} aria-hidden="true"/>
        <span className="sr-only"> (opens in a new tab)</span>
      </a>
    : <span className="muted">Source link unavailable</span>;
}

export type Remote<T> = {
  data: T | null;
  loading: boolean;
  error: Error | null;
  reload: () => void;
};

export function useRemote<T>(path: string): Remote<T> {
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<{
    data: T | null;
    loading: boolean;
    error: Error | null;
  }>({data: null, loading: true, error: null});

  const reload = useCallback(() => setRevision(value => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setState({data: null, loading: true, error: null});

    void api<T>(path, undefined, controller.signal)
      .then(data => {
        if (!controller.signal.aborted) {
          setState({data, loading: false, error: null});
        }
      })
      .catch(error => {
        if (!controller.signal.aborted) {
          setState({
            data: null,
            loading: false,
            error: error instanceof Error ? error : new Error('Request failed.'),
          });
        }
      });

    return () => controller.abort();
  }, [path, revision]);

  return {...state, reload};
}

export function Badge({
  children,
  tone = 'neutral',
}: {
  children: ReactNode;
  tone?: 'neutral' | 'good' | 'warn' | 'bad';
}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

export function Empty({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return <div className="empty">
    <Database size={26} aria-hidden="true"/>
    <h3>{title}</h3>
    <p>{children || 'No validated values are available for this selection. Missing observations are not replaced with estimates or zeroes.'}</p>
  </div>;
}

export function Loading({
  children = 'Loading published workspace data…',
}: {
  children?: ReactNode;
}) {
  return <div className="loading" role="status">
    <span className="sr-only">{children}</span>
    <span className="loading-visual" aria-hidden="true">
      <LoaderCircle size={18}/>
      <span>{children}</span>
    </span>
  </div>;
}

export function ErrorNotice({
  error,
  retry,
}: {
  error: Error;
  retry?: () => void;
}) {
  return <div className="notice danger" role="alert">
    <AlertCircle size={18} aria-hidden="true"/>
    <div>
      <strong>{error.message}</strong>
      {error instanceof ApiError && error.requestId &&
        <small>Request ID: <code>{error.requestId}</code></small>}
      {error instanceof ApiError && error.retryAfter &&
        <small>Service retry guidance: {error.retryAfter}</small>}
    </div>
    {retry && <button type="button" className="secondary" onClick={retry}>Retry</button>}
  </div>;
}

export function ResourceState<T>({resource}: {resource: Remote<T>}) {
  if (resource.loading) return <Loading/>;
  if (resource.error) return <ErrorNotice error={resource.error} retry={resource.reload}/>;
  return null;
}

export function JsonDetails({title, value}: {title: string; value: unknown}) {
  const [open, setOpen] = useState(false);

  return <details
    className="json-details"
    onToggle={event => setOpen(event.currentTarget.open)}
  >
    <summary>{title}</summary>
    {open && <pre>{JSON.stringify(value, null, 2) ?? 'Not recorded'}</pre>}
  </details>;
}

function evidencePeriod(record: Evidence): string {
  if (record.period_start && record.period_end) {
    return `${record.period_start} to ${record.period_end}`;
  }

  if (record.period_end) {
    return record.fact_id && record.period_start === null
      ? `As of ${record.period_end}`
      : `Period end ${record.period_end}`;
  }

  return 'Period metadata not supplied';
}

export function EvidenceCard({
  record,
  inspect,
}: {
  record: Evidence;
  inspect?: (record: Evidence) => void;
}) {
  const [copyStatus, setCopyStatus] = useState('');
  useEffect(() => setCopyStatus(''), [record.evidence_id]);

  const finiteScore =
    typeof record.reranker_score === 'number' &&
    Number.isFinite(record.reranker_score);

  async function copyPassage() {
    try {
      if (!navigator.clipboard) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(record.text);
      setCopyStatus('Evidence text copied.');
    } catch {
      setCopyStatus('Clipboard unavailable. Select and copy the displayed passage.');
    }
  }

  return <article className="evidence-card">
    <div className="section-head">
      <div className="evidence-source-heading">
        <Badge>{record.ticker} · FY{record.fiscal_year}</Badge>
        <span className="muted">{record.fact_id ? 'Financial fact evidence' : 'Filing passage'}</span>
      </div>
      <SourceLink url={record.source_url}>Original filing</SourceLink>
    </div>

    <h3>{record.section || 'Supporting source evidence'}</h3>
    {record.subsection && <p className="muted">{record.subsection}</p>}

    <blockquote
      className="excerpt"
      tabIndex={0}
      aria-label="Scrollable evidence text"
    >{record.text}</blockquote>

    <div className="button-row">
      <button type="button" className="text-button" onClick={() => void copyPassage()}>Copy evidence text</button>
      {inspect && <button type="button" className="text-button" onClick={() => inspect(record)}>Inspect provenance →</button>}
    </div>
    {copyStatus && <p className="footnote" role="status">{copyStatus}</p>}

    <dl className="inline-meta">
      <div><dt>Source company</dt><dd>{companyName(record.ticker)}</dd></div>
      <div><dt>Fiscal year</dt><dd>FY{record.fiscal_year}</dd></div>
      <div><dt>Source location</dt><dd>{record.location || 'Not recorded'}</dd></div>
      <div><dt>Reporting period</dt><dd>{evidencePeriod(record)}</dd></div>
      <div><dt>Filing date</dt><dd>{record.filing_date || 'Not recorded'}</dd></div>
      <div><dt>SEC accession</dt><dd><code>{record.accession_number || 'Not recorded'}</code></dd></div>
    </dl>

    <div className="evidence-footer">
      <div><small>Application evidence ID</small><code>{record.evidence_id}</code></div>
      <div><small>Evidence type</small><span className="muted">{record.fact_id ? 'Fact' : 'Passage'}</span></div>
    </div>

    <details className="row-details">
      <summary>Evidence identity and retrieval details</summary>
      <dl className="detail-grid">
        <div><dt>Chunk ID</dt><dd><code>{record.chunk_id || 'Not recorded / not applicable'}</code></dd></div>
        <div><dt>Fact ID</dt><dd><code>{record.fact_id || 'Not recorded / not applicable'}</code></dd></div>
        <div><dt>Reranker relevance</dt><dd>{finiteScore ? record.reranker_score!.toFixed(4) : 'Not recorded'}</dd></div>
      </dl>
      <p className="footnote">
        Reranker relevance is not answer-confidence probability. Ranking
        positions and citation use are not inferred from this record.
      </p>
    </details>
  </article>;
}