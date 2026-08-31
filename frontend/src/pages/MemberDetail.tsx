import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useMe } from '@/session/SessionProvider';
import { PageHeader, PageSections } from '@/components/layout/AppShell';
import { Card, CardBody, CardHeader, CardTitle, CardDescription } from '@/components/ui/Card';
import { ReadOnlyField, SelectField, TextField } from '@/components/ui/Field';
import { Button } from '@/components/ui/Button';
import { Note } from '@/components/ui/Note';
import { ActiveChip } from '@/components/ui/StatusChip';
import { Avatar } from '@/components/ui/Avatar';
import { TextLink } from '@/components/ui/TextLink';
import { DisabledWithReason } from '@/components/ui/DisabledWithReason';
import { ErrorState, NotFoundState } from '@/components/data/States';
import { SkeletonFields } from '@/components/ui/Skeleton';
import { useToast } from '@/components/feedback/ToastProvider';
import {
  useAllPlansQuery,
  useAllTrainersQuery,
  useMemberQuery,
  useUpdateMember,
} from '@/hooks/queries';
import { canEditMembers, canWrite } from '@/lib/permissions';
import { useFormFailure } from '@/lib/useFormFailure';
import { ApiError } from '@/lib/errors';
import { GOALS } from '@/api/types';

/**
 * One composed surface, deliberately not a tab strip.
 *
 * A gym product usually shows Overview / Attendance / Payments / Workouts here.
 * None of those can exist against this backend: Attendance, WorkoutLog and the rest
 * are models with no routes at all — routing them fails the build's own API-surface
 * check — and although invoices exist, no list endpoint accepts a filter, so an
 * owner cannot retrieve one member's invoices even in principle.
 *
 * That leaves exactly one real dataset for a member: their MemberProfile. A single
 * surface is the honest presentation of one dataset; four tabs with three of them
 * empty would not be.
 */

const schema = z.object({
  plan: z.string().optional(),
  trainer: z.string().optional(),
  join_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'Pick a join date.'),
  goal: z.string().optional(),
  photo_url: z
    .string()
    .trim()
    .refine((v) => v === '' || z.string().url().safeParse(v).success, 'Enter a full URL.')
    .optional(),
});

type Values = z.infer<typeof schema>;
const FIELDS = ['plan', 'trainer', 'join_date', 'goal', 'photo_url'] as const;

