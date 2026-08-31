import { useEffect, useMemo, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useMe } from '@/session/SessionProvider';
import { PageHeader, PageSections } from '@/components/layout/AppShell';
import { Card, CardBody, CardHeader, CardTitle, CardDescription } from '@/components/ui/Card';
import { ReadOnlyField, SelectField, TextField } from '@/components/ui/Field';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { Note } from '@/components/ui/Note';
import { Chip } from '@/components/ui/StatusChip';
import { DisabledWithReason } from '@/components/ui/DisabledWithReason';
import { ErrorState } from '@/components/data/States';
import { SkeletonFields } from '@/components/ui/Skeleton';
import { useToast } from '@/components/feedback/ToastProvider';
import { useGymQuery, useUpdateGym } from '@/hooks/queries';
import { canEditGym, canWrite } from '@/lib/permissions';
import { useFormFailure } from '@/lib/useFormFailure';

/**
 * Gym settings. Readable by every role, writable by the owner.
 *
 * Two fields here have consequences that are not obvious and are hard to reverse,
 * so both are explained inline and both trigger a confirmation naming the change:
 *
 * - `gstin`: setting one makes the backend compute GST on invoices issued AFTERWARDS.
 *   Clearing it leaves the tax fields null, meaning "not applicable". Already-issued
 *   invoices are never recomputed either way.
 * - `timezone`: every membership and billing date is evaluated in it, so changing it
 *   can change the active flags and period ends the server reports with nothing else
 *   having happened.
 *
 * `slug` is read-only because it is embedded in every invoice number already issued.
 */

const E164 = /^\+[1-9]\d{7,14}$/;
const GSTIN = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/;

const schema = z.object({
  name: z.string().trim().min(1, 'The gym needs a name.').max(200),
  contact_email: z
    .string()
    .trim()
    .refine((v) => v === '' || z.string().email().safeParse(v).success, 'Enter a valid email address.'),
  contact_phone: z
    .string()
    .trim()
    .min(1, 'A contact phone number is required.')
    .max(16, 'At most 16 characters.')
    .regex(E164, 'Use international format, such as +919876543210.'),
  timezone: z.string().min(1, 'Choose a timezone.'),
  gstin: z
    .string()
    .trim()
    .refine((v) => v === '' || GSTIN.test(v.toUpperCase()), 'A GSTIN is 15 characters, such as 22AAAAA0000A1Z5.'),
});

type Values = z.infer<typeof schema>;
const FIELDS = ['name', 'contact_email', 'contact_phone', 'timezone', 'gstin'] as const;

/** IANA names the browser knows, plus the gym's current value if it is not listed. */
function timezoneOptions(current: string): string[] {
  let names: string[] = [];
  const withSupport = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
  if (typeof withSupport.supportedValuesOf === 'function') {
    try {
      names = withSupport.supportedValuesOf('timeZone');
    } catch {
      names = [];
    }
  }
  if (names.length === 0) names = [current, 'UTC', 'Asia/Kolkata'];
  if (!names.includes(current)) names = [current, ...names];
  return names;
}

