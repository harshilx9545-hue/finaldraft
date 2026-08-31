import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useSearchParams } from 'react-router-dom';
import { verifyEmail } from '@/api/auth';
import { AuthShell } from '@/components/layout/AppShell';
import { Card, CardBody } from '@/components/ui/Card';
import { TextField } from '@/components/ui/Field';
import { Button } from '@/components/ui/Button';
import { TextLink } from '@/components/ui/TextLink';
import { Note } from '@/components/ui/Note';
import { useFormFailure } from '@/lib/useFormFailure';

/**
 * Email verification takes the raw code from the registration email. Valid for 72
 * hours, single use.
 *
 * There is no resend control, because the backend registers no resend route. If the
 * code is lost there is nothing this surface can offer, and saying so is better than
 * a button that 404s.
 */
const schema = z.object({ token: z.string().trim().min(1, 'Paste the code from the email.') });
type Values = z.infer<typeof schema>;

export default function VerifyEmail(): JSX.Element {
  const [params] = useSearchParams();
  const [verified, setVerified] = useState(false);

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { token: params.get('token') ?? '' },
  });

  const failure = useFormFailure<Values>(setError);

  const onSubmit = async (values: Values): Promise<void> => {
    failure.clearFormError();
    try {
      const response = await verifyEmail(values.token.trim());
      setVerified(response.email_verified);
    } catch (error) {
      failure.handle(error, ['token']);
    }
  };

  return (
    <AuthShell>
      <div className="mb-8 flex flex-col gap-3">
        <h1 className="font-display text-headline font-bold tracking-[-0.04em] text-ink">
          Verify your email
        </h1>
      </div>

      <Card>
        <CardBody className="pt-5">
          {verified ? (
            <div className="flex flex-col gap-5">
              <p role="status" className="text-body text-ink">
                Your email address is verified.
              </p>
              <TextLink to="/overview">Continue</TextLink>
            </div>
          ) : (
            <form noValidate onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-5">
              {failure.formError !== null ? (
                <p role="alert" className="text-small text-error">
                  {failure.formError}
                </p>
              ) : null}

              <TextField
                label="Verification code"
                required
                autoComplete="one-time-code"
                error={errors.token?.message}
                hint="From the registration email. Single use, valid for 72 hours."
                {...register('token')}
              />

              <Note>
                The code cannot be resent — the API has no resend endpoint. If it is lost, the
                account still works; only the verified flag stays unset.
              </Note>

              <Button
                type="submit"
                variant="primary"
                size="lg"
                loading={isSubmitting}
                disabled={isSubmitting || failure.locked}
              >
                {failure.locked ? `Wait ${failure.lockedSeconds}s` : 'Verify'}
              </Button>

              <TextLink to="/sign-in">Back to sign in</TextLink>
            </form>
          )}
        </CardBody>
      </Card>
    </AuthShell>
  );
}
