import { useMemo } from 'react';
import { useReducedMotion } from 'framer-motion';
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { Invoice, InvoiceStatus } from '@/api/types';
import { formatMoney } from '@/lib/money';
import { buildPoints, groupByStatus, SERIES_ORDER } from './invoiceGeometry';

/**
 * Invoice amount against issue date, one line per status. Owner only.
 *
 * This is the single chart in the product, and it is here because it is the only
 * one with real data behind it: the invoice collection carries an amount and a date
 * per record. There is no members-over-time, revenue-growth or attendance series
 * anywhere in the API, so no such chart exists.
 *
 * It renders only once every page has been fetched. A chart drawn from page 1 of 4
 * looks authoritative and is wrong, which is worse than a spinner.
 *
 * Every number a viewer reads comes from formatMoney on the original decimal
 * string. The numeric values inside the chart are plotting coordinates from
 * invoiceGeometry and are never displayed.
 */

/** Series colours from the Genesis palette, via CSS custom properties. */
const SERIES_COLOR: Record<InvoiceStatus, string> = {
  open: 'var(--color-warning)',
  settled: 'var(--color-success)',
  void: 'var(--color-error)',
  refunded: 'var(--color-neutral)',
};

const SERIES_LABEL: Record<InvoiceStatus, string> = {
  open: 'Open',
  settled: 'Settled',
  void: 'Void',
  refunded: 'Refunded',
};

function formatDateTick(value: number): string {
  const date = new Date(value);
  return date.toISOString().slice(0, 10);
}

export function InvoiceChart({ invoices }: { invoices: readonly Invoice[] }): JSX.Element {
  const reduced = useReducedMotion() ?? false;
  const grouped = useMemo(() => groupByStatus(buildPoints(invoices)), [invoices]);

  const present = SERIES_ORDER.filter((status) => (grouped.get(status)?.length ?? 0) > 0);

  return (
    <div className="h-[320px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
          <CartesianGrid stroke="var(--color-border)" strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="x"
            type="number"
            domain={['dataMin', 'dataMax']}
            scale="time"
            tickFormatter={formatDateTick}
            tick={{ fill: 'var(--color-text-secondary)', fontSize: 12 }}
            stroke="var(--color-border)"
          />
          <YAxis
            dataKey="y"
            type="number"
            // Tick labels are produced from the ORIGINAL string via formatMoney
            // wherever an exact figure matters; the axis shows magnitude only.
            tick={{ fill: 'var(--color-text-secondary)', fontSize: 12 }}
            stroke="var(--color-border)"
            width={72}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              borderRadius: 8,
              fontSize: 13,
            }}
            labelFormatter={(value) => formatDateTick(Number(value))}
            formatter={(_value, _name, item) => {
              // Read the invoice off the datum and format its ORIGINAL string.
              const point = item?.payload as { invoice?: Invoice } | undefined;
              const invoice = point?.invoice;
              if (invoice === undefined) return ['', ''];
              return [formatMoney(invoice.total_amount, invoice.currency), invoice.number];
            }}
          />
          <Legend
            formatter={(value) => (
              <span style={{ color: 'var(--color-text-secondary)', fontSize: 13 }}>{value}</span>
            )}
          />
          {present.map((status) => (
            <Line
              key={status}
              name={SERIES_LABEL[status]}
              data={grouped.get(status) ?? []}
              dataKey="y"
              type="monotone"
              stroke={SERIES_COLOR[status]}
              strokeWidth={2}
              dot={{ r: 3 }}
              activeDot={{ r: 5 }}
              isAnimationActive={!reduced}
              animationDuration={reduced ? 0 : 600}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/**
 * The same figures as a table, adjacent to the chart, so the data is available
 * without reading the graphic.
 */
export function InvoiceChartTable({ invoices }: { invoices: readonly Invoice[] }): JSX.Element {
  return (
    <div className="overflow-hidden rounded-panel border border-border">
      <table>
        <caption className="sr-only">
          Invoice amounts by issue date, the figures behind the chart above.
        </caption>
        <thead>
          <tr className="border-b border-border">
            {['Number', 'Issued', 'Status', 'Currency', 'Total'].map((header, index) => (
              <th
                key={header}
                scope="col"
                className={`px-4 py-3 text-caption font-medium uppercase tracking-[0.08em] text-muted ${
                  index === 4 ? 'text-right' : 'text-left'
                }`}
              >
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {invoices.map((invoice) => (
            <tr key={invoice.id} className="border-b border-border last:border-b-0">
              <td className="px-4 py-3 text-control text-ink break-value">{invoice.number}</td>
              <td className="px-4 py-3 text-control text-ink tabular">{invoice.issue_date}</td>
              <td className="px-4 py-3 text-control text-ink">{invoice.status}</td>
              <td className="px-4 py-3 text-control text-ink">{invoice.currency}</td>
              <td className="px-4 py-3 text-right text-control text-ink tabular">
                {formatMoney(invoice.total_amount, invoice.currency)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
