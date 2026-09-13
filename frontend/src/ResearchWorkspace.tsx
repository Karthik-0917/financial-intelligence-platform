import {
  useEffect,
  useId,
  useRef,
  useState,
} from 'react';
import {
  ArrowRight,
  BookOpen,
  Calculator,
  ChevronDown,
  FileText,
  Search,
  X,
} from 'lucide-react';
import {
  api,
  type Calculation,
  type Evidence,
  type Research,
  type Ticker,
} from './api';
import {
  COMPANIES,
  YEARS,
  ErrorNotice,
  JsonDetails,
  Loading,
  SourceLink,
  companyName,
  formatAmount,
  label,
} from './ui';
import {
  Disclosure,
  MetricStatus,
  SectionHeading,
} from './DesignSystem';
import './research-midnight.css';

const FAILURE_MESSAGES: Record<string, string> = {
  model_or_endpoint_unavailable:
    'The configured generation model or endpoint was unavailable. Retrieved evidence, if returned, remains inspectable.',
  authentication:
    'The generation provider rejected authorization. Check the private server-side provider configuration.',
  missing_api_key:
    'Narrative generation is not configured. Supported financial facts and calculations remain independent of the language model.',
  rate_limit:
    'The generation provider reached a request limit. Wait before submitting another request.',
  timeout:
    'The request exceeded its processing budget. Server or provider work may still be running.',
  provider_unavailable:
    'The narrative provider was temporarily unavailable.',
  context_budget_exceeded:
    'The required evidence could not fit within the configured generation budget without removing protected information.',
  structured_output_validation_failed:
    'The provider response did not satisfy the required answer structure and was not accepted.',
  malformed_response:
    'The provider response could not be accepted as a valid research result.',
  output_token_limit:
    'Generation ended before a complete answer was available.',
  primary_and_fallback_failed:
    'Neither the primary provider nor the configured fallback returned an accepted result.',
};

