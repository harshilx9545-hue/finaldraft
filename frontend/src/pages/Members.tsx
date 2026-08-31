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
import { TextField, SelectField } from '@/components/ui/Field';
import { Note } from '@/components/ui/Note';
import { ActiveChip } from '@/components/ui/StatusChip';
import { DisabledWithReason } from '@/components/ui/DisabledWithReason';
import { useToast } from '@/components/feedback/ToastProvider';
import { useAllPlansQuery, useAllTrainersQuery, useCreateMember, useMembersQuery } from '@/hooks/queries';
import { canCreateMember } from '@/lib/permissions';
import { useFormFailure } from '@/lib/useFormFailure';
import { GOALS, type MemberProfile } from '@/api/types';

const E164 = /^\+[1-9]\d{7,14}$/;

const schema = z.object({
  email: z.string().trim().email('Enter a valid email address.'),
  join_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'Pick a join date.'),
  first_name: z.string().trim().max(150).optional(),
  last_name: z.string().trim().max(150).optional(),
  phone: z
    .string()
    .trim()
    .max(16, 'At most 16 characters.')
    .refine((v) => v === '' || E164.test(v), 'Use international format, such as +919876543210.')
    .optional(),
  plan: z.string().optional(),
  trainer: z.string().optional(),
  goal: z.string().optional(),
  photo_url: z
    .string()
    .trim()
    .refine((v) => v === '' || z.string().url().safeParse(v).success, 'Enter a full URL.')
    .optional(),
});

type Values = z.infer<typeof schema>;

const FIELDS = [
  'email',
  'join_date',
  'first_name',
  'last_name',
  'phone',
  'plan',
  'trainer',
  'goal',
  'photo_url',
] as const;

export default function Members(): JSX.Element {
  const me = useMe();
  const toast = useToast();
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const [createdNotice, setCreatedNotice] = useState<string | null>(null);

  const isOwner = me.role === 'owner';
  const members = useMembersQuery(page);
  // Bare foreign keys arrive as integers with no name, and the backend offers no
  // lookup, so the whole plan collection is fetched to resolve them.
  const plans = useAllPlansQuery();
  // Owner only: GET /api/trainers is 403 for a trainer, so a trainer cannot resolve
  // any trainer name — including their own.
  const trainers = useAllTrainersQuery(isOwner);

  const planNames = useMemo(() => {
    const map = new Map<number, string>();
    for (const plan of plans.data?.items ?? []) map.set(plan.id, plan.name);
    return map;
  }, [plans.data]);

  const trainerNames = useMemo(() => {
    const map = new Map<number, string>();
    for (const trainer of trainers.data?.items ?? []) map.set(trainer.id, trainer.full_name);
    return map;
  }, [trainers.data]);

  const createGate = canCreateMember(me);

  const columns: readonly Column<MemberProfile>[] = useMemo(
    () => [
      {
        key: 'name',
        header: 'Member',
        render: (row) => (
          <div className="flex flex-col gap-1">
            <span className="font-medium text-ink break-value">{row.full_name}</span>
            <span className="text-caption text-muted break-value">{row.email}</span>
          </div>
        ),
      },
      {
        key: 'plan',
        header: 'Plan',
        render: (row) =>
          row.plan === null ? (
            <span className="text-muted">No plan</span>
          ) : (
            // Falls back to the raw id when the name is not resolvable, rather than
            // hiding the value or inventing one.
            <span className="break-value">{planNames.get(row.plan) ?? `#${row.plan}`}</span>
          ),
      },
      {
        key: 'trainer',
        header: 'Trainer',
        render: (row) => {
          if (!isOwner) return <span className="text-muted">Assigned to you</span>;
          if (row.trainer === null) return <span className="text-muted">No trainer assigned</span>;
          return <span className="break-value">{trainerNames.get(row.trainer) ?? `#${row.trainer}`}</span>;
        },
      },
      {
        key: 'join_date',
        header: 'Joined',
        render: (row) => <span className="tabular">{row.join_date}</span>,
      },
      {
        key: 'goal',
        header: 'Goal',
        render: (row) => (row.goal === '' ? <span className="text-muted">Not set</span> : row.goal),
      },
      {
        key: 'is_active',
        header: 'Status',
        render: (row) => <ActiveChip active={row.is_active} />,
      },
      {
        key: 'current_period_end',
        header: 'Period ends',
        render: (row) => (
          <span className="tabular">{row.current_period_end ?? 'No period end'}</span>
        ),
      },
    ],
    [isOwner, planNames, trainerNames],
  );

  const createAction = (
    <DisabledWithReason disabled={!createGate.allowed} reason={createGate.reason ?? ''}>
      <Button variant="primary" onClick={() => setCreating(true)}>
        <Plus aria-hidden="true" className="h-4 w-4" />
        <span>Add member</span>
      </Button>
    </DisabledWithReason>
  );

  return (
    <PageSections>
      <PageHeader
        title="Members"
        description="Everyone on your roster, as the API reports them."
        actions={createAction}
      />

      <div className="flex flex-col gap-4">
        <Note>
          Starting or renewing a paid membership period is not available through the API. A member
          added here therefore shows as not active with no period end, and no action on this screen
          can change that.
        </Note>
        {createdNotice !== null ? (
          <Note tone="warning">
            {createdNotice}{' '}
            <button
              type="button"
              onClick={() => setCreatedNotice(null)}
              className="underline underline-offset-2"
            >
              Dismiss
            </button>
          </Note>
        ) : null}
      </div>

      {members.isPending ? (
        <SkeletonTable rows={25} columns={6} label="members" />
      ) : members.isError ? (
        <ErrorState error={members.error} onRetry={() => void members.refetch()} />
      ) : members.data.count === 0 ? (
        <EmptyState
          title="No members yet"
          description={
            createGate.allowed
              ? 'Add your first member to start building the roster.'
              : (createGate.reason ?? 'Adding members is unavailable right now.')
          }
          action={createGate.allowed ? createAction : undefined}
        />
      ) : (
        <DataList
          caption="Members"
          orderedBy="most recent join date"
          columns={columns}
          rows={members.data.results}
          rowKey={(row) => row.id}
          count={members.data.count}
          page={page}
          hasNext={members.data.next !== null}
          hasPrevious={members.data.previous !== null}
          onPageChange={setPage}
          rowHref={(row) => `/members/${row.id}`}
          isFetching={members.isFetching}
        />
      )}

      <CreateMemberDialog
        open={creating}
        onClose={() => setCreating(false)}
        isOwner={isOwner}
        planOptions={plans.data?.items ?? []}
        trainerOptions={trainers.data?.items ?? []}
        onCreated={(message) => {
          setCreatedNotice(message);
          toast.success('Member created.');
          setCreating(false);
        }}
      />
    </PageSections>
  );
}

