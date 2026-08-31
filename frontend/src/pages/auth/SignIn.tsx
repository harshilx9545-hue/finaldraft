import { useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useNavigate } from 'react-router-dom';
import { login } from '@/api/auth';
import { useSession } from '@/session/SessionProvider';
import { AuthShell } from '@/components/layout/AppShell';
import { Card, CardBody } from '@/components/ui/Card';
import { TextField } from '@/components/ui/Field';
import { Button } from '@/components/ui/Button';
import { TextLink } from '@/components/ui/TextLink';
import { useFormFailure } from '@/lib/useFormFailure';

/**
 * `identifier` accepts an email address OR an E.164 phone number — the backend
 * resolves either. So there is no client-side format check beyond "not empty";
 * guessing which one the user meant and rejecting it would be worse than letting
 * the server decide.
 */
const schema = z.object({
  identifier: z.string().trim().min(1, 'Enter your email address or phone number.'),
  password: z.string().min(1, 'Enter your password.'),
});

type Values = z.infer<typeof schema>;

const FIELDS = ['identifier', 'password'] as const;

export default function SignIn(): JSX.Element {
  const navigate = useNavigate();
  const { establish, endedMessage, clearEndedMessage } = useSession();

  const {
    register,
    handleSubmit,
    setError,
    resetField,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { identifier: '', password: '' } });

  const failure = useFormFailure<Values>(setError);

  // The involuntary sign-out message belongs to this surface once, not forever.
  useEffect(() => () => clearEndedMessage(), [clearEndedMessage]);

  const onSubmit = async (values: Values): Promise<void> => {
    failure.clearFormError();
    try {
      await login({ identifier: values.identifier.trim(), password: values.password });
      await establish();
      navigate('/overview', { replace: true });
    } catch (error) {
      failure.handle(error, FIELDS);
      // The identifier is kept so the user can fix a typo. The password is discarded,
      // which is the convention for a sign-in form — but `keepError: true` matters:
      // resetField defaults to clearing the field's error too, which would delete the
      // message failure.handle just attached and leave an empty box with no reason.
      resetField('password', { keepError: true });
    }
  };

  return (
    <AuthShell>
      <div className="mb-8 flex flex-col gap-3">
        <h1 className="font-display text-headline font-bold tracking-[-0.04em] text-ink">
          Sign in
        </h1>
        <p className="text-body text-muted">Manage your gym, members and invoices.</p>
      </div>

      {endedMessage !== null ? (
        <p
          role="status"
          className="mb-6 rounded-panel border border-warning bg-surface px-4 py-3 text-small text-ink"
        >
          {endedMessage}
        </p>
      ) : null}

      <Card>
        <CardBody className="pt-5">
          <form noValidate onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-5">
            {failure.formError !== null ? (
              <p role="alert" className="text-small text-error">
                {failure.formError}
              </p>
            ) : null}

            <TextField
              label="Email or phone number"
              autoComplete="username"
              required
              error={errors.identifier?.message}
              hint="Either works. A phone number must be in international format, such as +919876543210."
              {...register('identifier')}
            />

            <TextField
              label="Password"
              type="password"
              autoComplete="current-password"
              required
              error={errors.password?.message}
              {...register('password')}
            />

            <div className="flex flex-col gap-3">
              <Button
                type="submit"
                variant="primary"
                size="lg"
                loading={isSubmitting}
                disabled={isSubmitting || failure.locked}
              >
                {failure.locked ? `Wait ${failure.lockedSeconds}s` : 'Sign in'}
              </Button>

              <div className="flex flex-wrap items-center justify-between gap-3">
                <TextLink to="/password-reset">Forgot your password</TextLink>
                <TextLink to="/register">Register a gym</TextLink>
              </div>
            </div>
          </form>
        </CardBody>
      </Card>
    </AuthShell>
  );
}