function object(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function abstentionExplanation(result: Research): string {
  const reason = result.abstention_reason;
  if (!reason) {
    return 'The request could not be supported by the available validated data and evidence.';
  }
  return FAILURE_MESSAGES[reason] || (
    /^[a-z]+(?:_[a-z]+)+$/.test(reason)
      ? `${label(reason)}. The recorded category is available in technical details.`
      : reason
  );
}

function CalculationRecord({value}: {value: Calculation}) {
  return <article className="mf-calculation-record">
    <header>
      <div>
        <span className="mf-eyebrow">Deterministic calculation</span>
        <h3>{label(value.metric)}</h3>
        <p>
          {value.ticker ? companyName(value.ticker) : 'Scope recorded in inputs'}
          {value.fiscal_year ? ` · FY${value.fiscal_year}` : ''}
        </p>
      </div>
      <strong>{formatAmount(value.value, value.unit, value.metric)}</strong>
    </header>
    <div className="mf-calculation-formula">
      <Calculator size={17} aria-hidden="true"/>
      <code>{value.formula}</code>
    </div>
    <div className="table-wrap" tabIndex={0} aria-label="Calculation input values">
      <table className="mf-table">
        <thead>
          <tr>
            <th scope="col">Input</th>
            <th scope="col">Company / period</th>
            <th scope="col" className="number">Value</th>
          </tr>
        </thead>
        <tbody>
          {value.inputs.map((fact, index) => <tr key={fact.fact_id || index}>
            <th scope="row">{label(fact.metric)}</th>
            <td>{fact.ticker} · FY{fact.fiscal_year}</td>
            <td className="number">{formatAmount(fact.value, fact.unit, fact.metric)}</td>
          </tr>)}
        </tbody>
      </table>
    </div>
    <Disclosure title="Exact arithmetic inputs and provenance">
      <p>Exact result: <code>{value.value} {value.unit}</code></p>
      {value.years != null && <p>Fiscal interval: {value.years} years.</p>}
      <div className="table-wrap" tabIndex={0} aria-label="Exact calculation inputs">
        <table className="mf-table">
          <thead><tr><th scope="col">Input</th><th scope="col" className="number">Exact persisted value</th></tr></thead>
          <tbody>{value.inputs.map((fact, index) => <tr key={fact.fact_id || index}>
            <th scope="row">{fact.ticker} FY{fact.fiscal_year} · {label(fact.metric)}</th>
            <td className="number"><code>{fact.value} {fact.unit}</code></td>
          </tr>)}</tbody>
        </table>
      </div>
      <JsonDetails title="Complete calculation record" value={value}/>
    </Disclosure>
  </article>;
}

function EvidenceReader({
  record,
  ordinal,
  cited,
  inspect,
  close,
}: {
  record: Evidence;
  ordinal: number;
  cited: boolean;
  inspect: (record: Evidence) => void;
  close: () => void;
}) {
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    heading.current?.focus({preventScroll: true});
  }, [record.evidence_id]);

  return <section className="mf-source-reader" aria-label={`Evidence ${ordinal} source reader`}>
    <header className="mf-source-reader-header">
      <div>
        <span className="mf-eyebrow">Evidence {ordinal}</span>
        <h3 tabIndex={-1} ref={heading}>
          {companyName(record.ticker)} · FY{record.fiscal_year}
        </h3>
      </div>
      <button type="button" className="mf-icon-button" onClick={close} aria-label="Close evidence reader">
        <X size={18} aria-hidden="true"/>
      </button>
    </header>

    <div className="mf-source-reader-context">
      <MetricStatus tone={cited ? 'blue' : 'neutral'}>
        {cited ? 'Cited in this response' : 'Selected, not cited'}
      </MetricStatus>
      <span>{record.fact_id ? 'Financial fact evidence' : 'Filing passage'}</span>
    </div>

    <div className="mf-source-reader-section">
      <span>Recorded section</span>
      <strong>{record.section || 'Not recorded'}</strong>
      {record.subsection && <p>{record.subsection}</p>}
    </div>

    <blockquote className="mf-source-passage">{record.text}</blockquote>

    <dl className="mf-source-primary-meta">
      <div><dt>SEC accession</dt><dd><code>{record.accession_number || 'Not recorded'}</code></dd></div>
      <div><dt>Reporting period</dt><dd>{record.period_start ? `${record.period_start} to ` : ''}{record.period_end || 'Not recorded'}</dd></div>
      <div><dt>Filing date</dt><dd>{record.filing_date || 'Not recorded'}</dd></div>
    </dl>

    <div className="mf-source-reader-actions">
      <SourceLink url={record.source_url}>Original SEC source</SourceLink>
      <button type="button" className="mf-text-button" onClick={() => inspect(record)}>Open provenance explorer →</button>
    </div>

    <Disclosure title="Evidence identity and retrieval metadata">
      <dl className="detail-grid">
        <div><dt>Evidence ID</dt><dd><code>{record.evidence_id}</code></dd></div>
        <div><dt>Chunk ID</dt><dd><code>{record.chunk_id || 'Not recorded / not applicable'}</code></dd></div>
        <div><dt>Technical source location</dt><dd>{record.location || 'Not recorded'}</dd></div>
        <div><dt>Reranker relevance</dt><dd>{typeof record.reranker_score === 'number' && Number.isFinite(record.reranker_score) ? record.reranker_score.toFixed(4) : 'Not recorded'}</dd></div>
      </dl>
      <p>Reranker relevance is not answer-confidence probability. Missing rank fields and page numbers are not inferred.</p>
      <JsonDetails title="Complete evidence record" value={record}/>
    </Disclosure>
  </section>;
}

