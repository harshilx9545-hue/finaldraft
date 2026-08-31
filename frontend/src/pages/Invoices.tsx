import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useMe } from '@/session/SessionProvider';
import { PageHeader, PageSections } from '@/components/layout/AppShell';
import { DataList, type Column } from '@/components/data/DataList';
import { EmptyState, ErrorState } from '@/components/data/States';
import { SkeletonTable } from '@/components/ui/Skeleton';
import { Card, CardBody, CardHeader, CardTitle, CardDescription } from '@/components/ui/Card';
import { Note } from '@/components/ui/Note';
import { InvoiceStatusChip } from '@/components/ui/StatusChip';
import { Button } from '@/components/ui/Button';
import { useInvoicesQuery, keys } from '@/hooks/queries';
import { fetchAllPages, listInvoices } from '@/api/resources';
import { formatMoney } from '@/lib/money';
import { InvoiceChart, InvoiceChartTable } from '@/charts/InvoiceChart';
import type { Invoice } from '@/api/types';

/**
 * Invoices.
 *
 * Scoping is the backend's, not a filter: an owner receives the whole gym's
 * invoices, everyone else only invoices where they are the payer. There is no
 * status, date or payer parameter to send.
 *
 * Worth knowing: reading this list calls `ensure_period_invoice` server-side, which
 * can ISSUE the upcoming subscription invoice. So nothing here polls, refetches on
 * focus, or reloads on reconnect.
 */
export default function Invoices(): JSX.Element {
  const me = useMe();
  const [page, setPage] = useState(1);
  const invoices = useInvoicesQuery(page);
  const isOwner = me.role === 'owner';

  const hasRows = (invoices.data?.count ?? 0) > 0;

  // The chart needs every page — a partial series would misrepresent the data.
  // Owner only, once per mount, never automatically refetched.
  const allInvoices = useQuery({
    queryKey: keys.invoicesEvery,
    queryFn: () => fetchAllPages(listInvoices),
    enabled: isOwner && hasRows,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    refetchInterval: false,
    staleTime: Infinity,
  });

  const columns: readonly Column<Invoice>[] = useMemo(
    () => [
      {
        key: 'number',
        header: 'Number',
        render: (row) => (
          <div className="flex flex-col gap-1">
            <span className="font-medium text-ink break-value">{row.number}</span>
            <span className="text-caption text-muted">
              {row.saas_subscription !== null
                ? 'Subscription invoice'
                : row.membership !== null
                  ? 'Membership invoice'
                  : 'Invoice'}
            </span>
          </div>
        ),
      },
      {
        key: 'issue_date',
        header: 'Issued',
        render: (row) => <span className="tabular">{row.issue_date}</span>,
      },
      {
        key: 'due_date',
        header: 'Due',
        render: (row) => <span className="tabular">{row.due_date}</span>,
      },
      {
        key: 'total_amount',
        header: 'Total',
        align: 'end',
        render: (row) => (
          <span className="tabular font-medium">{formatMoney(row.total_amount, row.currency)}</span>
        ),
      },
      {
        key: 'status',
        header: 'Status',
        render: (row) => <InvoiceStatusChip status={row.status} />,
      },
    ],
    [],
  );

  return (
    <PageSections>
      <PageHeader
        title="Invoices"
        description={
          isOwner
            ? 'Every invoice issued to this gym.'
            : 'Invoices payable by you.'
        }
      />

      {isOwner ? (
        <Note>
          Opening this page reads the invoice list, which can cause the backend to issue the
          upcoming subscription invoice. That is the API's behaviour on read, not an action taken
          here.
        </Note>
      ) : null}

      {invoices.isPending ? (
        <SkeletonTable rows={25} columns={5} label="invoices" />
      ) : invoices.isError ? (
        <ErrorState error={invoices.error} onRetry={() => void invoices.refetch()} />
      ) : invoices.data.count === 0 ? (
        <EmptyState
          title="No invoices yet"
          description="Invoices are issued by the backend when a billing period opens. There is no way to create one from here."
        />
      ) : (
        <DataList
          caption="Invoices"
          orderedBy="most recent issue date"
          columns={columns}
          rows={invoices.data.results}
          rowKey={(row) => row.id}
          count={invoices.data.count}
          page={page}
          hasNext={invoices.data.next !== null}
          hasPrevious={invoices.data.previous !== null}
          onPageChange={setPage}
          rowHref={(row) => `/invoices/${row.id}`}
          isFetching={invoices.isFetching}
        />
      )}

      {isOwner && hasRows ? (
        <Card>
          <CardHeader>
            <div className="flex flex-col gap-1">
              <CardTitle>Invoice amounts by issue date</CardTitle>
              <CardDescription>
                One line per status, built from every invoice the API returns.
              </CardDescription>
            </div>
          </CardHeader>
          <CardBody>
            {allInvoices.isPending ? (
              <div role="status" aria-live="polite" className="py-12 text-center">
                <p className="text-small text-muted">
                  Fetching every invoice page before drawing the chart. A partial chart would
                  misstate the data, so nothing is drawn until all pages are in.
                </p>
              </div>
            ) : allInvoices.isError ? (
              <ErrorState
                error={allInvoices.error}
                onRetry={() => void allInvoices.refetch()}
                title="The chart data did not load"
              />
            ) : (
              <div className="flex flex-col gap-6">
                {allInvoices.data.truncated ? (
                  <Note tone="warning">
                    This gym has more than the 1,000 invoices this page retrieves, so the chart is
                    not drawn. Paging above still shows every record.
                  </Note>
                ) : (
                  <>
                    <InvoiceChart invoices={allInvoices.data.items} />
                    <details>
                      <summary className="cursor-pointer text-control font-medium text-primary">
                        Show the figures as a table
                      </summary>
                      <div className="mt-4">
                        <InvoiceChartTable invoices={allInvoices.data.items} />
                      </div>
                    </details>
                  </>
                )}
              </div>
            )}
          </CardBody>
        </Card>
      ) : null}

      <Note>
        There is no receipt document. The API returns no payment identifier and lists no payments,
        so the receipt endpoint cannot be reached from any screen.
      </Note>

      {invoices.isError ? null : (
        <div>
          <Button variant="secondary" onClick={() => void invoices.refetch()}>
            Refresh invoices
          </Button>
        </div>
      )}
    </PageSections>
  );
}