export default function MemberDetail(): JSX.Element {
  const me = useMe();
  const toast = useToast();
  const params = useParams<{ id: string }>();
  const parsedId = Number.parseInt(params.id ?? '', 10);
  const id = Number.isFinite(parsedId) ? parsedId : null;

  const member = useMemberQuery(id);
  const plans = useAllPlansQuery();
  const trainers = useAllTrainersQuery(me.role === 'owner');
  const update = useUpdateMember(id ?? -1);

  const [editing, setEditing] = useState(false);
  const writeGate = canWrite(me);
  const mayEdit = canEditMembers(me.role);

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

  const {
    register,
    handleSubmit,
    setError,
    reset,
    formState: { errors, isDirty, dirtyFields },
  } = useForm<Values>({ resolver: zodResolver(schema) });
  const failure = useFormFailure<Values>(setError);

  // Seed the form from the loaded record once it arrives.
  useEffect(() => {
    if (member.data === undefined) return;
    reset({
      plan: member.data.plan === null ? '' : String(member.data.plan),
      trainer: member.data.trainer === null ? '' : String(member.data.trainer),
      join_date: member.data.join_date,
      goal: member.data.goal,
      photo_url: member.data.photo_url,
    });
  }, [member.data, reset]);

  // A 404 here is indistinguishable from another gym's id by design. Show the fixed
  // not-found surface, never a permissions message.
  if (member.isError && member.error instanceof ApiError && member.error.status === 404) {
    return (
      <PageSections>
        <NotFoundState action={<TextLink to="/members">Back to members</TextLink>} />
      </PageSections>
    );
  }

  if (member.isPending) {
    return (
      <PageSections>
        <PageHeader title="Member" />
        <Card>
          <CardBody className="pt-5">
            <SkeletonFields fields={7} label="member" />
          </CardBody>
        </Card>
      </PageSections>
    );
  }

  if (member.isError) {
    return (
      <PageSections>
        <ErrorState error={member.error} onRetry={() => void member.refetch()} />
      </PageSections>
    );
  }

  const record = member.data;

  const onSubmit = async (values: Values): Promise<void> => {
    failure.clearFormError();
    // Only changed fields go in the PATCH body.
    const payload: Record<string, unknown> = {};
    if (dirtyFields.plan) payload.plan = values.plan ? Number(values.plan) : null;
    if (dirtyFields.trainer && me.role === 'owner') {
      payload.trainer = values.trainer ? Number(values.trainer) : null;
    }
    if (dirtyFields.join_date) payload.join_date = values.join_date;
    if (dirtyFields.goal) payload.goal = values.goal ?? '';
    if (dirtyFields.photo_url) payload.photo_url = values.photo_url?.trim() ?? '';

    if (Object.keys(payload).length === 0) {
      setEditing(false);
      return;
    }

    try {
      await update.mutateAsync(payload);
      toast.success('Member updated.');
      setEditing(false);
    } catch (error) {
      failure.handle(error, FIELDS);
    }
  };

  return (
    <PageSections>
      <PageHeader
        title={record.full_name}
        description={record.email}
        actions={
          mayEdit && !editing ? (
            <DisabledWithReason disabled={!writeGate.allowed} reason={writeGate.reason ?? ''}>
              <Button variant="primary" onClick={() => setEditing(true)}>
                Edit member
              </Button>
            </DisabledWithReason>
          ) : undefined
        }
      />

      <Card>
        <CardHeader>
          <div className="flex items-center gap-4">
            <Avatar name={record.full_name} />
            <div className="flex flex-col gap-1">
              <CardTitle>Profile</CardTitle>
              <CardDescription>
                The complete record the API exposes for this member.
              </CardDescription>
            </div>
          </div>
          <ActiveChip active={record.is_active} />
        </CardHeader>

        <CardBody>
          {editing ? (
            <form noValidate onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-5">
              {failure.formError !== null ? (
                <p role="alert" className="text-small text-error">
                  {failure.formError}
                </p>
              ) : null}

              <div className="grid gap-5 sm:grid-cols-2">
                <SelectField label="Plan" error={errors.plan?.message} {...register('plan')}>
                  <option value="">No plan</option>
                  {(plans.data?.items ?? []).map((plan) => (
                    <option key={plan.id} value={plan.id}>
                      {plan.name}
                    </option>
                  ))}
                </SelectField>

                {me.role === 'owner' ? (
                  <SelectField label="Trainer" error={errors.trainer?.message} {...register('trainer')}>
                    <option value="">No trainer</option>
                    {(trainers.data?.items ?? []).map((trainer) => (
                      <option key={trainer.id} value={trainer.id}>
                        {trainer.full_name}
                      </option>
                    ))}
                  </SelectField>
                ) : (
                  <ReadOnlyField
                    label="Trainer"
                    value="Assigned to you"
                    hint="A trainer cannot list trainers, so no trainer can be selected here."
                  />
                )}

                <TextField
                  label="Join date"
                  type="date"
                  error={errors.join_date?.message}
                  {...register('join_date')}
                />

                <SelectField label="Goal" error={errors.goal?.message} {...register('goal')}>
                  <option value="">Not set</option>
                  {GOALS.map((goal) => (
                    <option key={goal} value={goal}>
                      {goal}
                    </option>
                  ))}
                </SelectField>
              </div>

              <TextField
                label="Photo URL"
                error={errors.photo_url?.message}
                hint="A URL. The API has no file upload endpoint."
                {...register('photo_url')}
              />

              <div className="flex flex-wrap gap-3">
                <Button
                  type="submit"
                  variant="primary"
                  loading={update.isPending}
                  disabled={update.isPending || !isDirty}
                >
                  Save changes
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => {
                    setEditing(false);
                    failure.clearFormError();
                    reset();
                  }}
                >
                  Cancel
                </Button>
              </div>
            </form>
          ) : (
            <div className="grid gap-6 sm:grid-cols-2">
              <ReadOnlyField label="Email" value={record.email} />
              <ReadOnlyField label="Joined" value={<span className="tabular">{record.join_date}</span>} />
              <ReadOnlyField
                label="Plan"
                value={
                  record.plan === null
                    ? 'No plan'
                    : (planNames.get(record.plan) ?? `#${record.plan}`)
                }
              />
              <ReadOnlyField
                label="Trainer"
                value={
                  me.role !== 'owner'
                    ? 'Assigned to you'
                    : record.trainer === null
                      ? 'No trainer assigned'
                      : (trainerNames.get(record.trainer) ?? `#${record.trainer}`)
                }
              />
              <ReadOnlyField label="Goal" value={record.goal === '' ? 'Not set' : record.goal} />
              <ReadOnlyField
                label="Period ends"
                value={
                  <span className="tabular">{record.current_period_end ?? 'No period end'}</span>
                }
                hint="Computed by the server from membership dates and invoice settlement."
              />
              <ReadOnlyField
                label="Photo URL"
                value={record.photo_url === '' ? 'Not set' : record.photo_url}
                className="sm:col-span-2"
              />
            </div>
          )}
        </CardBody>
      </Card>

      <div className="flex flex-col gap-4">
        <Note>
          This is everything the API exposes for a member. There is no attendance,
          payment-per-member, workout or activity endpoint, and invoices cannot be filtered by
          member, so there is nothing further to show here.
        </Note>
        <Note>
          A member cannot be deleted, deactivated or archived — no route accepts DELETE and the
          record has no writable status field. Active state is derived by the server.
        </Note>
      </div>
    </PageSections>
  );
}