export function ResearchAnswer({
  result,
  inspect,
}: {
  result: Research;
  inspect: (record: Evidence) => void;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showFindings, setShowFindings] = useState(false);

  useEffect(() => {
    setSelectedId(null);
    setShowFindings(false);
  }, [result]);

  const deterministic = !result.abstained &&
    result.grounding_status === 'deterministic_validated';

  const primary = deterministic &&
    result.question_type === 'FACT' &&
    result.facts.length === 1 &&
    result.calculations.length === 0
    ? result.facts[0]
    : deterministic &&
      result.question_type === 'CALCULATION' &&
      result.calculations.length === 1
      ? result.calculations[0]
      : null;

  const selected = result.evidence.find(record => record.evidence_id === selectedId);
  const selectedIndex = selected
    ? result.evidence.findIndex(record => record.evidence_id === selected.evidence_id)
    : -1;

  const citationIds = new Set(result.citation_ids);
  const citedCount = result.evidence.filter(record => citationIds.has(record.evidence_id)).length;
  const llm = object(result.trace.llm);

  const sources = result.evidence.filter((record, index, records) =>
    records.findIndex(other =>
      other.ticker === record.ticker &&
      other.fiscal_year === record.fiscal_year &&
      other.accession_number === record.accession_number &&
      other.source_url === record.source_url,
    ) === index,
  );

  const title = result.abstained
    ? 'An answer could not be supported'
    : primary
      ? [
          primary.ticker ? companyName(primary.ticker) : '',
          primary.fiscal_year ? `FY${primary.fiscal_year}` : '',
          label(primary.metric),
        ].filter(Boolean).join(' · ')
      : result.question_type === 'RISK'
        ? 'Risk disclosure brief'
        : result.question_type === 'COMPARISON'
          ? 'Comparative financial brief'
          : 'Research brief';

  function citationButtons(ids: string[]) {
    return <div className="mf-claim-citations">
      {[...new Set(ids)].map(id => {
        const index = result.evidence.findIndex(record => record.evidence_id === id);
        if (index < 0) return null;
        return <button
          type="button"
          key={id}
          onClick={() => setSelectedId(id)}
          aria-label={`Read evidence ${index + 1}`}
          aria-pressed={selectedId === id}
        >
          <BookOpen size={13} aria-hidden="true"/>
          Evidence {index + 1}
        </button>;
      })}
    </div>;
  }

  return <section className="mf-research-result" aria-label="Research result">
    <header className="mf-research-result-header">
      <div>
        <span className="mf-eyebrow">
          {result.abstained ? 'Request outcome' : deterministic ? 'Validated financial analysis' : 'Filing-based research'}
        </span>
        <h2>{title}</h2>
      </div>
      <MetricStatus tone={result.abstained ? 'amber' : deterministic ? 'teal' : 'blue'}>
        {result.abstained
          ? 'Abstained'
          : deterministic
            ? 'Deterministic'
            : result.facts.length || result.calculations.length
              ? 'Financial data + RAG'
              : 'Narrative RAG'}
      </MetricStatus>
    </header>

    <div className={`mf-research-result-body ${selected ? 'mf-reader-open' : ''}`}>
      <div className="mf-research-brief">
        {result.abstained
          ? <div className="mf-research-abstention">
              <h3>Why no answer was accepted</h3>
              <p>{abstentionExplanation(result)}</p>
              {result.evidence.length > 0 && <p>Selected evidence is available below for inspection. It is not an accepted answer.</p>}
            </div>
          : <>
              {primary && <div className="mf-research-primary">
                <strong>{formatAmount(primary.value, primary.unit, primary.metric)}</strong>
                <span>Validated {primary.unit === 'percentage' ? 'calculation output' : 'financial value'}</span>
                <Disclosure title="Exact result">
                  <code>{primary.value} {primary.unit}</code>
                </Disclosure>
              </div>}

              {result.answer && <section className="mf-research-answer-copy">
                <span className="mf-eyebrow">Answer</span>
                <p>{result.answer}</p>
              </section>}

              {!deterministic && <p className="mf-research-grounding">
                Application citation identities are validated. Semantic claim
                support has not been independently reviewed.
              </p>}

              {result.key_findings.length > 0 && <section className="mf-findings-section">
                <div className="mf-findings-heading">
                  <div><h3>Claim-level findings</h3><p>Inspect individual claims and their associated evidence.</p></div>
                  <button
                    type="button"
                    className="mf-button"
                    aria-expanded={showFindings}
                    onClick={() => setShowFindings(current => !current)}
                  >
                    {showFindings ? 'Hide findings' : `View ${result.key_findings.length} findings`}
                    <ChevronDown size={15} aria-hidden="true"/>
                  </button>
                </div>
                {showFindings && <ol className="mf-research-findings">
                  {result.key_findings.map((finding, index) => <li key={index}>
                    <p>{finding.text}</p>
                    {citationButtons(finding.citation_ids)}
                  </li>)}
                </ol>}
              </section>}
            </>}

        {result.calculations.length > 0 && <section className="mf-research-calculations">
          <SectionHeading eyebrow="Arithmetic, not generation" title="Calculation breakdown"/>
          {result.calculations.map((calculation, index) => <CalculationRecord key={calculation.calculation_id || index} value={calculation}/>)}
        </section>}

        {result.facts.length > 0 && <Disclosure title={`Validated financial inputs · ${result.facts.length} records`}>
          <div className="table-wrap" tabIndex={0} aria-label="Research financial facts">
            <table className="mf-table">
              <thead><tr><th scope="col">Scope</th><th scope="col">Metric</th><th scope="col" className="number">Value</th><th scope="col">Source</th></tr></thead>
              <tbody>{result.facts.map((fact, index) => <tr key={fact.fact_id || index}>
                <th scope="row">{fact.ticker}<small>FY{fact.fiscal_year}</small></th>
                <td>{label(fact.metric)}</td>
                <td className="number">{formatAmount(fact.value, fact.unit, fact.metric)}</td>
                <td><SourceLink url={fact.source_url}>SEC filing</SourceLink></td>
              </tr>)}</tbody>
            </table>
          </div>
          <JsonDetails title="Exact financial inputs and lineage" value={result.facts}/>
        </Disclosure>}

        <section className="mf-research-evidence-index">
          <div className="mf-evidence-index-heading">
            <h3>Supporting evidence</h3>
            <span>{result.evidence.length} selected · {citedCount} cited</span>
          </div>
          {result.evidence.length
            ? <div className="mf-evidence-reference-list">
                {result.evidence.map((record, index) => <button
                  key={record.evidence_id}
                  type="button"
                  className={selectedId === record.evidence_id ? 'mf-evidence-reference selected' : 'mf-evidence-reference'}
                  onClick={() => setSelectedId(record.evidence_id)}
                  aria-pressed={selectedId === record.evidence_id}
                >
                  <span className="mf-reference-number">{index + 1}</span>
                  <span className="mf-reference-description">
                    <strong>{companyName(record.ticker)} · FY{record.fiscal_year}</strong>
                    <span>{record.section || 'Supporting source evidence'}</span>
                  </span>
                  <span className="mf-reference-use">{citationIds.has(record.evidence_id) ? 'Cited' : 'Selected'}</span>
                  <ArrowRight size={16} aria-hidden="true"/>
                </button>)}
              </div>
            : <p className="mf-fineprint">No evidence records were returned for this request.</p>}
        </section>

        {sources.length > 0 && <Disclosure title={`Original sources · ${sources.length} filings`}>
          <div className="mf-research-source-list">
            {sources.map((record, index) => <div key={index}>
              <FileText size={18} aria-hidden="true"/>
              <div><strong>{companyName(record.ticker)} · FY{record.fiscal_year}</strong><span>{record.accession_number || 'Accession not recorded'}</span></div>
              <SourceLink url={record.source_url}>Open source</SourceLink>
            </div>)}
          </div>
        </Disclosure>}

        <Disclosure title="Technical details and execution trace">
          <dl className="detail-grid">
            <div><dt>Question classification</dt><dd>{label(result.question_type)}</dd></div>
            <div><dt>Accepted provider / model</dt><dd>{result.provider || 'None'} · {result.model || 'Not recorded / not applicable'}</dd></div>
            <div><dt>Request ID</dt><dd><code>{result.request_id}</code></dd></div>
            <div><dt>Grounding status</dt><dd>{label(result.grounding_status)}</dd></div>
            <div><dt>Recorded server latency</dt><dd>{Number.isFinite(result.latency_ms) ? `${(result.latency_ms / 1000).toFixed(2)} s` : 'Not recorded'}</dd></div>
            <div><dt>Fallback flag</dt><dd>{result.fallback_used ? 'Yes — inspect metadata' : 'No'}</dd></div>
            {result.abstention_reason && <div><dt>Recorded reason</dt><dd><code>{result.abstention_reason}</code></dd></div>}
          </dl>
          {llm.status === 'response_rejected' && <p className="notice warning">A provider response was received but rejected. It was not accepted as the answer.</p>}
          {result.fallback && <JsonDetails title="Fallback metadata" value={result.fallback}/>}
          <JsonDetails title="Execution stages" value={result.trace}/>
          <p>Execution metadata is not hidden model reasoning.</p>
        </Disclosure>
      </div>

      {selected && <EvidenceReader
        record={selected}
        ordinal={selectedIndex + 1}
        cited={citationIds.has(selected.evidence_id)}
        inspect={inspect}
        close={() => setSelectedId(null)}
      />}
    </div>
  </section>;
}

