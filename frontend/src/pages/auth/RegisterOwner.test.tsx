import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import RegisterOwner from './RegisterOwner';
import { SessionProvider } from '@/session/SessionProvider';
import { ToastProvider } from '@/components/feedback/ToastProvider';
import { clearTokens } from '@/api/client';

/**
 * Regression cover for the registration password field.
 *
 * The reported bug: type a password, submit, and the field comes back empty. The
 * cause was a blanket `resetField('password')` in the catch block, which fires on
 * ANY failure — including one caused by an entirely different field — and which,
 * because RHF's `resetField` defaults to `keepError: false`, also destroyed the
 * error message that had just been attached. The user was left with an empty box and
 * no explanation.
 *
 * These tests pin down the three things that matter: the password reaches the
 * request, a failure keeps what the user typed, and a field error stays visible.
 */

interface CapturedRequest {
  url: string;
  method: string;
  body: Record<string, unknown> | null;
}

const requests: CapturedRequest[] = [];

function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

/** Respond to the registration POST with whatever the test needs. */
function mockRegistration(responder: () => Response): void {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: string, init?: RequestInit) => {
      const url = String(input);
      requests.push({
        url,
        method: init?.method ?? 'GET',
        body: typeof init?.body === 'string' ? JSON.parse(init.body) : null,
      });

      if (url.endsWith('/auth/register/owner')) return Promise.resolve(responder());
      if (url.endsWith('/me')) {
        return Promise.resolve(
          jsonResponse(
            {
              id: 1,
              email: 'owner@example.com',
              first_name: '',
              last_name: '',
              phone: null,
              role: 'owner',
              email_verified: false,
              gym: null,
              subscription_status: 'trialing',
              is_active_member: null,
              current_period_end: null,
              member_profile_id: null,
            },
            200,
          ),
        );
      }
      return Promise.resolve(jsonResponse({}, 200));
    }),
  );
}

function renderPage(): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ToastProvider>
          <SessionProvider>
            <RegisterOwner />
          </SessionProvider>
        </ToastProvider>
      </BrowserRouter>
    </QueryClientProvider>,
  );
}

const PASSWORD = 'CorrectHorse99';

/** Fill only what the schema requires, so submission actually reaches the API. */
async function fillRequiredFields(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await user.type(screen.getByLabelText(/^Email/), 'owner@example.com');
  await user.type(screen.getByLabelText(/^Password/), PASSWORD);
  await user.type(screen.getByLabelText(/^Repeat password/), PASSWORD);
  await user.type(screen.getByLabelText(/^Business name/), 'Iron Pit');
  await user.type(screen.getByLabelText(/^Gym contact phone/), '+919876543210');
}

function passwordInput(): HTMLInputElement {
  return screen.getByLabelText(/^Password/) as HTMLInputElement;
}

function confirmInput(): HTMLInputElement {
  return screen.getByLabelText(/^Repeat password/) as HTMLInputElement;
}

beforeEach(() => {
  requests.length = 0;
  clearTokens();
  window.sessionStorage.clear();
});

describe('the password reaches the API', () => {
  it('includes password and password_confirm in the registration request', async () => {
    const user = userEvent.setup();
    mockRegistration(() =>
      jsonResponse(
        {
          gym: { id: 1, name: 'Iron Pit', slug: 'iron-pit' },
          user: { id: 1, email: 'owner@example.com', role: 'owner', email_verified: false },
          tokens: { access: 'a', refresh: 'r' },
        },
        201,
      ),
    );

    renderPage();
    await fillRequiredFields(user);
    await user.click(screen.getByRole('button', { name: /create gym and sign in/i }));

    await waitFor(() => {
      expect(requests.some((r) => r.url.endsWith('/auth/register/owner'))).toBe(true);
    });

    const registration = requests.find((r) => r.url.endsWith('/auth/register/owner'));
    expect(registration?.method).toBe('POST');
    // The whole point: the password the user typed is in the payload, unmodified.
    expect(registration?.body?.password).toBe(PASSWORD);
    expect(registration?.body?.password_confirm).toBe(PASSWORD);
    expect(registration?.body?.email).toBe('owner@example.com');
    expect(registration?.body?.business_name).toBe('Iron Pit');
    expect(registration?.body?.contact_phone).toBe('+919876543210');
  });

  it('does not send the password anywhere before submission', async () => {
    const user = userEvent.setup();
    mockRegistration(() => jsonResponse({}, 201));

    renderPage();
    await fillRequiredFields(user);

    // Typing alone must not produce a request.
    expect(requests.filter((r) => r.method === 'POST')).toHaveLength(0);
  });
});