function CreateMemberDialog({
  open,
  onClose,
  isOwner,
  planOptions,
  trainerOptions,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  isOwner: boolean;
  planOptions: readonly { id: number; name: string }[];
  trainerOptions: readonly { id: number; full_name: string }[];
  onCreated: (message: string) => void;
}): JSX.Element {
  const create = useCreateMember();
  const {
    register,
    handleSubmit,
    setError,
    reset,
    formState: { errors },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { email: '', join_date: new Date().toISOString().slice(0, 10) },
  });
  const failure = useFormFailure<Values>(setError);

  const onSubmit = async (values: Values): Promise<void> => {
    failure.clearFormError();

    // Optional fields are omitted rather than sent empty, so the backend applies
    // its own defaults instead of storing blanks.
    const payload: Record<string, unknown> = {
      email: values.email.trim(),
      join_date: values.join_date,
    };
    if (values.first_name?.trim()) payload.first_name = values.first_name.trim();
    if (values.last_name?.trim()) payload.last_name = values.last_name.trim();
    if (values.phone?.trim()) payload.phone = values.phone.trim();
    if (values.plan) payload.plan = Number(values.plan);
    // A trainer never sends `trainer`: MemberListCreateView.create overrides it
    // with the requesting trainer's own profile anyway.
    if (isOwner && values.trainer) payload.trainer = Number(values.trainer);
    if (values.goal) payload.goal = values.goal;
    if (values.photo_url?.trim()) payload.photo_url = values.photo_url.trim();

    try {
      await create.mutateAsync(payload as never);
      reset();
      onCreated(
        'Member created. They have no sign-in credentials yet and must use the password reset flow to set a password — the API sends no invitation email.',
      );
    } catch (error) {
      failure.handle(error, FIELDS);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Add member"
      description="Email and join date are required. Everything else is optional."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={() => void handleSubmit(onSubmit)()}
            loading={create.isPending}
            disabled={create.isPending || failure.locked}
          >
            {failure.locked ? `Wait ${failure.lockedSeconds}s` : 'Create member'}
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
          label="Email"
          type="email"
          required
          error={errors.email?.message}
          {...register('email')}
        />
        <TextField
          label="Join date"
          type="date"
          required
          error={errors.join_date?.message}
          hint="Back-dating is allowed."
          {...register('join_date')}
        />
        <div className="grid gap-5 sm:grid-cols-2">
          <TextField label="First name" error={errors.first_name?.message} {...register('first_name')} />
          <TextField label="Last name" error={errors.last_name?.message} {...register('last_name')} />
        </div>
        <TextField
          label="Phone"
          error={errors.phone?.message}
          hint="International format, such as +919876543210."
          {...register('phone')}
        />
        <SelectField label="Plan" error={errors.plan?.message} {...register('plan')}>
          <option value="">No plan</option>
          {planOptions.map((plan) => (
            <option key={plan.id} value={plan.id}>
              {plan.name}
            </option>
          ))}
        </SelectField>
        {isOwner ? (
          <SelectField label="Trainer" error={errors.trainer?.message} {...register('trainer')}>
            <option value="">No trainer</option>
            {trainerOptions.map((trainer) => (
              <option key={trainer.id} value={trainer.id}>
                {trainer.full_name}
              </option>
            ))}
          </SelectField>
        ) : null}
        <SelectField label="Goal" error={errors.goal?.message} {...register('goal')}>
          <option value="">Not set</option>
          {GOALS.map((goal) => (
            <option key={goal} value={goal}>
              {goal}
            </option>
          ))}
        </SelectField>
        <TextField
          label="Photo URL"
          error={errors.photo_url?.message}
          hint="A URL. The API has no file upload endpoint."
          {...register('photo_url')}
        />
      </form>
    </Dialog>
  );
}
