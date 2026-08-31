import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { requestPasswordReset } from '@/api/auth';
import { AuthShell } from '@/components/layout/AppShell';
import { Card, CardBody } from '@/components/ui/Card';
import { TextField } from '@/components/ui/Field';
import { Button } from '@/components/ui/Button';
import { TextLink } from '@/components/ui/TextLink';
import { Note } from '@/components/ui/Note';
import { useFormFailure } from '@/lib/useFormFailure';

/**
 * The backend answers 202 with a fixed `detail` string whether or not the address
 * is registered. That is deliberate — it stops the form being used to enumerate
 * accounts — so this surface shows the same message either way and offers no clue
 * about which happened.
 */
const schema = z.object({ email: z.string().trim().email('Enter a valid email address.') });
type Values = z.infer<typeof schema>;

export default function PasswordResetRequest(): JSX.Element {
  const [sent, setSent] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { email: '' } });
  const failure = useFormFailure<Values>(setError);

  const onSubmit = async (values: Values): Promise<void> => {
    failure.clearFormError();
    try {
      const response = await requestPasswordReset(values.email.trim());
      setSent(response.detail);
    } catch (error) {
      failure.handle(error, ['email']);
    }
  };

  return (
    <AuthShell>
      <div className="mb-8 flex flex-col gap-3">
        <h1 className="font-display text-headline font-bold tracking-[-0.04em] text-ink">
          Reset your password
        </h1>
        <p className="text-body text-muted">
          We will email a reset code. It is a code, not a link, and it is valid for 60 minutes.
        </p>
      </div>

      <Card>
        <CardBody className="pt-5">
          {sent !== null ? (
            <div className="flex flex-col gap-5">
              <p role="status" className="text-body text-ink">
                {sent}
              </p>
              <TextLink to="/password-reset/confirm">Enter the code</TextLink>
            </div>
          ) : (
            <form noValidate onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-5">
              {failure.formError !== null ? (
                <p role="alert" className="text-small text-error">
                  {failure.formError}
                </p>
              ) : null}

              <TextField
                label="Email"
                type="email"
                autoComplete="email"
                required
                error={errors.email?.message}
                {...register('email')}
              />

              <Note>
                A member added by a gym owner has no password yet. This is the flow that sets one.
              </Note>

              <Button
                type="submit"
                variant="primary"
                size="lg"
                loading={isSubmitting}
                disabled={isSubmitting || failure.locked}
              >
                {failure.locked ? `Wait ${failure.lockedSeconds}s` : 'Email me a code'}
              </Button>

              <div className="flex flex-wrap items-center justify-between gap-3">
                <TextLink to="/sign-in">Back to sign in</TextLink>
                <TextLink to="/password-reset/confirm">I already have a code</TextLink>
              </div>
            </form>
          )}
        </CardBody>
      </Card>
    </AuthShell>
  );
}
