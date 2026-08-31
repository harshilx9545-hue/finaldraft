import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useNavigate } from 'react-router-dom';
import { registerOwner } from '@/api/auth';
import type { OwnerRegistrationRequest } from '@/api/types';
import { useSession } from '@/session/SessionProvider';
import { AuthShell } from '@/components/layout/AppShell';
import { Card, CardBody } from '@/components/ui/Card';
import { TextField } from '@/components/ui/Field';
import { Button } from '@/components/ui/Button';
import { TextLink } from '@/components/ui/TextLink';
import { Note } from '@/components/ui/Note';
import { useFormFailure } from '@/lib/useFormFailure';

/**
 * Owner registration. This is the ONLY self-service sign-up the backend has:
 * `OwnerRegistrationSerializer` declares no `role` field and `register_owner`
 * always assigns `owner`. Trainers are created by an owner, members by an owner or
 * a trainer — neither can register themselves, so no such form exists.
 *
 * Validation mirrors the backend: password at least 10 characters (Django's
 * configured MinimumLengthValidator), the two passwords equal, phone numbers E.164
 * at 16 characters or fewer, GSTIN exactly 15 characters in the documented shape.
 */

const E164 = /^\+[1-9]\d{7,14}$/;
const GSTIN = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/;

const optionalPhone = z
  .string()
  .trim()
  .max(16, 'At most 16 characters.')
  .refine((value) => value === '' || E164.test(value), {
    message: 'Use international format, such as +919876543210.',
  });

const schema = z
  .object({
    email: z.string().trim().email('Enter a valid email address.'),
    password: z.string().min(10, 'At least 10 characters.'),
    password_confirm: z.string().min(1, 'Repeat the password.'),
    business_name: z.string().trim().min(1, 'Enter your business name.').max(200),
    contact_phone: z
      .string()
      .trim()
      .min(1, 'A contact phone number is required.')
      .max(16, 'At most 16 characters.')
      .regex(E164, 'Use international format, such as +919876543210.'),
    first_name: z.string().trim().max(150).optional(),
    last_name: z.string().trim().max(150).optional(),
    phone: optionalPhone.optional(),
    gym_name: z.string().trim().max(200).optional(),
    contact_email: z
      .string()
      .trim()
      .refine((value) => value === '' || z.string().email().safeParse(value).success, {
        message: 'Enter a valid email address.',
      })
      .optional(),
    gstin: z
      .string()
      .trim()
      .refine((value) => value === '' || GSTIN.test(value.toUpperCase()), {
        message: 'A GSTIN is 15 characters, such as 22AAAAA0000A1Z5.',
      })
      .optional(),
  })
  .refine((values) => values.password === values.password_confirm, {
    path: ['password_confirm'],
    message: 'Passwords do not match.',
  });

type Values = z.infer<typeof schema>;

const FIELDS = [
  'email',
  'password',
  'password_confirm',
  'business_name',
  'contact_phone',
  'first_name',
  'last_name',
  'phone',
  'gym_name',
  'contact_email',
  'gstin',
] as const;

/**
 * Build the request body.
 *
 * Optional fields are omitted when empty rather than sent as "", so the backend
 * applies its own defaults instead of storing blanks. The two password values are
 * passed through untouched — no trimming, because the backend's serializer declares
 * `trim_whitespace=False` on both and a leading or trailing space is a legitimate
 * part of a password.
 */
function buildPayload(values: Values): OwnerRegistrationRequest {
  const payload: OwnerRegistrationRequest = {
    email: values.email.trim(),
    password: values.password,
    password_confirm: values.password_confirm,
    business_name: values.business_name.trim(),
    contact_phone: values.contact_phone.trim(),
  };

  const first = values.first_name?.trim();
  if (first) payload.first_name = first;

  const last = values.last_name?.trim();
  if (last) payload.last_name = last;

  const phone = values.phone?.trim();
  if (phone) payload.phone = phone;

  const gymName = values.gym_name?.trim();
  if (gymName) payload.gym_name = gymName;

  const contactEmail = values.contact_email?.trim();
  if (contactEmail) payload.contact_email = contactEmail;

  const gstin = values.gstin?.trim();
  if (gstin) payload.gstin = gstin.toUpperCase();

  return payload;
}

