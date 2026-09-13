export type Ticker = 'AAPL' | 'MSFT' | 'AMZN';

export type Report = {
  company: string;
  ticker: Ticker;
  fiscal_year: number;
  filing_type: string;
  status: string;
  document_id?: string;
  accession_number: string | null;
  filing_date: string | null;
  period_end: string | null;
  source_url: string | null;
  content_sha256?: string;
  block_count?: number;
  stages?: Record<string, unknown>;
  identity?: Record<string, unknown>;
  error_category?: string;
};

export type Fact = {
  fact_id?: string;
  company?: string;
  ticker: Ticker;
  fiscal_year: number;
  metric: string;
  value: string;
  unit: string;
  metric_definition?: string;
  concept?: string;
  accession_number?: string;
  period_start?: string | null;
  period_end?: string;
  source_url?: string;
  source?: string;
  reconciliation_status?: string;
  reconciliation?: Record<string, unknown>;
};

export type Calculation = {
  calculation_id?: string;
  ticker?: Ticker;
  fiscal_year?: number;
  metric: string;
  value: string;
  unit: string;
  formula: string;
  inputs: Fact[];
  years?: number | null;
};

export type Evidence = {
  evidence_id: string;
  ticker: Ticker;
  fiscal_year: number;
  company?: string;
  filing_date?: string;
  period_start?: string | null;
  period_end?: string;
  accession_number?: string;
  source_url?: string;
  source?: string;
  section?: string;
  subsection?: string | null;
  location?: string;
  text: string;
  chunk_id?: string | null;
  fact_id?: string;
  retrieval_score?: number | null;
  reranker_score?: number | null;
  reranker_logit?: number | null;
  source_spans?: unknown[];
  reconciliation?: Record<string, unknown>;
};

export type Research = {
  request_id: string;
  question_type: string;
  answer: string;
  key_findings: {text: string; citation_ids: string[]}[];
  calculations: Calculation[];
  facts: Fact[];
  citation_ids: string[];
  evidence: Evidence[];
  provider: string | null;
  model: string | null;
  latency_ms: number;
  grounded: boolean;
  grounding_status: string;
  fallback_used: boolean;
  fallback: Record<string, unknown> | null;
  abstained: boolean;
  abstention_reason: string | null;
  trace: Record<string, unknown>;
};

export type AnalyticsRow = {
  ticker: Ticker;
  fiscal_year: number;
  values: Record<string, string>;
  evidence: Fact[];
  calculations: Calculation[];
  unavailable_metrics?: Record<string, string>;
};

export type Analytics = {
  status?: string;
  rows: AnalyticsRow[];
  issues: unknown[];
  corpus_version: string | null;
  validation_scope?: string;
};

export type IngestionAudit = {
  status?: string;
  run_id?: string;
  started_at?: string;
  finished_at?: string | null;
  publication?: string;
  index?: string;
  error_category?: string;
  matches_published_corpus?: boolean | null;
  slots?: {
    ticker: Ticker;
    fiscal_year: number;
    status: string;
    stages: Record<string, unknown>;
    error_category?: string;
  }[];
};

export type SystemStatus = {
  status_scope: string;
  corpus_valid: boolean;
  corpus_version: string | null;
  validated_report_count: number;
  expected_report_count: number;
  corpus_error?: string | null;
  index_present: boolean;
  configuration_compatible: boolean;
  index_loaded: boolean;
  index_artifacts_present: boolean;
  index_ready: boolean;
  index_integrity?: string;
  index_error?: string | null;
  retrieval_models_loaded: boolean;
  financial_fact_count: number;
  financial_validated_fact_count: number;
  financial_store_ready: boolean;
  financial_coverage_complete: boolean;
  financial_store_error?: string | null;
  financial?: Record<string, unknown>;
  rag_ready: boolean;
  narrative_locally_ready_to_attempt: boolean;
  provider: string;
  model: string;
  primary_configuration_complete: boolean;
  api_key_configured: boolean | null;
  provider_authentication: string;
  provider_reachability: string;
  structured_output_capability: string;
  fallback_enabled: boolean;
  last_ingestion?: IngestionAudit;
  readiness_scope?: string;
  note?: string;
  manifest?: Record<string, unknown> | null;
};

