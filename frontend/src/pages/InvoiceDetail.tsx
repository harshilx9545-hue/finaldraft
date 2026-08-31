import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useMe } from '@/session/SessionProvider';
import { PageHeader, PageSections } from '@/components/layout/AppShell';
import { Card, CardBody, CardHeader, CardTitle, CardDescription } from '@/components/ui/Card';
import { ReadOnlyField } from '@/components/ui/Field';
import { Button } from '@/components/ui/Button';
import { Note } from '@/components/ui/Note';
import { InvoiceStatusChip } from '@/components/ui/StatusChip';
import { TextLink } from '@/components/ui/TextLink';
import { DisabledWithReason } from '@/components/ui/DisabledWithReason';
import { ErrorState, NotFoundState } from '@/components/data/States';
import { SkeletonFields } from '@/components/ui/Skeleton';
import { useToast } from '@/components/feedback/ToastProvider';
import { useInvoiceQuery, usePayInvoice } from '@/hooks/queries';
import { canPayInvoice } from '@/lib/permissions';
import { formatHsnSac, formatMinorUnits, formatMoney, formatTax } from '@/lib/money';
import { ApiError, mapFailure } from '@/lib/errors';
import type { PayOrder } from '@/api/types';

/**
 * One invoice, and the payment handoff.
 *
 * What this surface will NOT do: claim an invoice is paid. `POST
 * /api/invoices/{id}/pay` creates a gateway ORDER and returns a reference. The
 * status changes only when the gateway calls the backend's webhook. Presenting the
 * order as a settled payment would be a lie the user discovers later, so the note
 * says exactly what happened and offers a re-read instead.
 *
 * No card fields anywhere. The backend scans request bodies at every nesting depth
 * for card-data names and rejects them, and the pay body is an empty object.
 */
export default function InvoiceDetail(): JSX.Element {
  const me = useMe();
  const toast = useToast();
  const params = useParams<{ id: string }>();
  const parsed = Number.parseInt(params.id ?? '', 10);
  const id = Number.isFinite(parsed) ? parsed : null;

  const invoice = useInvoiceQuery(id);
  const pay = usePayInvoice(id ?? -1);
  const [order, setOrder] = useState<PayOrder | null>(null);
  const [payError, setPayError] = useState<string | null>(null);

  if (invoice.isError && invoice.error instanceof ApiError && invoice.error.status === 404) {
    return (
      <PageSections>
        <NotFoundState action={<TextLink to="/invoices">Back to invoices</TextLink>} />
      </PageSections>
    );
  }

  if (invoice.isPending) {
    return (
      <PageSections>
        <PageHeader title="Invoice" />
        <Card>
          <CardBody className="pt-5">
            <SkeletonFields fields={10} label="invoice" />
          </CardBody>
        </Card>
      </PageSections>
    );
  }

  if (invoice.isError) {
    return (
      <PageSections>
        <ErrorState error={invoice.error} onRetry={() => void invoice.refetch()} />
      </PageSections>
    );
  }

  const record = invoice.data;
  const gate = canPayInvoice(me, record);
  const subject =
    record.saas_subscription !== null
      ? 'Subscription invoice'
      : record.membership !== null
        ? 'Membership invoice'
        : 'Invoice';

  const onPay = async (): Promise<void> => {
    setPayError(null);
    try {
      const result = await pay.mutateAsync();
      if (!result.order_ref || !result.key_id) {
        setPayError('The payment could not be started. No gateway order was created.');
        return;
      }
      setOrder(result);
      toast.success('Payment order created.');
      // The gateway checkout would be opened here with key_id and order_ref. It is
      // not simulated: no fake success screen, no fake receipt.
    } catch (error) {
      setPayError(mapFailure(error).message);
    }
  };

  return (
    <PageSections>
      <PageHeader
        title={record.number}
        description={`${subject} · issued ${record.issue_date}`}
        actions={
          me.role === 'trainer' ? undefined : (
            <DisabledWithReason disabled={!gate.allowed} reason={gate.reason ?? ''}>
              <Button
                variant="primary"
                onClick={() => void onPay()}
                loading={pay.isPending}
                disabled={pay.isPending}
              >
                Pay this invoice
              </Button>
            </DisabledWithReason>
          )
        }
      />

      <Card>
        <CardHeader>
          <div className="flex flex-col gap-1">
            <CardTitle>Invoice</CardTitle>
            <CardDescription>
              {record.financial_year} · sequence {record.sequence_no}
            </CardDescription>
          </div>
          <InvoiceStatusChip status={record.status} />
        </CardHeader>
        <CardBody>
          <div className="grid gap-6 sm:grid-cols-2">
            <ReadOnlyField
              label="Taxable value"
              value={
                <span className="tabular">
                  {formatMoney(record.taxable_value, record.currency)}
                </span>
              }
            />
            <ReadOnlyField
              label="Total"
              value={
                <span className="tabular font-medium">
                  {formatMoney(record.total_amount, record.currency)}
                </span>
              }
            />
            <ReadOnlyField
              label="CGST"
              value={<span className="tabular">{formatTax(record.cgst, record.currency)}</span>}
            />
            <ReadOnlyField
              label="SGST"
              value={<span className="tabular">{formatTax(record.sgst, record.currency)}</span>}
            />
            <ReadOnlyField
              label="IGST"
              value={<span className="tabular">{formatTax(record.igst, record.currency)}</span>}
            />
            <ReadOnlyField label="HSN / SAC" value={formatHsnSac(record.hsn_sac)} />
            <ReadOnlyField label="Currency" value={record.currency} />
            <ReadOnlyField
              label="Due"
              value={<span className="tabular">{record.due_date}</span>}
            />
          </div>

          {record.cgst === null && record.sgst === null && record.igst === null ? (
            <Note className="mt-6">
              Tax is not applicable on this invoice: the issuing gym had no GSTIN when it was
              issued. That is different from a tax of zero.
            </Note>
          ) : null}
        </CardBody>
      </Card>

      {payError !== null ? (
        <Note tone="warning">{payError}</Note>
      ) : null}

      {order !== null ? (
        <Card>
          <CardHeader>
            <div className="flex flex-col gap-1">
              <CardTitle>Payment order created</CardTitle>
              <CardDescription>
                This is a gateway order, not a payment. Nothing has been charged yet.
              </CardDescription>
            </div>
          </CardHeader>
          <CardBody>
            <div className="grid gap-6 sm:grid-cols-2">
              <ReadOnlyField label="Order reference" value={order.order_ref} />
              <ReadOnlyField label="Currency" value={order.currency} />
              <ReadOnlyField
                label="Payable"
                value={
                  <span className="tabular">{formatMoney(record.total_amount, record.currency)}</span>
                }
              />
              <ReadOnlyField
                label="Gateway amount"
                value={formatMinorUnits(order.amount_minor, order.currency)}
                hint="Minor units, as the gateway requires. Not a display amount."
              />
            </div>

            <Note className="mt-6" tone="warning">
              This invoice stays <strong>{record.status}</strong> until the payment gateway notifies
              the backend through its webhook. Nothing on this screen can settle it.
            </Note>

            <div className="mt-4">
              <Button variant="secondary" onClick={() => void invoice.refetch()}>
                Check the invoice again
              </Button>
            </div>
          </CardBody>
        </Card>
      ) : null}

      <Note>
        No receipt is available. The pay response carries no payment identifier and no route lists
        payments, so the receipt endpoint cannot be reached.
      </Note>

      <TextLink to="/invoices">Back to invoices</TextLink>
    </PageSections>
  );
}
