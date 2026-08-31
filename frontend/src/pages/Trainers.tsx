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
import { TextField } from '@/components/ui/Field';
import { Note } from '@/components/ui/Note';
import { TrainerStatusChip } from '@/components/ui/StatusChip';
import { DisabledWithReason } from '@/components/ui/DisabledWithReason';
import { useToast } from '@/components/feedback/ToastProvider';
import { useCreateTrainer, useTrainersQuery } from '@/hooks/queries';
import { canWrite } from '@/lib/permissions';
import { useFormFailure } from '@/lib/useFormFailure';
import type { TrainerProfile } from '@/api/types';

/**
 * Trainers are list-and-create only. `core/urls.py` registers no `trainers/{id}`
 * path at all, so there is no detail route, no PATCH and no DELETE — which means
 * `specialization` and `status` can be set at creation and never changed again.
 * No edit control is rendered, and the limitation is stated on the page.
 *
 * Unlike member creation, `invite_trainer` does call `send_invite_email` with a
 * generated temporary password, so a new trainer really can sign in.
 */

const E164 = /^\+[1-9]\d{7,14}$/;

const schema = z.object({
  email: z.string().trim().email('Enter a valid email address.'),
  first_name: z.string().trim().max(150).optional(),
  last_name: z.string().trim().max(150).optional(),
  phone: z
    .string()
    .trim()
    .max(16, 'At most 16 characters.')
    .refine((v) => v === '' || E164.test(v), 'Use international format, such as +919876543210.')
    .optional(),
  specialization: z.string().trim().max(200).optional(),
});

type Values = z.infer<typeof schema>;
const FIELDS = ['email', 'first_name', 'last_name', 'phone', 'specialization'] as const;

export default function Trainers(): JSX.Element {
  const me = useMe();
  const toast = useToast();
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);

  const trainers = useTrainersQuery(page);
  const writeGate = canWrite(me);

  const columns: readonly Column<TrainerProfile>[] = useMemo(
    () => [
      {
        key: 'name',
        header: 'Trainer',
        render: (row) => (
          <div className="flex flex-col gap-1">
            <span className="font-medium text-ink break-value">
              {row.full_name.trim() === '' ? 'Not provided' : row.full_name}
            </span>
            <span className="text-caption text-muted break-value">{row.email}</span>
          </div>
        ),
      },
      {
        key: 'specialization',
        header: 'Specialization',
        render: (row) =>
          row.specialization.trim() === '' ? (
            <span className="text-muted">Not provided</span>
          ) : (
            <span className="break-value">{row.specialization}</span>
          ),
      },
      {
        key: 'status',
        header: 'Status',
        render: (row) => <TrainerStatusChip status={row.status} />,
      },
    ],
    [],
  );

  const createAction = (
    <DisabledWithReason disabled={!writeGate.allowed} reason={writeGate.reason ?? ''}>
      <Button variant="primary" onClick={() => setCreating(true)}>
        <Plus aria-hidden="true" className="h-4 w-4" />
        <span>Invite trainer</span>
      </Button>
    </DisabledWithReason>
  );

  return (
    <PageSections>
      <PageHeader
        title="Trainers"
        description="Staff who can be assigned to members."
        actions={createAction}
      />

      <Note>
        A trainer's specialization and status cannot be changed after creation — the API exposes no
        trainer update route. Set them correctly when inviting.
      </Note>

      {trainers.isPending ? (
        <SkeletonTable rows={25} columns={3} label="trainers" />
      ) : trainers.isError ? (
        <ErrorState error={trainers.error} onRetry={() => void trainers.refetch()} />
      ) : trainers.data.count === 0 ? (
        <EmptyState
          title="No trainers yet"
          description={
            writeGate.allowed
              ? 'Invite a trainer and they will receive an email with a temporary password.'
              : (writeGate.reason ?? 'Inviting trainers is unavailable right now.')
          }
          action={writeGate.allowed ? createAction : undefined}
        />
      ) : (
        <DataList
          caption="Trainers"
          orderedBy="creation order"
          columns={columns}
          rows={trainers.data.results}
          rowKey={(row) => row.id}
          count={trainers.data.count}
          page={page}
          hasNext={trainers.data.next !== null}
          hasPrevious={trainers.data.previous !== null}
          onPageChange={setPage}
          isFetching={trainers.isFetching}
        />
      )}

      <InviteTrainerDialog
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={() => {
          toast.success('Trainer created. An email with a temporary password has been sent.');
          setCreating(false);
        }}
      />
    </PageSections>
  );
}

function InviteTrainerDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}): JSX.Element {
  const create = useCreateTrainer();
  const {
    register,
    handleSubmit,
    setError,
    reset,
    formState: { errors },
  } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { email: '' } });
  const failure = useFormFailure<Values>(setError);

  const onSubmit = async (values: Values): Promise<void> => {
    failure.clearFormError();
    const payload: Record<string, unknown> = { email: values.email.trim() };
    if (values.first_name?.trim()) payload.first_name = values.first_name.trim();
    if (values.last_name?.trim()) payload.last_name = values.last_name.trim();
    if (values.phone?.trim()) payload.phone = values.phone.trim();
    if (values.specialization?.trim()) payload.specialization = values.specialization.trim();

    try {
      await create.mutateAsync(payload as never);
      reset();
      onCreated();
    } catch (error) {
      failure.handle(error, FIELDS);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Invite trainer"
      description="Only the email address is required. Specialization cannot be changed later."
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
            {failure.locked ? `Wait ${failure.lockedSeconds}s` : 'Send invite'}
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
        <TextField
          label="Specialization"
          error={errors.specialization?.message}
          hint="Cannot be edited after creation."
          {...register('specialization')}
        />
      </form>
    </Dialog>
  );
}