export type Evaluation = {
  status?: string;
  metrics?: Record<string, unknown> | null;
  [key: string]: unknown;
};

export class ApiError extends Error {
  constructor(
    message: string,
    public status?: number,
    public requestId?: string,
    public retryAfter?: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

type ObjectValue = Record<string, unknown>;

const TICKERS = new Set(['AAPL', 'MSFT', 'AMZN']);
const FISCAL_YEARS = new Set([2022, 2023, 2024]);
const QUESTION_TYPES = new Set([
  'FACT',
  'COMPARISON',
  'CALCULATION',
  'MULTI_DOCUMENT',
  'EXPLANATION',
  'RISK',
  'UNSUPPORTED',
]);

const DECIMAL = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;

function isObject(value: unknown): value is ObjectValue {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function requireCondition(condition: boolean): asserts condition {
  if (!condition) throw new Error('Invalid API response structure');
}

function record(value: unknown): ObjectValue {
  requireCondition(isObject(value));
  return value;
}

function stringValue(value: unknown): value is string {
  return typeof value === 'string';
}

function nonemptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function nullableString(value: unknown): boolean {
  return value === null || typeof value === 'string';
}

function decimalString(value: unknown): value is string {
  return typeof value === 'string' && DECIMAL.test(value);
}

function finiteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function nonnegativeInteger(value: unknown): boolean {
  return finiteNumber(value) && Number.isInteger(value) && value >= 0;
}

function strings(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(nonemptyString);
}

function validateOptionalStrings(value: ObjectValue, fields: string[]) {
  for (const field of fields) {
    requireCondition(value[field] === undefined || nullableString(value[field]));
  }
}

function validateScope(value: ObjectValue) {
  requireCondition(
    typeof value.ticker === 'string' &&
    TICKERS.has(value.ticker) &&
    typeof value.fiscal_year === 'number' &&
    FISCAL_YEARS.has(value.fiscal_year),
  );
}

function validateFact(value: unknown) {
  const item = record(value);
  validateScope(item);
  requireCondition(
    nonemptyString(item.metric) &&
    decimalString(item.value) &&
    nonemptyString(item.unit),
  );

  validateOptionalStrings(item, [
    'fact_id',
    'company',
    'metric_definition',
    'concept',
    'accession_number',
    'period_start',
    'period_end',
    'source_url',
    'source',
    'reconciliation_status',
  ]);

  requireCondition(
    item.reconciliation === undefined ||
    item.reconciliation === null ||
    isObject(item.reconciliation),
  );
}

function validateCalculation(value: unknown) {
  const item = record(value);
  requireCondition(
    nonemptyString(item.metric) &&
    decimalString(item.value) &&
    nonemptyString(item.unit) &&
    nonemptyString(item.formula) &&
    Array.isArray(item.inputs),
  );

  item.inputs.forEach(validateFact);

  requireCondition(
    item.ticker === undefined ||
    (typeof item.ticker === 'string' && TICKERS.has(item.ticker)),
  );
  requireCondition(
    item.fiscal_year === undefined ||
    (typeof item.fiscal_year === 'number' && FISCAL_YEARS.has(item.fiscal_year)),
  );
  requireCondition(
    item.years == null ||
    (nonnegativeInteger(item.years) && Number(item.years) > 0),
  );
  validateOptionalStrings(item, ['calculation_id']);
}

function validateEvidence(value: unknown) {
  const item = record(value);
  validateScope(item);
  requireCondition(
    nonemptyString(item.evidence_id) &&
    nonemptyString(item.text),
  );

  validateOptionalStrings(item, [
    'company',
    'filing_date',
    'period_start',
    'period_end',
    'accession_number',
    'source_url',
    'source',
    'section',
    'subsection',
    'location',
    'chunk_id',
    'fact_id',
  ]);

  for (const key of ['retrieval_score', 'reranker_score', 'reranker_logit']) {
    requireCondition(item[key] == null || finiteNumber(item[key]));
  }

  requireCondition(
    item.source_spans === undefined ||
    item.source_spans === null ||
    Array.isArray(item.source_spans),
  );
  requireCondition(
    item.reconciliation === undefined ||
    item.reconciliation === null ||
    isObject(item.reconciliation),
  );
}

function validateResearch(value: ObjectValue) {
  requireCondition(
    nonemptyString(value.request_id) &&
    stringValue(value.answer) &&
    typeof value.question_type === 'string' &&
    QUESTION_TYPES.has(value.question_type) &&
    typeof value.abstained === 'boolean' &&
    typeof value.grounded === 'boolean' &&
    typeof value.fallback_used === 'boolean' &&
    nonemptyString(value.grounding_status) &&
    finiteNumber(value.latency_ms) &&
    value.latency_ms >= 0 &&
    nullableString(value.provider) &&
    nullableString(value.model) &&
    nullableString(value.abstention_reason) &&
    isObject(value.trace) &&
    (value.fallback === null || isObject(value.fallback)),
  );

  requireCondition(!(value.abstained && value.grounded));

  requireCondition(Array.isArray(value.facts));
  requireCondition(Array.isArray(value.calculations));
  requireCondition(Array.isArray(value.evidence));
  requireCondition(Array.isArray(value.key_findings));
  requireCondition(strings(value.citation_ids));

  value.facts.forEach(validateFact);
  value.calculations.forEach(validateCalculation);
  value.evidence.forEach(validateEvidence);

  const evidenceIds = value.evidence.map(item => record(item).evidence_id as string);
  const allowed = new Set(evidenceIds);

  requireCondition(allowed.size === evidenceIds.length);
  requireCondition(value.citation_ids.every(id => allowed.has(id)));

  for (const finding of value.key_findings) {
    const item = record(finding);
    requireCondition(nonemptyString(item.text) && strings(item.citation_ids));
    requireCondition(item.citation_ids.length > 0);
    requireCondition(item.citation_ids.every(id => allowed.has(id)));
  }
}

function validateAnalytics(value: ObjectValue) {
  requireCondition(
    Array.isArray(value.rows) &&
    Array.isArray(value.issues) &&
    nullableString(value.corpus_version),
  );

  validateOptionalStrings(value, ['status', 'validation_scope']);

  const scopes = new Set<string>();

  for (const entry of value.rows) {
    const row = record(entry);
    validateScope(row);

    const scope = `${row.ticker}-${row.fiscal_year}`;
    requireCondition(!scopes.has(scope));
    scopes.add(scope);

    const values = record(row.values);
    requireCondition(Object.values(values).every(decimalString));

    requireCondition(Array.isArray(row.evidence));
    requireCondition(Array.isArray(row.calculations));
    row.evidence.forEach(validateFact);
    row.calculations.forEach(validateCalculation);

    if (row.unavailable_metrics !== undefined) {
      const unavailable = record(row.unavailable_metrics);
      requireCondition(Object.values(unavailable).every(stringValue));
    }
  }
}

function validateStatus(value: ObjectValue) {
  requireCondition(value.status_scope === 'local_readiness');

  for (const key of [
    'corpus_valid',
    'index_present',
    'configuration_compatible',
    'index_loaded',
    'index_artifacts_present',
    'index_ready',
    'retrieval_models_loaded',
    'financial_store_ready',
    'financial_coverage_complete',
    'rag_ready',
    'narrative_locally_ready_to_attempt',
    'primary_configuration_complete',
    'fallback_enabled',
  ]) {
    requireCondition(typeof value[key] === 'boolean');
  }

  for (const key of [
    'validated_report_count',
    'expected_report_count',
    'financial_fact_count',
    'financial_validated_fact_count',
  ]) {
    requireCondition(nonnegativeInteger(value[key]));
  }

  for (const key of [
    'provider',
    'model',
    'provider_authentication',
    'provider_reachability',
    'structured_output_capability',
  ]) {
    requireCondition(typeof value[key] === 'string');
  }

  requireCondition(nullableString(value.corpus_version));
  requireCondition(
    value.api_key_configured === null ||
    typeof value.api_key_configured === 'boolean',
  );

  validateOptionalStrings(value, [
    'corpus_error',
    'index_integrity',
    'index_error',
    'financial_store_error',
    'readiness_scope',
    'note',
  ]);

  for (const key of ['financial', 'manifest', 'last_ingestion']) {
    requireCondition(
      value[key] === undefined ||
      value[key] === null ||
      isObject(value[key]),
    );
  }
}

function validateEnvelope(path: string, value: unknown) {
  if (path === 'reports') {
    requireCondition(Array.isArray(value));

    for (const entry of value) {
      const report = record(entry);
      validateScope(report);

      requireCondition(
        nonemptyString(report.company) &&
        nonemptyString(report.filing_type) &&
        nonemptyString(report.status),
      );

      validateOptionalStrings(report, [
        'document_id',
        'accession_number',
        'filing_date',
        'period_end',
        'source_url',
        'content_sha256',
        'error_category',
      ]);

      requireCondition(
        report.block_count == null || nonnegativeInteger(report.block_count),
      );
    }
    return;
  }

  if (path === 'companies') {
    requireCondition(Array.isArray(value) && value.every(isObject));
    return;
  }

  const item = record(value);

  if (path === 'research' || path === 'compare') validateResearch(item);
  if (path === 'analytics') validateAnalytics(item);
  if (path === 'system/status') validateStatus(item);
  if (path.startsWith('evidence/')) validateEvidence(item);

  if (path === 'evaluation') {
    requireCondition(item.status === undefined || typeof item.status === 'string');
    requireCondition(item.metrics == null || isObject(item.metrics));
    requireCondition(item.records === undefined || Array.isArray(item.records));
  }
}

function apiBase(): string {
  const environment = (
    import.meta as ImportMeta & {
      env?: Record<string, string | boolean | undefined>;
    }
  ).env;

  const configured = environment?.VITE_API_BASE_URL;
  const base = typeof configured === 'string' && configured.trim()
    ? configured.trim()
    : '/api';

  if (base.startsWith('/') && !base.startsWith('//')) {
    if (
      base.includes('?') ||
      base.includes('#') ||
      base.includes('\\') ||
      base.split('/').some(part => part === '..' || part === '.')
    ) {
      throw new ApiError('The frontend API base configuration is invalid.');
    }

    return base.replace(/\/+$/, '');
  }

  try {
    const url = new URL(base);
    if (
      !['http:', 'https:'].includes(url.protocol) ||
      url.username ||
      url.password ||
      url.search ||
      url.hash
    ) {
      throw new Error('Unsupported API base');
    }
    return url.href.replace(/\/+$/, '');
  } catch {
    throw new ApiError(
      'The frontend API base must be a same-origin path or an explicit HTTP(S) URL.',
    );
  }
}

export async function api<T>(
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  if (!/^(?:health|companies|reports|research|compare|analytics|evaluation|system\/status|evidence\/[^/?#]+)$/.test(path)) {
    throw new ApiError('Unsupported application API route.');
  }

  const base = apiBase();
  const maxRetries = path === 'research' || path === 'compare' ? 4 : 1;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    const controller = new AbortController();
    let timedOut = false;
    const abort = () => controller.abort();

    if (signal?.aborted) controller.abort();
    signal?.addEventListener('abort', abort, {once: true});

    const timer = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, 150_000);

    try {
      const response = await fetch(`${base}/${path}`, {
        method: body === undefined ? 'GET' : 'POST',
        signal: controller.signal,
        credentials: 'omit',
        headers: body === undefined
          ? {Accept: 'application/json'}
          : {
              Accept: 'application/json',
              'Content-Type': 'application/json',
            },
        body: body === undefined ? undefined : JSON.stringify(body),
      });

      const requestId = response.headers.get('X-Request-ID') || undefined;
      let data: unknown;

      try {
        data = await response.json();
      } catch {
        throw new ApiError(
          'The service returned a non-JSON response.',
          response.status,
          requestId,
        );
      }

      if (!response.ok) {
        const detail = isObject(data) && typeof data.detail === 'string'
          ? data.detail
          : `Request failed (${response.status}).`;

        const apiError = new ApiError(
          detail,
          response.status,
          requestId,
          response.headers.get('Retry-After') || undefined,
        );

        if (response.status === 503 && attempt < maxRetries) {
          const retryAfterHeader = response.headers.get('Retry-After');
          let delayMs = 2000;
          if (retryAfterHeader) {
            const parsed = parseInt(retryAfterHeader, 10);
            if (Number.isFinite(parsed) && parsed > 0) {
              delayMs = Math.min(parsed * 1000, 8000);
            }
          }
          delayMs = Math.min(delayMs * Math.pow(1.5, attempt), 10000);

          await new Promise<void>((resolve, reject) => {
            const timeout = window.setTimeout(resolve, delayMs);
            const onAbort = () => {
              window.clearTimeout(timeout);
              reject(new DOMException('Request cancelled', 'AbortError'));
            };
            signal?.addEventListener('abort', onAbort, {once: true});
          }).catch((e) => {
            if (e instanceof DOMException && e.name === 'AbortError') throw e;
          });

          if (signal?.aborted) {
            throw new DOMException('Request cancelled', 'AbortError');
          }
          continue;
        }

        throw apiError;
      }

      try {
        validateEnvelope(path, data);

        if (
          (path === 'research' || path === 'compare') &&
          requestId &&
          record(data).request_id !== requestId
        ) {
          throw new Error('Request identifier mismatch');
        }
      } catch {
        throw new ApiError(
          'The service response does not match the supported data contract.',
          502,
          requestId,
        );
      }

      return data as T;
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        if (timedOut) {
          throw new ApiError(
            'The request timed out. Check service status before retrying; server work may still be running.',
          );
        }
        if (signal?.aborted) {
          throw error;
        }
      }

      if (error instanceof ApiError) {
        if (error.status === 503 && attempt < maxRetries && (path === 'research' || path === 'compare')) {
          const retryAfter = error.retryAfter ? parseInt(error.retryAfter, 10) : 2;
          let delayMs = Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter * 1000 : 2000;
          delayMs = Math.min(delayMs * Math.pow(1.5, attempt), 10000);
          await new Promise<void>((resolve) => window.setTimeout(resolve, delayMs));
          if (signal?.aborted) {
            throw new DOMException('Request cancelled', 'AbortError');
          }
          continue;
        }
        throw error;
      }

      if (attempt < maxRetries && (path === 'research' || path === 'compare')) {
        await new Promise<void>((resolve) => window.setTimeout(resolve, 1000 * (attempt + 1)));
        if (signal?.aborted) {
          throw new DOMException('Request cancelled', 'AbortError');
        }
        continue;
      }

      throw new ApiError(
        'Unable to reach the backend. Check the service connection and frontend API configuration.',
      );
    } finally {
      window.clearTimeout(timer);
      signal?.removeEventListener('abort', abort);
    }
  }

  throw new ApiError('Research service is busy. Please retry shortly.');
}