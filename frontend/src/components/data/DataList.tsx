import { Link } from 'react-router-dom';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { cn } from '@/lib/cn';

/**
 * A paginated backend collection.
 *
 * Two things this component deliberately does NOT have:
 *
 * - No search box, no filter control, no sortable header. The backend registers no
 *   filter backend and no view reads query_params, so any of those would either do
 *   nothing or filter one page client-side and present the result as if the server
 *   had produced it. The absence is stated on screen rather than left to be
 *   discovered.
 * - No page-number jumping. Paging is driven by the `next` and `previous` fields the
 *   response supplies, because a computed page count can disagree with the server.
 *
 * At 768px and up it renders a real <table> with a caption and column headers. Below
 * that it becomes a stacked list, one group per record with each value beside its
 * label, rather than a table in a horizontal scroller.
 */

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => React.ReactNode;
  /** Right-align numeric columns. */
  align?: 'start' | 'end';
  /** Hide on the mobile stacked layout when a value is already in the title. */
  hideOnMobile?: boolean;
}

export interface DataListProps<T> {
  /** Names the collection. Becomes the table caption and the mobile list label. */
  caption: string;
  columns: readonly Column<T>[];
  rows: readonly T[];
  rowKey: (row: T) => string | number;
  /** Total from the response `count`, not the length of `results`. */
  count: number;
  page: number;
  hasNext: boolean;
  hasPrevious: boolean;
  onPageChange: (page: number) => void;
  /** Where a row navigates, when a detail route exists for it. */
  rowHref?: (row: T) => string | undefined;
  /** The server's fixed ordering, stated so it does not look arbitrary. */
  orderedBy: string;
  isFetching?: boolean;
}

export function DataList<T>({
  caption,
  columns,
  rows,
  rowKey,
  count,
  page,
  hasNext,
  hasPrevious,
  onPageChange,
  rowHref,
  orderedBy,
  isFetching = false,
}: DataListProps<T>): JSX.Element {
  return (
    <div className={cn('flex flex-col gap-4', isFetching && 'opacity-70')}>
      {/* Desktop: a real table. */}
      <div className="hidden overflow-hidden rounded-card border border-border bg-surface md:block">
        <table>
          <caption className="sr-only">
            {caption}. Ordered by {orderedBy}. Search and filtering are not available.
          </caption>
          <thead>
            <tr className="border-b border-border">
              {columns.map((column) => (
                <th
                  key={column.key}
                  scope="col"
                  className={cn(
                    'px-4 py-3 text-caption font-medium uppercase tracking-[0.08em] text-muted',
                    column.align === 'end' ? 'text-right' : 'text-left',
                  )}
                >
                  {column.header}
                </th>
              ))}
              {rowHref ? <th scope="col" className="w-10 px-4 py-3" /> : null}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const href = rowHref?.(row);
              return (
                <tr
                  key={rowKey(row)}
                  className="border-b border-border last:border-b-0 transition-colors duration-base ease-standard hover:bg-background"
                >
                  {columns.map((column) => (
                    <td
                      key={column.key}
                      className={cn(
                        'px-4 py-4 text-control text-ink align-top',
                        column.align === 'end' ? 'text-right' : 'text-left',
                      )}
                    >
                      {column.render(row)}
                    </td>
                  ))}
                  {rowHref ? (
                    <td className="px-4 py-4 text-right align-top">
                      {href ? (
                        <Link
                          to={href}
                          className="inline-flex items-center gap-1 text-control font-medium text-primary no-underline hover:underline focus-visible:underline"
                        >
                          <span>Open</span>
                          <ChevronRight aria-hidden="true" className="h-3.5 w-3.5" />
                        </Link>
                      ) : null}
                    </td>
                  ) : null}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Mobile: stacked records, each value beside its label. */}
      <ul aria-label={caption} className="flex list-none flex-col gap-4 p-0 md:hidden">
        {rows.map((row) => {
          const href = rowHref?.(row);
          return (
            <li key={rowKey(row)} className="rounded-card border border-border bg-surface p-4">
              <dl className="m-0 flex flex-col gap-3">
                {columns
                  .filter((column) => column.hideOnMobile !== true)
                  .map((column) => (
                    <div key={column.key} className="flex flex-wrap items-baseline gap-2">
                      <dt className="min-w-[8rem] text-caption font-medium uppercase tracking-[0.08em] text-muted">
                        {column.header}
                      </dt>
                      <dd className="m-0 flex-1 text-control text-ink break-value">
                        {column.render(row)}
                      </dd>
                    </div>
                  ))}
              </dl>
              {href ? (
                <Link
                  to={href}
                  className="mt-4 inline-flex min-h-11 items-center gap-1 text-control font-medium text-primary no-underline hover:underline focus-visible:underline"
                >
                  <span>Open</span>
                  <ChevronRight aria-hidden="true" className="h-3.5 w-3.5" />
                </Link>
              ) : null}
            </li>
          );
        })}
      </ul>

      <div className="flex flex-wrap items-center justify-between gap-4">
        <p className="text-caption text-muted">
          <span className="tabular">{count}</span> total,{' '}
          <span className="tabular">{rows.length}</span> on this page. Ordered by {orderedBy} on the
          server. Search and filtering are not available.
        </p>

        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => onPageChange(page - 1)}
            disabled={!hasPrevious}
            aria-label="Previous page"
          >
            <ChevronLeft aria-hidden="true" className="h-4 w-4" />
            <span>Previous</span>
          </Button>
          <span className="text-caption text-muted tabular">Page {page}</span>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => onPageChange(page + 1)}
            disabled={!hasNext}
            aria-label="Next page"
          >
            <span>Next</span>
            <ChevronRight aria-hidden="true" className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}
