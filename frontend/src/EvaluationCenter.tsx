import {useEffect, useState} from 'react';
import {
  Activity,
  Download,
  FlaskConical,
  Layers,
  ShieldCheck,
  X,
} from 'lucide-react';
import type {Evaluation} from './api';
import {
  JsonDetails,
  ResourceState,
  label,
  type Remote,
} from './ui';
import {
  Disclosure,
  MeasurementBar,
  MetricStatus,
  MetricSummary,
  Pagination,
  SectionHeading,
  type MetricTone,
} from './DesignSystem';

type ObjectValue = Record<string, unknown>;

function object(value: unknown): ObjectValue {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as ObjectValue
    : {};
}

function objects(value: unknown): ObjectValue[] {
  return Array.isArray(value)
    ? value.filter(item =>
        typeof item === 'object' && item !== null && !Array.isArray(item),
      ) as ObjectValue[]
    : [];
}

function text(value: unknown, fallback = 'Not recorded'): string {
  return typeof value === 'string' && value.trim() ? value : fallback;
}

function integer(value: unknown): number | null {
  return typeof value === 'number' &&
    Number.isInteger(value) &&
    value >= 0
    ? value
    : null;
}

function count(value: unknown): string {
  return integer(value)?.toLocaleString('en-US') ?? 'Not recorded';
}

function measuredFraction(value: unknown, denominator: unknown): number | null {
  const eligible = integer(denominator);
  return typeof value === 'number' &&
    Number.isFinite(value) &&
    value >= 0 &&
    value <= 1 &&
    eligible !== null &&
    eligible > 0
    ? value
    : null;
}

function fraction(value: unknown, denominator: unknown): string {
  if (value == null) return 'Not measured';
  const measured = measuredFraction(value, denominator);
  return measured === null ? 'Check artifact' : `${(measured * 100).toFixed(2)}%`;
}

function milliseconds(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0
    ? `${value.toLocaleString('en-US', {maximumFractionDigits: 2})} ms`
    : 'Not measured';
}

function outcomeTone(status: string): MetricTone {
  if (status.includes('failed')) return 'red';
  if (status.startsWith('skipped')) return 'amber';
  if (status === 'executed' || status === 'retrieval_executed') return 'blue';
  return 'neutral';
}

const RETRIEVAL_METRICS = [
  ['recall_at_5', 'Recall@5', 'Relevant reference evidence found in the first five results.'],
  ['recall_at_10', 'Recall@10', 'Relevant reference evidence found in the first ten results.'],
  ['precision_at_5', 'Precision@5', 'Relevant results divided by five ranking positions.'],
  ['mrr', 'Mean reciprocal rank', 'Reciprocal rank of the first relevant result.'],
  ['hit_rate', 'Hit rate', 'Questions with relevant evidence in the scored ranking.'],
] as const;

const ANSWER_METRICS = [
  ['structured_regression_correctness', 'Structured agreement', 'structured', false],
  ['citation_id_validity', 'Citation-ID validity', 'citation', false],
  ['unsupported_abstention_correctness', 'Unsupported-policy abstention', 'unsupported_abstention', false],
  ['false_abstention_on_structured_references', 'False abstention', 'false_abstention', true],
  ['routing_type_agreement', 'Question-type agreement', 'routing', false],
] as const;

function ProviderTable({title, value}: {title: string; value: unknown}) {
  const rows = objects(value);

  return <section>
    <h3>{title}</h3>
    {rows.length
      ? <div className="table-wrap" tabIndex={0} aria-label={title}>
          <table className="mf-table">
            <thead>
              <tr>
                <th scope="col">Provider / model</th>
                <th scope="col">Fallback</th>
                <th scope="col" className="number">Responses</th>
              </tr>
            </thead>
            <tbody>{rows.map((row, index) => <tr key={index}>
              <th scope="row">{text(row.provider)}<small><code>{text(row.model)}</code></small></th>
              <td>{row.fallback_used === true ? 'Yes' : row.fallback_used === false ? 'No' : 'Not recorded'}</td>
              <td className="number">{count(row.response_count)}</td>
            </tr>)}</tbody>
          </table>
        </div>
      : <div className="mf-inline-empty">
          <span>No recorded responses</span>
          <p>This category contains no provider-response records.</p>
        </div>}
  </section>;
}

