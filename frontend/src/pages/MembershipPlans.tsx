import { useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Plus } from 'lucide-react';
import { useMe } from '@/session/SessionProvider';
import { PageHeader, PageSections } from '@/components/layout/AppShell';
import { DataList, type Column } from '@/components/data/DataList';
import { EmptyState, ErrorState } from '@/components/data/States';
import { SkeletonTable } from '@/components/ui/Skeleton';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { CheckField, SelectField, TextField } from '@/components/ui/Field';
import { Chip } from '@/components/ui/StatusChip';
import { Note } from '@/components/ui/Note';
import { DisabledWithReason } from '@/components/ui/DisabledWithReason';
import { useToast } from '@/components/feedback/ToastProvider';
import { useCreatePlan, usePlansQuery, useUpdatePlan } from '@/hooks/queries';
import { canEditPlans, canWrite } from '@/lib/permissions';
import { useFormFailure } from '@/lib/useFormFailure';
import { formatMoney, isValidMoneyInput, normaliseMoneyInput } from '@/lib/money';
import { CURRENCIES, type MembershipPlan } from '@/api/types';

/**
 * The packages a gym sells. Readable by every role, writable by the owner only.
 *
 * `price` is handled as text end to end — validated with a regex, submitted as the
 * string typed — because the backend stores a 12-digit decimal and a JavaScript
 * number round trip can lose the last cent.
 *
 * `max_members_allowed` deliberately does not appear: that field belongs to SaasPlan,
 * the platform's own billing tier, not to a gym's membership plan.
 */

const schema = z.object({
  name: z.string().trim().min(1, 'Give the plan a name.').max(200),
  price: z
    .string()
    .trim()
    .refine(isValidMoneyInput, 'Up to 10 digits, with at most 2 decimal places.'),
  duration_days: z
    .string()
    .refine((v) => {
      const n = Number.parseInt(v, 10);
      return Number.isFinite(n) && n >= 1 && n <= 3650;
    }, 'Between 1 and 3650 days.'),
  currency: z.string(),
  includes_trainer: z.boolean().optional(),
  includes_diet: z.boolean().optional(),
});

type Values = z.infer<typeof schema>;
const FIELDS = ['name', 'price', 'duration_days', 'currency', 'includes_trainer', 'includes_diet'] as const;

export default function MembershipPlans(): JSX.Element {
  const me = useMe();
  const toast = useToast();
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<MembershipPlan | null>(null);

  const plans = usePlansQuery(page);
  const mayEdit = canEditPlans(me.role);
  const writeGate = canWrite(me);

  const columns: readonly Column<MembershipPlan>[] = useMemo(
    () => [
      {
        key: 'name',
        header: 'Plan',
        render: (row) => <span className="font-medium text-ink break-value">{row.name}</span>,
      },
      {
        key: 'price',
        header: 'Price',
        align: 'end',
        render: (row) => <span className="tabular">{formatMoney(row.price, row.currency)}</span>,
      },
      {
        key: 'duration_days',
        header: 'Duration',
        align: 'end',
        render: (row) => <span className="tabular">{row.duration_days} days</span>,
      },
      {
        key: 'includes',
        header: 'Includes',
        render: (row) => (
          <span className="flex flex-wrap gap-2">
            <Chip tone={row.includes_trainer ? 'info' : 'neutral'}>
              {row.includes_trainer ? 'Trainer' : 'No trainer'}
            </Chip>
            <Chip tone={row.includes_diet ? 'info' : 'neutral'}>
              {row.includes_diet ? 'Diet' : 'No diet'}
            </Chip>
          </span>
        ),
      },
      ...(mayEdit
        ? [
            {
              key: 'actions',
              header: 'Actions',
              align: 'end' as const,
              render: (row: MembershipPlan) => (
                <DisabledWithReason disabled={!writeGate.allowed} reason={writeGate.reason ?? ''}>
                  <Button variant="secondary" size="sm" onClick={() => setEditing(row)}>
                    Edit
                  </Button>
                </DisabledWithReason>
              ),
            },
          ]
        : []),
    ],
    [mayEdit, writeGate.allowed, writeGate.reason],
  );

  const createAction = mayEdit ? (
    <DisabledWithReason disabled={!writeGate.allowed} reason={writeGate.reason ?? ''}>
      <Button variant="primary" onClick={() => setCreating(true)}>
        <Plus aria-hidden="true" className="h-4 w-4" />
        <span>New plan</span>
      </Button>
    </DisabledWithReason>
  ) : undefined;

  return (
    <PageSections>
      <PageHeader
        title="Membership plans"
        description={
          mayEdit
            ? 'The packages this gym offers.'
            : 'The packages this gym offers. Read-only for your role.'
        }
        actions={createAction}
      />

      <Note>
        Plans can be created and edited, but no member can be enrolled on one or billed for it
        through the API — there is no membership endpoint. A plan assigned to a member records the
        intent without starting a paid period.
      </Note>

      {plans.isPending ? (
        <SkeletonTable rows={25} columns={4} label="membership plans" />
      ) : plans.isError ? (
        <ErrorState error={plans.error} onRetry={() => void plans.refetch()} />
      ) : plans.data.count === 0 ? (
        <EmptyState
          title="No plans yet"
          description={
            mayEdit
              ? 'Create the first plan so members can be assigned to it.'
              : 'This gym has not defined any membership plans.'
          }
          action={createAction}
        />
      ) : (
        <DataList
          caption="Membership plans"
          orderedBy="price, lowest first"
          columns={columns}
          rows={plans.data.results}
          rowKey={(row) => row.id}
          count={plans.data.count}
          page={page}
          hasNext={plans.data.next !== null}
          hasPrevious={plans.data.previous !== null}
          onPageChange={setPage}
          isFetching={plans.isFetching}
        />
      )}

      {creating ? (
        <PlanDialog
          mode="create"
          onClose={() => setCreating(false)}
          onDone={() => {
            toast.success('Plan created.');
            setCreating(false);
          }}
        />
      ) : null}

      {editing !== null ? (
        <PlanDialog
          mode="edit"
          plan={editing}
          onClose={() => setEditing(null)}
          onDone={() => {
            toast.success('Plan updated.');
            setEditing(null);
          }}
        />
      ) : null}
    </PageSections>
  );
}

