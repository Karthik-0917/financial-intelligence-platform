import {memo, useEffect, useId, useMemo, useState} from 'react';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
} from 'recharts';
import type {Analytics, Ticker} from './api';
import {
  COMPANIES,
  YEARS,
  Empty,
  formatValue,
  label,
  numeric,
} from './ui';

const SERIES: Record<Ticker, {color: string; dash?: string}> = {
  AAPL: {color: 'var(--fi-company-aapl)'},
  MSFT: {color: 'var(--fi-company-msft)', dash: '7 3'},
  AMZN: {color: 'var(--fi-company-amzn)', dash: '2 3'},
};

/* Animate chart geometry only. Labels and the exact-value table always use
 * the current real observations; motion never writes intermediate data. */
function useChartMotion() {
  const [reduced, setReduced] = useState(() =>
    window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  );
  const [duration] = useState(() => {
    const value = Number.parseFloat(getComputedStyle(document.documentElement)
      .getPropertyValue('--fi-motion-chart'));
    return Number.isFinite(value) ? value : 420;
  });

  useEffect(() => {
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setReduced(preference.matches);
    update();
    preference.addEventListener('change', update);
    return () => preference.removeEventListener('change', update);
  }, []);

  return {
    isAnimationActive: !reduced,
    animationBegin: 0,
    animationDuration: duration,
    animationEasing: 'ease-in-out' as const,
  };
}