export default function GymPage(): JSX.Element {
  const me = useMe();
  const toast = useToast();
  const gym = useGymQuery();
  const update = useUpdateGym();

  const mayEdit = canEditGym(me.role);
  const writeGate = canWrite(me);
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState<Values | null>(null);

  const {
    register,
    handleSubmit,
    setError,
    reset,
    formState: { errors, isDirty, dirtyFields },
  } = useForm<Values>({ resolver: zodResolver(schema) });
  const failure = useFormFailure<Values>(setError);

  useEffect(() => {
    if (gym.data === undefined) return;
    reset({
      name: gym.data.name,
      contact_email: gym.data.contact_email ?? '',
      contact_phone: gym.data.contact_phone ?? '',
      timezone: gym.data.timezone,
      gstin: gym.data.gstin ?? '',
    });
  }, [gym.data, reset]);

  const options = useMemo(() => timezoneOptions(gym.data?.timezone ?? 'UTC'), [gym.data?.timezone]);

  if (gym.isPending) {
    return (
      <PageSections>
        <PageHeader title="Gym" />
        <Card>
          <CardBody className="pt-5">
            <SkeletonFields fields={8} label="gym" />
          </CardBody>
        </Card>
      </PageSections>
    );
  }

  if (gym.isError) {
    return (
      <PageSections>
        <ErrorState error={gym.error} onRetry={() => void gym.refetch()} />
      </PageSections>
    );
  }

  const record = gym.data;

  const submit = async (values: Values): Promise<void> => {
    failure.clearFormError();
    const payload: Record<string, string> = {};
    if (dirtyFields.name) payload.name = values.name.trim();
    if (dirtyFields.contact_email) payload.contact_email = values.contact_email.trim();
    if (dirtyFields.contact_phone) payload.contact_phone = values.contact_phone.trim();
    if (dirtyFields.timezone) payload.timezone = values.timezone;
    if (dirtyFields.gstin) payload.gstin = values.gstin.trim().toUpperCase();

    if (Object.keys(payload).length === 0) {
      setEditing(false);
      return;
    }

    try {
      await update.mutateAsync(payload);
      toast.success('Gym updated.');
      setEditing(false);
      setConfirming(null);
    } catch (error) {
      failure.handle(error, FIELDS);
      setConfirming(null);
    }
  };

  const onSubmit = (values: Values): void => {
    const gstinChanged = (record.gstin ?? '') !== values.gstin.trim().toUpperCase();
    const timezoneChanged = record.timezone !== values.timezone;
    if (gstinChanged || timezoneChanged) {
      setConfirming(values);
      return;
    }
    void submit(values);
  };

  return (
    <PageSections>
      <PageHeader
        title={record.name}
        description={mayEdit ? 'Your gym details.' : 'Your gym details. Read-only for your role.'}
        actions={
          mayEdit && !editing ? (
            <DisabledWithReason disabled={!writeGate.allowed} reason={writeGate.reason ?? ''}>
              <Button variant="primary" onClick={() => setEditing(true)}>
                Edit gym
              </Button>
            </DisabledWithReason>
          ) : undefined
        }
      />

      <Card>
        <CardHeader>
          <div className="flex flex-col gap-1">
            <CardTitle>Details</CardTitle>
            <CardDescription>These values appear on the invoices this gym issues.</CardDescription>
          </div>
          <Chip tone={record.is_active ? 'success' : 'error'}>
            {record.is_active ? 'Active' : 'Inactive'}
          </Chip>
        </CardHeader>

        <CardBody>
          {editing ? (
            <form noValidate onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-5">
              {failure.formError !== null ? (
                <p role="alert" className="text-small text-error">
                  {failure.formError}
                </p>
              ) : null}

              <TextField label="Name" required error={errors.name?.message} {...register('name')} />
              <div className="grid gap-5 sm:grid-cols-2">
                <TextField
                  label="Contact email"
                  type="email"
                  error={errors.contact_email?.message}
                  {...register('contact_email')}
                />
                <TextField
                  label="Contact phone"
                  required
                  error={errors.contact_phone?.message}
                  hint="International format, such as +919876543210."
                  {...register('contact_phone')}
                />
              </div>

              <SelectField
                label="Timezone"
                required
                error={errors.timezone?.message}
                hint="Every membership and billing date is evaluated in this timezone. Changing it can change the active flags and period ends the server reports, with nothing else having happened."
                {...register('timezone')}
              >
                {options.map((zone) => (
                  <option key={zone} value={zone}>
                    {zone}
                  </option>
                ))}
              </SelectField>

              <TextField
                label="GSTIN"
                error={errors.gstin?.message}
                hint="Setting a GSTIN makes the backend compute GST on invoices issued afterwards. Clearing it leaves tax fields null, meaning not applicable — which is different from zero. Invoices already issued are never recomputed."
                {...register('gstin')}
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
              <ReadOnlyField label="Name" value={record.name} />
              <ReadOnlyField
                label="Slug"
                value={record.slug}
                hint="Cannot be changed: it forms part of every invoice number already issued."
              />
              <ReadOnlyField label="Contact email" value={record.contact_email ?? 'Not set'} />
              <ReadOnlyField label="Contact phone" value={record.contact_phone ?? 'Not set'} />
              <ReadOnlyField
                label="Timezone"
                value={record.timezone}
                hint="All membership and billing dates are evaluated here."
              />
              <ReadOnlyField
                label="GSTIN"
                value={record.gstin ?? 'Not set'}
                hint={
                  record.gstin === null
                    ? 'Without a GSTIN, invoices carry null tax fields, meaning not applicable.'
                    : 'GST is computed on invoices issued while this is set.'
                }
              />
              <ReadOnlyField label="Gym id" value={String(record.id)} />
            </div>
          )}
        </CardBody>
      </Card>

      <Note>
        No subscription plan, seat limit or seat usage figure is shown, because no endpoint reports
        which platform plan this gym holds. A seat limit only surfaces as an error when a member
        creation is refused.
      </Note>

      <Dialog
        open={confirming !== null}
        onClose={() => setConfirming(null)}
        title="Confirm this change"
        description="These two fields change how the backend computes tax and dates."
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirming(null)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              loading={update.isPending}
              onClick={() => {
                if (confirming !== null) void submit(confirming);
              }}
            >
              Apply change
            </Button>
          </>
        }
      >
        {confirming !== null ? (
          <div className="flex flex-col gap-4">
            {record.timezone !== confirming.timezone ? (
              <div className="flex flex-col gap-1">
                <span className="text-small font-medium text-ink">Timezone</span>
                <span className="text-small text-muted break-value">
                  {record.timezone} &rarr; {confirming.timezone}
                </span>
                <span className="text-caption text-muted">
                  Membership and billing dates are evaluated in this timezone, so active flags and
                  period ends the server reports may change.
                </span>
              </div>
            ) : null}
            {(record.gstin ?? '') !== confirming.gstin.trim().toUpperCase() ? (
              <div className="flex flex-col gap-1">
                <span className="text-small font-medium text-ink">GSTIN</span>
                <span className="text-small text-muted break-value">
                  {record.gstin ?? 'Not set'} &rarr;{' '}
                  {confirming.gstin.trim() === '' ? 'Not set' : confirming.gstin.trim().toUpperCase()}
                </span>
                <span className="text-caption text-muted">
                  Affects GST on invoices issued after this change. Invoices already issued are not
                  recomputed.
                </span>
              </div>
            ) : null}
          </div>
        ) : null}
      </Dialog>
    </PageSections>
  );
}
