import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useMe, useSession } from '@/session/SessionProvider';
import { PageHeader, PageSections } from '@/components/layout/AppShell';
import { Card, CardBody, CardHeader, CardTitle, CardDescription } from '@/components/ui/Card';
import { ReadOnlyField, TextField } from '@/components/ui/Field';
import { Button } from '@/components/ui/Button';
import { Note } from '@/components/ui/Note';
import { TextLink } from '@/components/ui/TextLink';
import { Avatar } from '@/components/ui/Avatar';
import {
  ActiveChip,
  SubscriptionStatusChip,
  VerifiedChip,
} from '@/components/ui/StatusChip';
import { useToast } from '@/components/feedback/ToastProvider';
import { useUpdateMe } from '@/hooks/queries';
import { useFormFailure } from '@/lib/useFormFailure';

/**
 * Your own account.
 *
 * `MeUpdateSerializer` accepts exactly three fields — first name, last name, phone —
 * so everything else on this page is read-only, including email and role.
 *
 * There is no authenticated password-change route. The only path is the
 * unauthenticated reset flow, and completing it blacklists every refresh token for
 * the account, so it ends every session. The control says so rather than surprising
 * the user with a sign-out.
 */

const E164 = /^\+[1-9]\d{7,14}$/;

const schema = z.object({
  first_name: z.string().trim().max(150),
  last_name: z.string().trim().max(150),
  phone: z
    .string()
    .trim()
    .max(16, 'At most 16 characters.')
    .refine((v) => v === '' || E164.test(v), 'Use international format, such as +919876543210.'),
});

type Values = z.infer<typeof schema>;
const FIELDS = ['first_name', 'last_name', 'phone'] as const;

export default function Profile(): JSX.Element {
  const me = useMe();
  const { refreshMe } = useSession();
  const toast = useToast();
  const update = useUpdateMe();
  const [editing, setEditing] = useState(false);

  const {
    register,
    handleSubmit,
    setError,
    reset,
    formState: { errors, isDirty },
  } = useForm<Values>({ resolver: zodResolver(schema) });
  const failure = useFormFailure<Values>(setError);

  useEffect(() => {
    reset({
      first_name: me.first_name,
      last_name: me.last_name,
      phone: me.phone ?? '',
    });
  }, [me, reset]);

  const displayName = `${me.first_name} ${me.last_name}`.trim() || me.email;

  const onSubmit = async (values: Values): Promise<void> => {
    failure.clearFormError();
    try {
      // All three are sent, including cleared ones as empty strings, because the
      // serializer treats an omitted field as "leave unchanged".
      await update.mutateAsync({
        first_name: values.first_name.trim(),
        last_name: values.last_name.trim(),
        phone: values.phone.trim(),
      });
      await refreshMe();
      toast.success('Profile updated.');
      setEditing(false);
    } catch (error) {
      failure.handle(error, FIELDS);
    }
  };

  return (
    <PageSections>
      <PageHeader
        title="Profile"
        description={me.email}
        actions={
          editing ? undefined : (
            <Button variant="primary" onClick={() => setEditing(true)}>
              Edit profile
            </Button>
          )
        }
      />

      <Card>
        <CardHeader>
          <div className="flex items-center gap-4">
            <Avatar name={displayName} />
            <div className="flex flex-col gap-1">
              <CardTitle>Your details</CardTitle>
              <CardDescription>Name and phone number are the only editable fields.</CardDescription>
            </div>
          </div>
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
                <TextField
                  label="First name"
                  autoComplete="given-name"
                  error={errors.first_name?.message}
                  {...register('first_name')}
                />
                <TextField
                  label="Last name"
                  autoComplete="family-name"
                  error={errors.last_name?.message}
                  {...register('last_name')}
                />
              </div>
              <TextField
                label="Phone"
                error={errors.phone?.message}
                hint="International format, such as +919876543210. Must be unique across the platform."
                {...register('phone')}
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
              <ReadOnlyField label="First name" value={me.first_name || 'Not provided'} />
              <ReadOnlyField label="Last name" value={me.last_name || 'Not provided'} />
              <ReadOnlyField label="Email" value={me.email} hint="Cannot be changed through the API." />
              <ReadOnlyField label="Phone" value={me.phone ?? 'Not provided'} />
              <ReadOnlyField label="Role" value={me.role} hint="Assigned by the backend." />
              <ReadOnlyField label="Gym" value={me.gym?.name ?? 'None'} />
            </div>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex flex-col gap-1">
            <CardTitle>Account state</CardTitle>
            <CardDescription>Computed by the backend on every request.</CardDescription>
          </div>
        </CardHeader>
        <CardBody>
          <div className="flex flex-wrap items-start gap-8">
            <div className="flex flex-col gap-2">
              <span className="text-caption font-medium uppercase tracking-[0.08em] text-muted">
                Email
              </span>
              <VerifiedChip verified={me.email_verified} />
            </div>
            <div className="flex flex-col gap-2">
              <span className="text-caption font-medium uppercase tracking-[0.08em] text-muted">
                Gym subscription
              </span>
              <SubscriptionStatusChip status={me.subscription_status} />
            </div>
            {me.is_active_member !== null ? (
              <div className="flex flex-col gap-2">
                <span className="text-caption font-medium uppercase tracking-[0.08em] text-muted">
                  Membership
                </span>
                <ActiveChip active={me.is_active_member} />
              </div>
            ) : null}
          </div>

          {!me.email_verified ? (
            <Note className="mt-6">
              Your email is not verified. Enter the code from your registration email on the{' '}
              <TextLink to="/verify-email" withArrow={false}>
                verification page
              </TextLink>
              . The code cannot be resent — the API has no resend endpoint.
            </Note>
          ) : null}
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex flex-col gap-1">
            <CardTitle>Password</CardTitle>
            <CardDescription>Changed through the reset flow.</CardDescription>
          </div>
        </CardHeader>
        <CardBody>
          <p className="text-small text-muted">
            There is no authenticated password change. The backend emails a reset code, and
            completing the reset signs out every session for your account, including this one.
          </p>
          <div className="mt-4">
            <TextLink to="/password-reset">Change your password</TextLink>
          </div>
        </CardBody>
      </Card>
    </PageSections>
  );
}