function FinancialChart({
  analytics,
  metric,
  companies,
  kind = 'line',
  years = YEARS,
}: {
  analytics: Analytics;
  metric: string;
  companies: Ticker[];
  kind?: 'line' | 'bar';
  years?: number[];
}) {
  const captionId = useId();
  const chartMotion = useChartMotion();

  const selectedCompanies = useMemo(
    () => COMPANIES.filter(company => companies.includes(company.ticker)),
    [companies],
  );

  const selectedYears = useMemo(
    () => [...new Set(years)]
      .filter(year => YEARS.includes(year))
      .sort((left, right) => left - right),
    [years],
  );

  const data = useMemo(
    () => selectedYears.map(year => ({
      year: `FY${year}`,
      ...Object.fromEntries(selectedCompanies.map(company => {
        const row = analytics.rows.find(item =>
          item.ticker === company.ticker && item.fiscal_year === year,
        );
        return [company.ticker, numeric(row?.values[metric])];
      })),
    })),
    [analytics.rows, metric, selectedCompanies, selectedYears],
  );

  const coordinates = data.flatMap(row =>
    selectedCompanies.map(company =>
      (row as Record<string, unknown>)[company.ticker],
    ).filter((value): value is number =>
      typeof value === 'number' && Number.isFinite(value),
    ),
  );

  const expectedObservations = selectedYears.length * selectedCompanies.length;
  const missingObservations = expectedObservations - coordinates.length;
  const hasNegative = coordinates.some(value => value < 0);
  const hasPositive = coordinates.some(value => value > 0);
  const zeroOnly = coordinates.length > 0 &&
    coordinates.every(value => value === 0);

  /*
   * Financial scales include zero.
   * [0, 1] is a display range for an all-zero dataset, not an observation.
   */
  const domain: [number | 'auto', number | 'auto'] = zeroOnly
    ? [0, 1]
    : hasNegative
      ? hasPositive ? ['auto', 'auto'] : ['auto', 0]
      : [0, 'auto'];

  if (!coordinates.length) {
    return <Empty title={`No chartable ${label(metric).toLowerCase()} values`}>
      No available observations were returned for the selected companies
      and fiscal periods. Missing values are not estimated or plotted as zero.
    </Empty>;
  }

  const shared = <>
    <CartesianGrid stroke="var(--fi-border-subtle)" vertical={false}/>
    <XAxis
      dataKey="year"
      tick={{fontSize: 12, fill: 'var(--fi-text-secondary)'}}
      axisLine={false}
      tickLine={false}
      tickMargin={11}
      padding={kind === 'line' ? {left: 12, right: 12} : undefined}
    />
    <YAxis
      width={91}
      domain={domain}
      tick={{fontSize: 12, fill: 'var(--fi-text-secondary)'}}
      axisLine={false}
      tickLine={false}
      tickCount={5}
      tickFormatter={value => formatValue(String(value), metric)}
    />
    {hasNegative && <ReferenceLine y={0} stroke="var(--fi-border-strong)"/>}
    <Tooltip
      isAnimationActive={false}
      cursor={kind === 'bar'
        ? {fill: 'var(--fi-accent-tint)', fillOpacity: 0.65}
        : {stroke: 'var(--fi-border-strong)', strokeDasharray: '3 3'}}
      contentStyle={{
        border: '1px solid var(--fi-border)',
        borderRadius: 'var(--fi-radius-control)',
        background: 'var(--fi-surface)',
        color: 'var(--fi-text-primary)',
        fontSize: 13,
        boxShadow: 'none',
        padding: '12px 15px',
      }}
      labelStyle={{
        fontWeight: 650,
        marginBottom: 8,
        color: 'var(--fi-text-primary)',
      }}
      formatter={value => formatValue(
        typeof value === 'number' || typeof value === 'string'
          ? String(value)
          : undefined,
        metric,
      )}
    />
  </>;

  return <figure className="financial-chart">
    <div
      role="list"
      aria-label="Chart series"
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        gap: '12px 23px',
        marginBottom: 18,
      }}
    >
      {selectedCompanies.map(company => {
        const count = data.filter(row =>
          typeof (row as Record<string, unknown>)[company.ticker] === 'number',
        ).length;
        const appearance = SERIES[company.ticker];

        return <span
          role="listitem"
          key={company.ticker}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 8,
            color: 'var(--fi-text-secondary)',
            fontSize: 12,
            fontWeight: 550,
          }}
        >
          <svg width="25" height="12" aria-hidden="true">
            <line
              x1="1"
              x2="24"
              y1="6"
              y2="6"
              stroke={appearance.color}
              strokeWidth="3"
              strokeDasharray={kind === 'line' ? appearance.dash : undefined}
            />
          </svg>
          {company.name}
          {count === 0 && <span style={{color: 'var(--fi-warning)', fontWeight: 400}}>· unavailable</span>}
        </span>;
      })}
    </div>

    <div
      className="chart-frame"
      role="group"
      aria-label={`${label(metric)} by company and fiscal year`}
      aria-describedby={captionId}
    >
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        {kind === 'bar'
          ? <BarChart
              data={data}
              margin={{top: 12, right: 18, bottom: 8, left: 0}}
              accessibilityLayer
              barGap={8}
            >
              {shared}
              {selectedCompanies.map(company => <Bar
                key={company.ticker}
                dataKey={company.ticker}
                name={company.name}
                fill={SERIES[company.ticker].color}
                maxBarSize={48}
                {...chartMotion}
              />)}
            </BarChart>
          : <LineChart
              data={data}
              margin={{top: 12, right: 18, bottom: 8, left: 0}}
              accessibilityLayer
            >
              {shared}
              {selectedCompanies.map(company => <Line
                key={company.ticker}
                dataKey={company.ticker}
                name={company.name}
                stroke={SERIES[company.ticker].color}
                strokeDasharray={SERIES[company.ticker].dash}
                strokeWidth={2.7}
                dot={{r: 4, strokeWidth: 2, fill: 'var(--fi-surface)'}}
                activeDot={{r: 6, strokeWidth: 2, stroke: 'var(--fi-surface)'}}
                connectNulls={false}
                {...chartMotion}
              />)}
            </LineChart>}
      </ResponsiveContainer>
    </div>

    <figcaption id={captionId} className="footnote">
      {label(metric)} · {selectedYears.map(year => `FY${year}`).join(', ')}.
      {missingObservations > 0 &&
        ` ${missingObservations} of ${expectedObservations} selected observations unavailable; no zero substitution.`}
      {' '}Chart coordinates use browser numeric precision.
    </figcaption>

    <details className="chart-data-details">
      <summary>Exact chart values and availability</summary>
      <p className="mf-fineprint">
        These persisted decimal strings are authoritative over rounded
        tooltips and visual coordinates.
      </p>
      <div className="table-wrap" tabIndex={0} aria-label="Exact chart values">
        <table className="mf-table">
          <caption className="sr-only">
            Exact persisted values underlying the {label(metric).toLowerCase()} chart
          </caption>
          <thead>
            <tr>
              <th scope="col">Fiscal year</th>
              {selectedCompanies.map(company => <th
                key={company.ticker}
                scope="col"
                className="number"
              >{company.name}</th>)}
            </tr>
          </thead>
          <tbody>
            {selectedYears.map(year => <tr key={year}>
              <th scope="row">FY{year}</th>
              {selectedCompanies.map(company => {
                const row = analytics.rows.find(item =>
                  item.ticker === company.ticker && item.fiscal_year === year,
                );
                const value = row?.values[metric];
                return <td key={company.ticker} className="number">
                  {numeric(value) === null
                    ? <>
                        <span>Unavailable</span>
                        <small>{row?.unavailable_metrics?.[metric] || 'No validated value returned.'}</small>
                      </>
                    : <code>{value}</code>}
                </td>;
              })}
            </tr>)}
          </tbody>
        </table>
      </div>
    </details>
  </figure>;
}

/* Parent inputs may recreate the same company array while the user types.
 * Do not restart chart animation unless a chart input actually changes. */
export default memo(FinancialChart, (previous, next) =>
  previous.analytics === next.analytics &&
  previous.metric === next.metric &&
  previous.kind === next.kind &&
  previous.years === next.years &&
  previous.companies.join(',') === next.companies.join(','),
);