function PlanDialog({
  mode,
  plan,
  onClose,
  onDone,
}: {
  mode: 'create' | 'edit';
  plan?: MembershipPlan;
  onClose: () => void;
  onDone: () => void;
}): JSX.Element {
  const create = useCreatePlan();
  const update = useUpdatePlan(plan?.id ?? -1);
  const mutation = mode === 'create' ? create : update;

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: plan?.name ?? '',
      // The decimal string goes into the control unchanged.
      price: plan?.price ?? '',
      duration_days: plan === undefined ? '30' : String(plan.duration_days),
      currency: plan?.currency ?? 'INR',
      includes_trainer: plan?.includes_trainer ?? false,
      includes_diet: plan?.includes_diet ?? false,
    },
  });
  const failure = useFormFailure<Values>(setError);

  const onSubmit = async (values: Values): Promise<void> => {
    failure.clearFormError();
    const payload = {
      name: values.name.trim(),
      price: normaliseMoneyInput(values.price),
      duration_days: Number.parseInt(values.duration_days, 10),
      currency: values.currency,
      includes_trainer: values.includes_trainer ?? false,
      includes_diet: values.includes_diet ?? false,
    };

    try {
      if (mode === 'create') await create.mutateAsync(payload as never);
      else await update.mutateAsync(payload as never);
      onDone();
    } catch (error) {
      failure.handle(error, FIELDS);
    }
  };

  return (
    <Dialog
      open
      onClose={onClose}
      title={mode === 'create' ? 'New membership plan' : 'Edit membership plan'}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={() => void handleSubmit(onSubmit)()}
            loading={mutation.isPending}
            disabled={mutation.isPending || failure.locked}
          >
            {failure.locked ? `Wait ${failure.lockedSeconds}s` : 'Save plan'}
          </Button>
        </>
      }
    >
      <form noValidate onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-5">
        {failure.formError !== null ? (
          <p role="alert" className="text-small text-error">
            {failure.formError}
          </p>
        ) : null}

        <TextField
          label="Name"
          required
          error={errors.name?.message}
          hint="Unique within your gym, ignoring letter case."
          {...register('name')}
        />
        <div className="grid gap-5 sm:grid-cols-2">
          <TextField
            label="Price"
            required
            inputMode="decimal"
            error={errors.price?.message}
            hint="Up to 10 digits and 2 decimals, for example 1500.00."
            {...register('price')}
          />
          <SelectField label="Currency" error={errors.currency?.message} {...register('currency')}>
            {CURRENCIES.map((currency) => (
              <option key={currency} value={currency}>
                {currency}
              </option>
            ))}
          </SelectField>
        </div>
        <TextField
          label="Duration in days"
          required
          type="number"
          min={1}
          max={3650}
          error={errors.duration_days?.message}
          hint="Between 1 and 3650."
          {...register('duration_days')}
        />
        <CheckField label="Includes a trainer" {...register('includes_trainer')} />
        <CheckField label="Includes a diet plan" {...register('includes_diet')} />
      </form>
    </Dialog>
  );
}
