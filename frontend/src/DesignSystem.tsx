import {useId, type ReactNode} from 'react';
import {
  ArrowDownRight,
  ArrowUpRight,
  ChevronLeft,
  ChevronRight,
  Minus,
} from 'lucide-react';
import './midnight.css';

export type MetricTone = 'blue' | 'teal' | 'amber' | 'red' | 'neutral';

export function SectionHeading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return <header className="mf-section-heading">
    <div>
      {eyebrow && <span className="mf-eyebrow">{eyebrow}</span>}
      <h2>{title}</h2>
      {description && <p>{description}</p>}
    </div>
    {action && <div className="mf-section-action">{action}</div>}
  </header>;
}

export function MetricSummary({
  title,
  value,
  detail,
  tone = 'blue',
  measured = true,
}: {
  title: string;
  value: string;
  detail: string;
  tone?: MetricTone;
  measured?: boolean;
}) {
  return <article className={`mf-metric mf-tone-${tone} ${measured ? '' : 'mf-unmeasured'}`}>
    <span className="mf-metric-label">{title}</span>
    <strong className="mf-metric-value">{value}</strong>
    <span className="mf-metric-detail">{detail}</span>
  </article>;
}

export function MetricStatus({
  children,
  tone = 'neutral',
}: {
  children: ReactNode;
  tone?: MetricTone;
}) {
  return <span className={`mf-status mf-tone-${tone}`}>
    <span aria-hidden="true" className="mf-status-marker"/>
    {children}
  </span>;
}

export function Disclosure({
  title,
  children,
  initiallyOpen = false,
}: {
  title: string;
  children: ReactNode;
  initiallyOpen?: boolean;
}) {
  return <details className="mf-disclosure" open={initiallyOpen || undefined}>
    <summary>{title}</summary>
    <div className="mf-disclosure-content">{children}</div>
  </details>;
}

export function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
  label = 'records',
}: {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
  label?: string;
}) {
  const id = useId();
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const safePage = Math.min(Math.max(1, page), pages);
  const first = total === 0 ? 0 : (safePage - 1) * pageSize + 1;
  const last = Math.min(safePage * pageSize, total);

  return <nav className="mf-pagination" aria-label={`${label} pagination`}>
    <span role="status" aria-live="polite">
      {first}–{last} of {total} {label}
    </span>
    <div className="mf-pagination-controls">
      <label htmlFor={id}>Rows</label>
      <select
        id={id}
        value={pageSize}
        onChange={event => onPageSizeChange(Number(event.target.value))}
      >
        {[10, 20, 50].map(size => <option key={size} value={size}>{size}</option>)}
      </select>
      <button
        type="button"
        className="mf-icon-button"
        disabled={safePage === 1}
        onClick={() => onPageChange(safePage - 1)}
        aria-label="Previous page"
      ><ChevronLeft size={17} aria-hidden="true"/></button>
      <span className="mf-page-position">{safePage} / {pages}</span>
      <button
        type="button"
        className="mf-icon-button"
        disabled={safePage === pages}
        onClick={() => onPageChange(safePage + 1)}
        aria-label="Next page"
      ><ChevronRight size={17} aria-hidden="true"/></button>
    </div>
  </nav>;
}

export function MeasurementBar({
  label,
  value,
  display,
  detail,
  lowerIsBetter = false,
  tone = 'blue',
}: {
  label: string;
  value: number | null;
  display: string;
  detail: string;
  lowerIsBetter?: boolean;
  tone?: MetricTone;
}) {
  const valid = value !== null &&
    Number.isFinite(value) &&
    value >= 0 &&
    value <= 1;

  return <div className={`mf-measurement mf-tone-${tone}`}>
    <div className="mf-measurement-heading">
      <span>{label}</span>
      <strong>{display}</strong>
    </div>
    {valid
      ? <div
          className="mf-meter"
          role="meter"
          aria-label={label}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={value * 100}
          aria-valuetext={`${display}; ${lowerIsBetter ? 'lower is preferable' : 'higher is preferable'}`}
        >
          <span style={{width: `${value * 100}%`}}/>
        </div>
      : <div className="mf-meter mf-meter-unmeasured" aria-hidden="true"/>}
    <p>
      {valid
        ? lowerIsBetter
          ? <ArrowDownRight size={13} aria-hidden="true"/>
          : <ArrowUpRight size={13} aria-hidden="true"/>
        : <Minus size={13} aria-hidden="true"/>}
      {detail}
    </p>
  </div>;
}