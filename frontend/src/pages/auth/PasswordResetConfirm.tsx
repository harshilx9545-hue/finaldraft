import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { confirmPasswordReset } from '@/api/auth';
import { AuthShell } from '@/components/layout/AppShell';
import { Card, CardBody } from '@/components/ui/Card';
import { TextField } from '@/components/ui/Field';
import { Button } from '@/components/ui/Button';
import { TextLink } from '@/components/ui/TextLink';
import { Note } from '@/components/ui/Note';
import { useToast } from '@/components/feedback/ToastProvider';
import { useFormFailure } from '@/lib/useFormFailure';

/**
 * The emailed value is a raw code, not a link, so this is a text field. A `token`
 * query parameter still seeds it — a user who pastes a whole URL should not have to
 * dig the code out — but the form never submits itself on load.
 *
 * On success the backend blacklists every refresh token for that user, so the local
 * session is dropped and the user is sent to sign in.
 */
const schema = z
  .object({
    token: z.string().trim().min(1, 'Paste the code from the email.'),
    password: z.string().min(10, 'At least 10 characters.'),
    password_confirm: z.string().min(1, 'Repeat the password.'),
  })
  .refine((values) => values.password === values.password_confirm, {
    path: ['password_confirm'],
    message: 'Passwords do not match.',
  });

type Values = z.infer<typeof schema>;
const FIELDS = ['token', 'password', 'password_confirm'] as const;

export default function PasswordResetConfirm(): JSX.Element {
  const navigate = useNavigate();
  const toast = useToast();
  const [params] = useSearchParams();

  const {
    register,
    handleSubmit,
    setError,
    resetField,
    formState: { errors, isSubmitting },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      token: params.get('token') ?? '',
      password: '',
      password_confirm: '',
    },
  });

  const failure = useFormFailure<Values>(setError);

  const onSubmit = async (values: Values): Promise<void> => {
    failure.clearFormError();
    try {
      await confirmPasswordReset({
        token: values.token.trim(),
        password: values.password,
        password_confirm: values.password_confirm,
      });
      toast.success('Your password has been changed. Please sign in with the new password.');
      navigate('/sign-in', { replace: true });
    } catch (error) {
      failure.handle(error, FIELDS);
      resetField('password');
      resetField('password_confirm');
    }
  };

  return (
    <AuthShell>
      <div className="mb-8 flex flex-col gap-3">
        <h1 className="font-display text-headline font-bold tracking-[-0.04em] text-ink">
          Set a new password
        </h1>
      </div>

      <Card>
        <CardBody className="pt-5">
          <form noValidate onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-5">
            {failure.formError !== null ? (
              <p role="alert" className="text-small text-error">
                {failure.formError}
              </p>
            ) : null}

            <TextField
              label="Reset code"
              required
              autoComplete="one-time-code"
              error={errors.token?.message}
              hint="From the email. Single use, valid for 60 minutes."
              {...register('token')}
            />
            <TextField
              label="New password"
              type="password"
              autoComplete="new-password"
              required
              error={errors.password?.message}
              hint="At least 10 characters."
              {...register('password')}
            />
            <TextField
              label="Repeat new password"
              type="password"
              autoComplete="new-password"
              required
              error={errors.password_confirm?.message}
              {...register('password_confirm')}
            />

            <Note>Completing this signs out every existing session for your account.</Note>

            <Button
              type="submit"
              variant="primary"
              size="lg"
              loading={isSubmitting}
              disabled={isSubmitting || failure.locked}
            >
              {failure.locked ? `Wait ${failure.lockedSeconds}s` : 'Change password'}
            </Button>

            <TextLink to="/sign-in">Back to sign in</TextLink>
          </form>
        </CardBody>
      </Card>
    </AuthShell>
  );
}