export default function RegisterOwner(): JSX.Element {
  const navigate = useNavigate();
  const { establish } = useSession();

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    // Every field is declared, so the form is fully controlled by RHF from the first
    // render and there is no undefined-to-string transition on any input.
    defaultValues: {
      email: '',
      password: '',
      password_confirm: '',
      business_name: '',
      contact_phone: '',
      first_name: '',
      last_name: '',
      phone: '',
      gym_name: '',
      contact_email: '',
      gstin: '',
    },
  });

  const failure = useFormFailure<Values>(setError);

  const onSubmit = async (values: Values): Promise<void> => {
    failure.clearFormError();

    // Tracks whether the account was actually created, so a failure in the
    // follow-up /api/me call is not mistaken for a failed registration.
    let accountCreated = false;

    try {
      await registerOwner(buildPayload(values));
      accountCreated = true;
      await establish();
    } catch (error) {
      if (accountCreated) {
        // The owner and gym exist; only resolving the session afterwards failed.
        // Re-submitting this form would now collide with the email just registered,
        // so leaving the user on it would trap them in an unwinnable retry.
        // SessionProvider has already recorded the reason, which the sign-in surface
        // displays.
        navigate('/sign-in', { replace: true });
        return;
      }

      // Registration itself failed. Keep every entered value, including both
      // passwords: the cause is frequently another field entirely (a taken email,
      // a taken phone) or a throttle, and clearing the password would punish the
      // user for something unrelated. Where the backend named a field,
      // failure.handle has attached the message to it — nothing here may clear that
      // error, which is exactly what the previous resetField calls did.
      failure.handle(error, FIELDS);
      return;
    }

    navigate('/overview', { replace: true });
  };

  return (
    <AuthShell>
      <div className="mb-8 flex flex-col gap-3">
        <h1 className="font-display text-headline font-bold tracking-[-0.04em] text-ink">
          Register your gym
        </h1>
        <p className="text-body text-muted">
          This creates an owner account and your gym in one step.
        </p>
      </div>

      <Card>
        <CardBody className="pt-5">
          <form noValidate onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-5">
            {failure.formError !== null ? (
              <p role="alert" className="text-small text-error">
                {failure.formError}
              </p>
            ) : null}

            <fieldset className="m-0 flex flex-col gap-5 border-0 p-0">
              <legend className="mb-1 text-caption font-medium uppercase tracking-[0.08em] text-muted">
                Your account
              </legend>

              <TextField
                label="Email"
                type="email"
                autoComplete="email"
                required
                error={errors.email?.message}
                {...register('email')}
              />
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
                label="Your phone number"
                error={errors.phone?.message}
                hint="Optional. International format, such as +919876543210."
                {...register('phone')}
              />
              <div className="grid gap-5 sm:grid-cols-2">
                <TextField
                  label="Password"
                  type="password"
                  autoComplete="new-password"
                  required
                  error={errors.password?.message}
                  hint="At least 10 characters."
                  {...register('password')}
                />
                <TextField
                  label="Repeat password"
                  type="password"
                  autoComplete="new-password"
                  required
                  error={errors.password_confirm?.message}
                  {...register('password_confirm')}
                />
              </div>
            </fieldset>

            <fieldset className="m-0 flex flex-col gap-5 border-0 p-0">
              <legend className="mb-1 text-caption font-medium uppercase tracking-[0.08em] text-muted">
                Your gym
              </legend>

              <TextField
                label="Business name"
                required
                error={errors.business_name?.message}
                {...register('business_name')}
              />
              <TextField
                label="Gym name"
                error={errors.gym_name?.message}
                hint="Optional. Defaults to the business name."
                {...register('gym_name')}
              />
              <TextField
                label="Gym contact phone"
                required
                error={errors.contact_phone?.message}
                hint="International format, such as +919876543210."
                {...register('contact_phone')}
              />
              <TextField
                label="Gym contact email"
                type="email"
                error={errors.contact_email?.message}
                hint="Optional."
                {...register('contact_email')}
              />
              <TextField
                label="GSTIN"
                error={errors.gstin?.message}
                hint="Optional. Adding one makes the backend compute GST on invoices issued afterwards."
                {...register('gstin')}
              />
            </fieldset>

            <Note>
              Your gym timezone is set to Asia/Kolkata and can be changed afterwards on the Gym
              page. All membership and billing dates are evaluated in that timezone.
            </Note>

            <Button
              type="submit"
              variant="primary"
              size="lg"
              loading={isSubmitting}
              disabled={isSubmitting || failure.locked}
            >
              {failure.locked ? `Wait ${failure.lockedSeconds}s` : 'Create gym and sign in'}
            </Button>

            <TextLink to="/sign-in">Already have an account</TextLink>
          </form>
        </CardBody>
      </Card>
    </AuthShell>
  );
}
