import type { Invoice, InvoiceStatus } from '@/api/types';

/**
 * The ONLY module in the codebase permitted to turn a backend money string into a
 * JavaScript number.
 *
 * A chart needs numeric coordinates; there is no way around that. So the conversion
 * is quarantined here, and the rule is: the number produced may be used as a
 * PLOTTING COORDINATE and nothing else. It is never rendered as text, never summed,
 * never averaged, and never compared to another amount for display. Every figure a
 * user actually reads — axis labels, tooltips, the adjacent table — is produced by
 * the Money_Formatter from the original unmodified string.
 *
 * Keeping this in one small file means the boundary is checkable by eye and by test,
 * rather than being a convention people remember most of the time.
 */

export interface InvoicePoint {
  /** Kept for labelling. This is what gets rendered. */
  invoice: Invoice;
  /** Plotting coordinate only. Never rendered. */
  y: number;
  /** Plotting coordinate only (epoch ms of `issue_date`). Never rendered. */
  x: number;
  status: InvoiceStatus;
}

/** Plotting coordinate only. See the module note. */
function toPlottingValue(decimalString: string): number {
  const parsed = Number.parseFloat(decimalString);
  return Number.isFinite(parsed) ? parsed : 0;
}

/**
 * `issue_date` is a calendar date in the gym's timezone. Parsing it as UTC noon
 * keeps every point on the right day regardless of the viewer's offset, which a
 * midnight parse would not.
 */
function toPlottingDate(isoDate: string): number {
  const parsed = Date.parse(`${isoDate}T12:00:00Z`);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function buildPoints(invoices: readonly Invoice[]): InvoicePoint[] {
  return invoices.map((invoice) => ({
    invoice,
    x: toPlottingDate(invoice.issue_date),
    y: toPlottingValue(invoice.total_amount),
    status: invoice.status,
  }));
}

export const SERIES_ORDER: readonly InvoiceStatus[] = [
  'open',
  'settled',
  'void',
  'refunded',
] as const;

export function groupByStatus(points: readonly InvoicePoint[]): Map<InvoiceStatus, InvoicePoint[]> {
  const grouped = new Map<InvoiceStatus, InvoicePoint[]>();
  for (const status of SERIES_ORDER) grouped.set(status, []);
  for (const point of points) {
    const bucket = grouped.get(point.status);
    if (bucket !== undefined) bucket.push(point);
  }
  // Chronological within each series so a line reads left to right.
  for (const bucket of grouped.values()) bucket.sort((a, b) => a.x - b.x);
  return grouped;
}