export default function EvaluationCenter({
  resource,
}: {
  resource: Remote<Evaluation>;
}) {
  const data = resource.data;
  const [filter, setFilter] = useState('ALL');
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<ObjectValue | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  useEffect(() => {
    setSelected(null);
    setFilter('ALL');
    setSearch('');
    setPage(1);
  }, [data]);

  const completed = data?.status === 'completed';
  const unexecuted = data?.status === 'not_yet_evaluated';
  const metrics = object(data?.metrics);
  const denominators = object(data?.denominators);
  const retrieval = object(metrics.retrieval);
  const statuses = object(data?.record_status_counts);
  const stages = object(data?.stage_latency_ms);
  const llm = object(data?.llm);
  const records = objects(data?.records);

  const filtered = records.filter(record => {
    const matchesStatus = filter === 'ALL' || text(record.status, 'unknown') === filter;
    const content = [
      record.id,
      record.question,
      record.expected_question_type,
      record.actual_question_type,
    ].filter(value => typeof value === 'string').join(' ').toLowerCase();
    return matchesStatus && content.includes(search.trim().toLowerCase());
  });

  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, pageCount);
  const visible = filtered.slice(
    (currentPage - 1) * pageSize,
    currentPage * pageSize,
  );

  const outcomeRows = Object.entries(statuses).flatMap(([name, value]) => {
    const total = integer(value);
    return total === null ? [] : [{name, count: total}];
  });
  const outcomeTotal = outcomeRows.reduce((sum, row) => sum + row.count, 0);
  const datasetCount = integer(denominators.dataset);
  const outcomesMatchDataset = datasetCount !== null && outcomeTotal === datasetCount;

  function download() {
    if (!data) return;
    const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = completed
      ? 'financial-evaluation-artifact.json'
      : 'financial-evaluation-state.json';
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return <div className="mf-quality">
    <ResourceState resource={resource}/>

    {data && <section className="mf-quality-banner">
      <div className="mf-quality-banner-main">
        <span className="mf-eyebrow">System quality / recorded evidence</span>
        <h2>{unexecuted ? 'Ready for measurement. Not yet evaluated.' : 'Know what was tested. See what remains unknown.'}</h2>
        <p>{unexecuted
          ? 'No completed evaluation artifact is available. A working index and passing unit tests are not answer-quality scores.'
          : 'Financial regression, policy checks, retrieval quality, and semantic review are separate measurements.'}</p>
      </div>
      <div className="mf-quality-banner-actions">
        <MetricStatus tone={completed ? 'teal' : unexecuted ? 'neutral' : 'amber'}>
          {completed ? 'Run completed' : label(data.status || 'unknown')}
        </MetricStatus>
        <button type="button" className="mf-button mf-button-on-dark" onClick={download}>
          <Download size={16} aria-hidden="true"/>Export {unexecuted ? 'state' : 'artifact'}
        </button>
      </div>
      <div className="mf-quality-runline">
        <span><strong>Mode</strong>{label(text(data.mode, 'not recorded'))}</span>
        <span><strong>Generation</strong>{data.allow_llm === true ? 'Explicitly permitted' : data.allow_llm === false ? 'Disabled' : 'Not recorded'}</span>
        <span><strong>Recorded</strong>{text(data.created_at)}</span>
      </div>
    </section>}

    {data && !completed && !unexecuted && <div className="notice warning">
      This artifact does not report a completed run. Records remain
      inspectable, but aggregate scores are not presented as completed evaluation.
    </div>}

    {data && unexecuted && <>
      <section className="fluxa-card fluxa-eval-intent-card" style={{padding:'16px',background:'var(--fi-surface)',border:'1px solid var(--fi-border)',borderRadius:'12px',display:'grid',gap:'12px'}}>
        <div style={{display:'flex',justifyContent:'space-between',gap:'16px',flexWrap:'wrap',alignItems:'center'}}>
          <div style={{display:'grid',gap:'6px',maxWidth:'640px'}}>
            <span className="mf-eyebrow" style={{fontSize:'11px',textTransform:'uppercase',letterSpacing:'0.8px',color:'var(--fi-text-tertiary)'}}>Evaluation status</span>
            <h3 style={{fontSize:'16px',margin:0,lineHeight:'1.3'}}>Evaluation is supported by the system, but no completed evaluation run is currently recorded.</h3>
            <p style={{fontSize:'12px',color:'var(--fi-text-secondary)',margin:0,lineHeight:'1.6'}}>Retrieval quality, answer validation, and semantic review are separate measurements that require a completed evaluation run with reviewed references. No scores are inferred from indexes, unit tests, or API health.</p>
          </div>
          <div style={{display:'flex',gap:'8px',flexWrap:'wrap',alignItems:'center'}}>
            <span className="fluxa-badge neutral" style={{fontSize:'11px'}}>No artifact yet</span>
            <span className="fluxa-badge neutral" style={{fontSize:'11px'}}>Truthful status</span>
            <span className="fluxa-badge blue" style={{fontSize:'11px'}}>Supported: retrieval · answer · semantic</span>
          </div>
        </div>
        <div style={{display:'grid',gridTemplateColumns:'repeat(3, minmax(0,1fr))',gap:'12px',fontSize:'11px',color:'var(--fi-text-tertiary)',borderTop:'1px solid var(--fi-border-subtle)',paddingTop:'12px'}}>
          <span><strong style={{color:'var(--fi-text-primary)'}}>Recorded:</strong> configuration, dataset version, corpus version</span>
          <span><strong style={{color:'var(--fi-text-primary)'}}>Not recorded:</strong> Recall@5/10, Precision@5, MRR, hit rate, answer checks, semantic grades</span>
          <span><strong style={{color:'var(--fi-text-primary)'}}>Export:</strong> truthful state only, no fabricated scores</span>
        </div>
      </section>

      <div className="mf-quality-empty fluxa-eval-status-grid">
        <section className="fluxa-card fluxa-eval-card">
          <div className="fluxa-card-header" style={{padding:'12px 14px'}}>
            <div style={{display:'flex',alignItems:'center',gap:'8px'}}>
              <span style={{width:'28px',height:'28px',borderRadius:'8px',background:'var(--fi-surface-muted)',border:'1px solid var(--fi-border-subtle)',display:'grid',placeItems:'center'}}><FlaskConical size={16}/></span>
              <div>
                <span className="mf-eyebrow" style={{fontSize:'10px'}}>RETRIEVAL QUALITY</span>
                <h3 style={{fontSize:'13px',margin:'2px 0 0'}}>Can the system find the right evidence?</h3>
              </div>
            </div>
            <MetricStatus tone="neutral">Not measured</MetricStatus>
          </div>
          <div className="fluxa-card-body" style={{padding:'12px 14px',display:'grid',gap:'10px'}}>
            <p style={{fontSize:'12px',color:'var(--fi-text-secondary)',margin:0,lineHeight:'1.5'}}>Recall@5, Recall@10, Precision@5, MRR and hit rate require a completed evaluation run with reviewed, index-matched references.</p>
            <div style={{display:'flex',flexWrap:'wrap',gap:'6px'}}>
              <span className="fluxa-badge neutral" style={{fontSize:'10px'}}>Recall@5</span>
              <span className="fluxa-badge neutral" style={{fontSize:'10px'}}>Recall@10</span>
              <span className="fluxa-badge neutral" style={{fontSize:'10px'}}>Precision@5</span>
              <span className="fluxa-badge neutral" style={{fontSize:'10px'}}>MRR</span>
              <span className="fluxa-badge neutral" style={{fontSize:'10px'}}>Hit rate</span>
            </div>
            <p className="mf-fineprint" style={{margin:0}}>Evidence required: reviewed reference evidence, index-matched rankings, scored retrieval requests. Missing rankings do not become zero scores.</p>
          </div>
        </section>
        <section className="fluxa-card fluxa-eval-card">
          <div className="fluxa-card-header" style={{padding:'12px 14px'}}>
            <div style={{display:'flex',alignItems:'center',gap:'8px'}}>
              <span style={{width:'28px',height:'28px',borderRadius:'8px',background:'var(--fi-surface-muted)',border:'1px solid var(--fi-border-subtle)',display:'grid',placeItems:'center'}}><ShieldCheck size={16}/></span>
              <div>
                <span className="mf-eyebrow" style={{fontSize:'10px'}}>ANSWER VALIDATION</span>
                <h3 style={{fontSize:'13px',margin:'2px 0 0'}}>Does the result satisfy the recorded reference?</h3>
              </div>
            </div>
            <MetricStatus tone="amber">Pending</MetricStatus>
          </div>
          <div className="fluxa-card-body" style={{padding:'12px 14px',display:'grid',gap:'10px'}}>
            <p style={{fontSize:'12px',color:'var(--fi-text-secondary)',margin:0,lineHeight:'1.5'}}>Answer checks require actual evaluation execution and reference validation. Financial regression agreement, citation-ID validity, routing and abstention checks need a run.</p>
            <div style={{display:'flex',flexWrap:'wrap',gap:'6px'}}>
              <span className="fluxa-badge neutral" style={{fontSize:'10px'}}>Structured agreement</span>
              <span className="fluxa-badge neutral" style={{fontSize:'10px'}}>Citation-ID validity</span>
              <span className="fluxa-badge neutral" style={{fontSize:'10px'}}>Abstention policy</span>
              <span className="fluxa-badge neutral" style={{fontSize:'10px'}}>Routing type</span>
            </div>
            <p className="mf-fineprint" style={{margin:0}}>Evidence required: executed answer requests, eligible reference denominators, recorded question types. Valid IDs do not imply semantic support.</p>
          </div>
        </section>
        <section className="fluxa-card fluxa-eval-card">
          <div className="fluxa-card-header" style={{padding:'12px 14px'}}>
            <div style={{display:'flex',alignItems:'center',gap:'8px'}}>
              <span style={{width:'28px',height:'28px',borderRadius:'8px',background:'var(--fi-surface-muted)',border:'1px solid var(--fi-border-subtle)',display:'grid',placeItems:'center'}}><Layers size={16}/></span>
              <div>
                <span className="mf-eyebrow" style={{fontSize:'10px'}}>SEMANTIC VALIDATION</span>
                <h3 style={{fontSize:'13px',margin:'2px 0 0'}}>Does the evidence support the claim?</h3>
              </div>
            </div>
            <MetricStatus tone="neutral">Not established</MetricStatus>
          </div>
          <div className="fluxa-card-body" style={{padding:'12px 14px',display:'grid',gap:'10px'}}>
            <p style={{fontSize:'12px',color:'var(--fi-text-secondary)',margin:0,lineHeight:'1.5'}}>Semantic grading requires reviewed grading evidence and cannot be inferred from configuration alone. Correct identifiers do not establish claim support.</p>
            <div style={{display:'flex',flexWrap:'wrap',gap:'6px'}}>
              <span className="fluxa-badge neutral" style={{fontSize:'10px'}}>Groundedness</span>
              <span className="fluxa-badge neutral" style={{fontSize:'10px'}}>Narrative correctness</span>
              <span className="fluxa-badge neutral" style={{fontSize:'10px'}}>Completeness</span>
            </div>
            <p className="mf-fineprint" style={{margin:0}}>Evidence required: human-review grading artifact, groundedness judgments, narrative correctness review. No score is inferred from unit tests or index health.</p>
          </div>
        </section>
      </div>
      <Disclosure title="Evaluation state and measurement boundaries">
        <p>No model benchmark, manual review, or quality score is inferred from configuration. Working indexes and passing unit tests are not evaluation scores.</p>
        <JsonDetails title="Returned state" value={data}/>
      </Disclosure>
    </>}

    {completed && <>
      <section className="mf-quality-summary" aria-label="Evaluation summary">
        <MetricSummary
          title="Answer executions"
          value={count(denominators.answer_requests_executed)}
          detail={`Dataset: ${count(denominators.dataset)} questions`}
        />
        <MetricSummary
          title="Structured agreement"
          value={fraction(metrics.structured_regression_correctness, denominators.structured)}
          detail={`${count(denominators.structured)} eligible references`}
          measured={measuredFraction(metrics.structured_regression_correctness, denominators.structured) !== null}
          tone="teal"
        />
        <MetricSummary
          title="Citation-ID validity"
          value={fraction(metrics.citation_id_validity, denominators.citation)}
          detail={`${count(denominators.citation)} eligible answers; identity only`}
          measured={measuredFraction(metrics.citation_id_validity, denominators.citation) !== null}
          tone="blue"
        />
        <MetricSummary
          title="Policy abstention"
          value={fraction(metrics.unsupported_abstention_correctness, denominators.unsupported_abstention)}
          detail={`${count(denominators.unsupported_abstention)} unsupported references`}
          measured={measuredFraction(metrics.unsupported_abstention_correctness, denominators.unsupported_abstention) !== null}
          tone="teal"
        />
        <MetricSummary
          title="Mean answer latency"
          value={milliseconds(metrics.mean_total_latency_ms)}
          detail="Observed request timing—not a provider benchmark"
          measured={typeof metrics.mean_total_latency_ms === 'number' && Number.isFinite(metrics.mean_total_latency_ms) && metrics.mean_total_latency_ms >= 0}
          tone="neutral"
        />
      </section>

      <div className="mf-quality-columns">
        <section className="mf-quality-section">
          <SectionHeading
            eyebrow="Automated structural checks"
            title="Answer quality"
            description="Eligible denominators remain visible beside every result."
          />
          <div className="mf-answer-measurements">
            {ANSWER_METRICS.map(([key, title, denominator, lowerIsBetter]) => <MeasurementBar
              key={key}
              label={title}
              value={measuredFraction(metrics[key], denominators[denominator])}
              display={fraction(metrics[key], denominators[denominator])}
              detail={`${count(denominators[denominator])} eligible observations · ${lowerIsBetter ? 'lower' : 'higher'} is preferable`}
              lowerIsBetter={lowerIsBetter}
              tone={lowerIsBetter ? 'amber' : 'blue'}
            />)}
          </div>
          <p className="mf-fineprint">
            Store-derived correctness measures regression agreement—not an
            independent audit. Valid citation IDs do not establish claim support.
          </p>
        </section>

        <section className="mf-quality-section mf-retrieval-section">
          <SectionHeading
            eyebrow="Reviewed references required"
            title="Retrieval quality"
            action={<MetricStatus tone={integer(denominators.retrieval_scored) ? 'blue' : 'amber'}>
              {count(denominators.retrieval_scored)} rankings scored
            </MetricStatus>}
          />
          <div className="mf-retrieval-list">
            {RETRIEVAL_METRICS.map(([key, title, definition]) => <div key={key}>
              <div><strong>{title}</strong><p>{definition}</p></div>
              <span className={measuredFraction(retrieval[key], denominators.retrieval_scored) === null ? 'mf-not-measured' : 'mf-result-number'}>
                {fraction(retrieval[key], denominators.retrieval_scored)}
              </span>
            </div>)}
          </div>
          <div className="mf-coverage-note">
            <Activity size={17} aria-hidden="true"/>
            <p>
              {count(denominators.retrieval_requests_attempted)} retrieval-only
              attempts recorded. Missing rankings and unreviewed references
              do not become zero-quality scores.
            </p>
          </div>
          <Disclosure title="Retrieval scoring boundaries">
            <p>These are recorded macro averages. Precision@5 divides by five. Failed attempts without observable rankings are excluded from quality averages and counted separately. Interleaved company/year lists are not globally calibrated relevance scores.</p>
          </Disclosure>
        </section>
      </div>

      <section className="mf-review-boundary">
        <div>
          <span className="mf-eyebrow">A separate quality layer</span>
          <h3>Semantic support is not structural validity.</h3>
          <p>No human-review completion is inferred from a passing citation check.</p>
        </div>
        <dl>
          {[
            ['semantic_groundedness', 'Groundedness'],
            ['narrative_correctness', 'Narrative correctness'],
            ['completeness', 'Completeness'],
          ].map(([key, title]) => <div key={key}>
            <dt>{title}</dt>
            <dd><MetricStatus tone={metrics[key] == null ? 'neutral' : 'amber'}>
              {metrics[key] == null ? 'Not measured' : 'Inspect grading artifact'}
            </MetricStatus></dd>
          </div>)}
        </dl>
      </section>

      <div className="mf-quality-columns">
        <section className="mf-quality-section">
          <SectionHeading eyebrow="Execution coverage" title="What happened in this run"/>
          {outcomeRows.length > 0
            ? <>
                {outcomeTotal > 0 && <div className="mf-outcome-strip" aria-hidden="true">
                  {outcomeRows.filter(row => row.count > 0).map(row => <span
                    key={row.name}
                    className={`mf-tone-${outcomeTone(row.name)}`}
                    style={{width: `${row.count / outcomeTotal * 100}%`}}
                  />)}
                </div>}
                <dl className="mf-outcome-list">
                  {outcomeRows.map(row => <div key={row.name}>
                    <dt><MetricStatus tone={outcomeTone(row.name)}>{label(row.name)}</MetricStatus></dt>
                    <dd>{row.count.toLocaleString('en-US')}</dd>
                  </div>)}
                </dl>
                {!outcomesMatchDataset && <p className="mf-fineprint">
                  Recorded outcome counts do not establish complete dataset
                  coverage. Inspect the artifact denominators.
                </p>}
              </>
            : <div className="mf-inline-empty"><span>No outcome counts recorded</span></div>}
          <p className="mf-fineprint">Executed means a request ran—not that it passed every quality check.</p>
        </section>

        <section className="mf-quality-section">
          <SectionHeading eyebrow="Observed timings" title="Latency profile"/>
          <dl className="mf-latency-grid">
            <div><dt>Mean answer request</dt><dd>{milliseconds(metrics.mean_total_latency_ms)}</dd></div>
            <div><dt>Retrieval-only mean</dt><dd>{milliseconds(metrics.mean_retrieval_attempt_latency_ms)}</dd></div>
            <div><dt>Median answer request</dt><dd>{milliseconds(metrics.median_total_latency_ms)}</dd></div>
            <div><dt>P95 answer request</dt><dd>{milliseconds(metrics.p95_total_latency_ms)}</dd></div>
          </dl>
          {Object.keys(stages).length > 0 && <Disclosure title="Recorded stage measurements">
            <div className="table-wrap" tabIndex={0} aria-label="Recorded stage latency">
              <table className="mf-table">
                <thead><tr><th scope="col">Stage</th><th scope="col" className="number">Mean</th><th scope="col" className="number">Observations</th></tr></thead>
                <tbody>{Object.entries(stages).map(([name, value]) => {
                  const stage = object(value);
                  return <tr key={name}><th scope="row">{label(name)}</th><td className="number">{milliseconds(stage.mean)}</td><td className="number">{count(stage.observations)}</td></tr>;
                })}</tbody>
              </table>
            </div>
          </Disclosure>}
          <p className="mf-fineprint">Cold/warm state and hardware are not normalized. Missing measurements stay unmeasured.</p>
        </section>
      </div>

      <section className="mf-quality-section">
        <SectionHeading
          eyebrow="Provider accounting"
          title="Received is not the same as accepted"
          description="Provider responses are accounted for separately from application requests."
        />
        <div className="mf-quality-columns mf-provider-columns">
          <ProviderTable title="Received by orchestration" value={llm.received_responses}/>
          <ProviderTable title="Accepted into final answers" value={llm.accepted_responses}/>
        </div>
        <Disclosure title="Provider accounting definition">
          <p>{text(llm.count_definition, 'No count definition recorded.')}</p>
          <p>These counts do not establish billing, token consumption, or total HTTP attempts.</p>
        </Disclosure>
      </section>
    </>}

    {data && records.length > 0 && <section className="mf-quality-section mf-records-section">
      <SectionHeading
        eyebrow="Inspect individual outcomes"
        title="Question-level results"
        description="Filter the recorded dataset, then inspect a specific result."
        action={<MetricStatus>{records.length} recorded entries</MetricStatus>}
      />
      <div className="mf-record-filters">
        <input
          aria-label="Search evaluation records"
          placeholder="Search ID, recorded question text, or type"
          value={search}
          onChange={event => {setSearch(event.target.value); setPage(1);}}
        />
        <select
          aria-label="Filter evaluation outcome"
          value={filter}
          onChange={event => {setFilter(event.target.value); setPage(1);}}
        >
          <option value="ALL">All recorded outcomes</option>
          {[...new Set(records.map(record => text(record.status, 'unknown')))].map(status => <option key={status} value={status}>{label(status)}</option>)}
        </select>
      </div>
      <div className="table-wrap" tabIndex={0} aria-label="Paginated evaluation records">
        <table className="mf-table">
          <thead>
            <tr>
              <th scope="col">Question / record</th>
              <th scope="col">Expected → actual</th>
              <th scope="col">Execution</th>
              <th scope="col">Structured check</th>
              <th scope="col"><span className="sr-only">Inspect record</span></th>
            </tr>
          </thead>
          <tbody>{visible.map((entry, index) => <tr key={`${text(entry.id)}-${index}`}>
            <th scope="row">
              <span className="mf-record-id">{text(entry.id)}</span>
              <small>{text(entry.question, 'Question text not recorded in this artifact')}</small>
            </th>
            <td>{text(entry.expected_question_type, '—')} → {text(entry.actual_question_type, '—')}</td>
            <td><MetricStatus tone={outcomeTone(text(entry.status, 'unknown'))}>{label(text(entry.status, 'unknown'))}</MetricStatus></td>
            <td><MetricStatus tone={entry.structured_reference_correct === true ? 'teal' : entry.structured_reference_correct === false ? 'red' : 'neutral'}>
              {entry.structured_reference_correct === true ? 'Pass' : entry.structured_reference_correct === false ? 'Fail' : 'Not graded'}
            </MetricStatus></td>
            <td><button type="button" className="mf-text-button" onClick={() => setSelected(entry)} aria-label={`Inspect evaluation record ${text(entry.id)}`}>Inspect →</button></td>
          </tr>)}</tbody>
        </table>
      </div>
      {!visible.length && <div className="mf-inline-empty"><span>No matching records</span><p>Change the search or outcome filter.</p></div>}
      <Pagination
        page={currentPage}
        pageSize={pageSize}
        total={filtered.length}
        onPageChange={setPage}
        onPageSizeChange={size => {setPageSize(size); setPage(1);}}
        label="matching records"
      />
      {selected && <aside className="mf-selected-record" aria-label="Selected evaluation record">
        <div className="mf-selected-record-heading">
          <div><span className="mf-eyebrow">Selected record</span><h3>{text(selected.id)}</h3></div>
          <button type="button" className="mf-icon-button" onClick={() => setSelected(null)} aria-label="Close selected record"><X size={18} aria-hidden="true"/></button>
        </div>
        <p>{text(selected.question, 'The runner did not record question text in this artifact. The record ID remains available for dataset lookup.')}</p>
        <JsonDetails title="Complete recorded result" value={selected}/>
      </aside>}
    </section>}

    {data && !unexecuted && <Disclosure title="Run identity, reproducibility, and limitations">
      <dl className="detail-grid">
        <div><dt>Evaluation policy</dt><dd><code>{text(data.evaluation_version)}</code></dd></div>
        <div><dt>Dataset version</dt><dd><code>{text(data.dataset_version)}</code></dd></div>
        <div><dt>Corpus version</dt><dd><code>{text(data.corpus_version)}</code></dd></div>
        <div><dt>Index signature</dt><dd><code>{text(data.index_signature)}</code></dd></div>
        <div><dt>Run wall time</dt><dd>{milliseconds(data.evaluation_wall_time_ms)}</dd></div>
      </dl>
      <JsonDetails title="Executed configuration and any recorded model/seed" value={data.configuration}/>
      {Array.isArray(data.limitations)
        ? <ul>{data.limitations.filter((item): item is string => typeof item === 'string').map((item, index) => <li key={index}>{item}</li>)}</ul>
        : <p>{text(data.limitations, 'No limitations field recorded.')}</p>}
      <p>A single run does not establish BGE base-versus-large performance. No model-comparison result is inferred here.</p>
      <JsonDetails title="Metric definitions and eligibility" value={data.definitions}/>
      <JsonDetails title="Complete evaluation artifact" value={data}/>
    </Disclosure>}
  </div>;
}