describe('a failure caused by another field', () => {
  it('keeps the password the user typed', async () => {
    const user = userEvent.setup();
    // The realistic case: the email is already registered. Nothing whatsoever is
    // wrong with the password, so wiping it is pure user punishment.
    mockRegistration(() =>
      jsonResponse(
        {
          error: {
            code: 'VALIDATION_ERROR',
            message: 'An account with this email already exists.',
            details: { field: 'email' },
          },
        },
        400,
      ),
    );

    renderPage();
    await fillRequiredFields(user);
    await user.click(screen.getByRole('button', { name: /create gym and sign in/i }));

    await waitFor(() => {
      expect(screen.getByText(/an account with this email already exists/i)).toBeInTheDocument();
    });

    expect(passwordInput().value).toBe(PASSWORD);
    expect(confirmInput().value).toBe(PASSWORD);
  });

  it('keeps every other entered value too', async () => {
    const user = userEvent.setup();
    mockRegistration(() =>
      jsonResponse(
        {
          error: {
            code: 'VALIDATION_ERROR',
            message: 'An account with this email already exists.',
            details: { field: 'email' },
          },
        },
        400,
      ),
    );

    renderPage();
    await fillRequiredFields(user);
    await user.type(screen.getByLabelText(/^First name/), 'Asha');
    await user.click(screen.getByRole('button', { name: /create gym and sign in/i }));

    await waitFor(() => {
      expect(screen.getByText(/an account with this email already exists/i)).toBeInTheDocument();
    });

    expect((screen.getByLabelText(/^First name/) as HTMLInputElement).value).toBe('Asha');
    expect((screen.getByLabelText(/^Business name/) as HTMLInputElement).value).toBe('Iron Pit');
    expect((screen.getByLabelText(/^Gym contact phone/) as HTMLInputElement).value).toBe(
      '+919876543210',
    );
  });
});

describe('a failure caused by the password itself', () => {
  it('shows the reason and does not silently empty the field', async () => {
    const user = userEvent.setup();
    // Django's validators reject far more than a length rule: common passwords,
    // all-numeric ones, and any too similar to the email. The client cannot predict
    // these, so this response is routine — and the reason must survive on screen.
    mockRegistration(() =>
      jsonResponse(
        {
          error: {
            code: 'VALIDATION_ERROR',
            message: 'This password is too common.',
            details: { field: 'password' },
          },
        },
        400,
      ),
    );

    renderPage();
    await fillRequiredFields(user);
    await user.click(screen.getByRole('button', { name: /create gym and sign in/i }));

    // The error the backend gave must be visible, attached to the field.
    await waitFor(() => {
      expect(screen.getByText(/this password is too common/i)).toBeInTheDocument();
    });

    expect(passwordInput()).toHaveAttribute('aria-invalid', 'true');
    // And the value stays, so the user can edit rather than retype from scratch.
    expect(passwordInput().value).toBe(PASSWORD);
  });
});

describe('throttling', () => {
  it('keeps the password when the request is rate limited', async () => {
    const user = userEvent.setup();
    mockRegistration(() =>
      jsonResponse(
        {
          error: {
            code: 'RATE_LIMITED',
            message: 'Too many attempts.',
            details: { retry_after_seconds: 30 },
          },
        },
        429,
      ),
    );

    renderPage();
    await fillRequiredFields(user);
    await user.click(screen.getByRole('button', { name: /create gym and sign in/i }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /wait 30s/i })).toBeInTheDocument();
    });

    // Nothing was wrong with what they typed; a throttle is about timing.
    expect(passwordInput().value).toBe(PASSWORD);
  });
});

describe('client-side validation', () => {
  it('blocks submission and sends nothing when the passwords differ', async () => {
    const user = userEvent.setup();
    mockRegistration(() => jsonResponse({}, 201));

    renderPage();
    await user.type(screen.getByLabelText(/^Email/), 'owner@example.com');
    await user.type(screen.getByLabelText(/^Password/), PASSWORD);
    await user.type(screen.getByLabelText(/^Repeat password/), 'SomethingElse99');
    await user.type(screen.getByLabelText(/^Business name/), 'Iron Pit');
    await user.type(screen.getByLabelText(/^Gym contact phone/), '+919876543210');
    await user.click(screen.getByRole('button', { name: /create gym and sign in/i }));

    await waitFor(() => {
      expect(screen.getByText(/passwords do not match/i)).toBeInTheDocument();
    });

    expect(requests.filter((r) => r.url.endsWith('/auth/register/owner'))).toHaveLength(0);
    // A local validation failure must not clear the fields either.
    expect(passwordInput().value).toBe(PASSWORD);
  });
});