const STARTING_POINTS = [
  {
    type: 'Verify',
    title: 'A reported financial value',
    question: "What was Apple's revenue in FY2024?",
  },
  {
    type: 'Calculate',
    title: 'Growth across fiscal years',
    question: "What was Microsoft's revenue growth from FY2023 to FY2024?",
  },
  {
    type: 'Investigate',
    title: 'Risk in a filing disclosure',
    question: 'What risks did Amazon identify in FY2024?',
  },
];

export default function ResearchWorkspace({
  initialQuestion = '',
  inspect,
}: {
  initialQuestion?: string;
  inspect: (record: Evidence) => void;
}) {
  const id = useId();
  const [question, setQuestion] = useState(initialQuestion);
  const [ticker, setTicker] = useState<Ticker | ''>('');
  const [year, setYear] = useState('');
  const [result, setResult] = useState<Research | null>(null);
  const [submittedQuestion, setSubmittedQuestion] = useState('');
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const [cancelled, setCancelled] = useState(false);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => setQuestion(initialQuestion), [initialQuestion]);

  function cancelWaiting() {
    controller.current?.abort();
    controller.current = null;
    setBusy(false);
    setCancelled(true);
  }

  async function submit() {
    if (busy || controller.current) return;

    const text = question.trim();

    if (text.length < 5 || text.length > 2000) {
      setError(new Error('Enter a question between 5 and 2,000 characters.'));
      return;
    }

    const request = new AbortController();
    controller.current = request;
    setBusy(true);
    setCancelled(false);
    setError(null);
    setResult(null);
    setSubmittedQuestion(text);

    try {
      const response = await api<Research>('research', {
        question: text,
        tickers: ticker ? [ticker] : [],
        years: year ? [Number(year)] : [],
      }, request.signal);

      if (!request.signal.aborted && controller.current === request) {
        setResult(response);
      }
    } catch (failure) {
      if (!request.signal.aborted && controller.current === request) {
        setError(failure instanceof Error ? failure : new Error('Research failed.'));
      }
    } finally {
      if (controller.current === request) {
        controller.current = null;
        setBusy(false);
      }
    }
  }

  return <div className="mf-research-workspace">
    <section className="mf-research-composer">
      <div className="mf-research-composer-title">
        <Search size={19} aria-hidden="true"/>
        <label htmlFor={id}>What would you like to investigate?</label>
        <span>SEC filings · FY2022–FY2024</span>
      </div>
      <form onSubmit={event => {event.preventDefault(); void submit();}}>
        <div className="mf-question-entry">
          <textarea
            id={id}
            value={question}
            onChange={event => setQuestion(event.target.value)}
            onKeyDown={event => {
              if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229) return;
              event.preventDefault();
              if (!event.repeat) event.currentTarget.form?.requestSubmit();
            }}
            minLength={5}
            maxLength={2000}
            rows={2}
            required
            placeholder="Ask about a financial value, compare companies, or examine a filing disclosure."
          />
          <button type="submit" className="mf-research-submit" disabled={busy}>
            {busy ? 'Researching…' : 'Research'}<ArrowRight size={17} aria-hidden="true"/>
          </button>
        </div>
        <div className="mf-question-controls">
          <details className="mf-question-scope">
            <summary>Optional scope defaults</summary>
            <div>
              <label>Company
                <select value={ticker} onChange={event => setTicker(event.target.value as Ticker | '')}>
                  <option value="">From question</option>
                  {COMPANIES.map(company => <option key={company.ticker} value={company.ticker}>{company.name}</option>)}
                </select>
              </label>
              <label>Fiscal year
                <select value={year} onChange={event => setYear(event.target.value)}>
                  <option value="">From question</option>
                  {YEARS.map(value => <option key={value} value={value}>FY{value}</option>)}
                </select>
              </label>
              <p>Explicit scope in the question takes precedence.</p>
            </div>
          </details>
          {busy
            ? <button type="button" className="mf-text-button" onClick={cancelWaiting}>Cancel waiting</button>
            : <span>Financial calculations remain LLM independent.</span>}
        </div>
      </form>
    </section>

    {busy && <Loading>Processing the request. No estimated progress is available.</Loading>}
    {cancelled && <p className="notice">Browser waiting was cancelled. Server or provider work may continue.</p>}
    {error && <ErrorNotice error={error}/>}

    {result && <>
      <div className="mf-submitted-question">
        <span>Submitted question</span><p>{submittedQuestion}</p>
      </div>
      <ResearchAnswer result={result} inspect={inspect}/>
    </>}

    {!result && !busy && !error && !cancelled && <section className="mf-research-start">
      <SectionHeading
        eyebrow="Suggested workflows—not recent activity"
        title="Start with a question. Keep the source in view."
        description="These examples populate the input. They do not supply predetermined answers."
      />
      <div className="mf-research-starting-points">
        {STARTING_POINTS.map((point, index) => <button
          type="button"
          key={point.question}
          onClick={() => setQuestion(point.question)}
        >
          <span className="mf-workflow-number">0{index + 1}</span>
          <span className="mf-workflow-type">{point.type}</span>
          <strong>{point.title}</strong>
          <p>{point.question}</p>
          <ArrowRight size={18} aria-hidden="true"/>
        </button>)}
      </div>
      <div className="mf-research-boundaries">
        <div><strong>Financial facts</strong><span>Validated store records and Python calculations.</span></div>
        <div><strong>Narrative research</strong><span>Retrieved filing evidence and structured provider synthesis.</span></div>
        <div><strong>Unsupported requests</strong><span>An explanation—not an invented answer or forecast.</span></div>
      </div>
    </section>}
  </div>;
}