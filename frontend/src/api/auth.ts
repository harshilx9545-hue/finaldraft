import { api, clearTokens, getTokens, setTokens } from './client';
import type {
  DetailResponse,
  EmailVerifiedResponse,
  LoginRequest,
  OwnerRegistrationRequest,
  OwnerRegistrationResponse,
  TokenPair,
} from './types';

/** POST /api/auth/login — `identifier` is an email OR an E.164 phone number. */
export async function login(payload: LoginRequest): Promise<TokenPair> {
  const pair = await api.post<TokenPair>('/auth/login', payload, { anonymous: true });
  setTokens(pair);
  return pair;
}

/**
 * POST /api/auth/register/owner
 *
 * Registration always produces an `owner`: the serializer declares no `role`
 * field and `register_owner` assigns it. There is deliberately no self-service
 * path that creates a trainer or a member.
 */
export async function registerOwner(
  payload: OwnerRegistrationRequest,
): Promise<OwnerRegistrationResponse> {
  const response = await api.post<OwnerRegistrationResponse>(
    '/auth/register/owner',
    payload,
    { anonymous: true },
  );
  setTokens(response.tokens);
  return response;
}

/**
 * POST /api/auth/logout — clears the session whatever the server answers.
 *
 * A failed logout must not trap the user in a session they asked to leave, and the
 * refresh token is discarded locally regardless.
 */
export async function logout(): Promise<void> {
  const tokens = getTokens();
  try {
    if (tokens !== null) {
      await api.post<null>('/auth/logout', { refresh: tokens.refresh });
    }
  } catch {
    /* Intentionally swallowed: the local session is cleared either way. */
  } finally {
    clearTokens();
  }
}

/** POST /api/auth/verify-email — the backend emails a raw code, not a link. */
export function verifyEmail(token: string): Promise<EmailVerifiedResponse> {
  return api.post<EmailVerifiedResponse>('/auth/verify-email', { token }, { anonymous: true });
}

/**
 * POST /api/auth/password-reset — always 202, with a fixed `detail` string that
 * is identical whether or not the address is registered. Do not add any UI that
 * distinguishes the two.
 */
export function requestPasswordReset(email: string): Promise<DetailResponse> {
  return api.post<DetailResponse>('/auth/password-reset', { email }, { anonymous: true });
}

/**
 * POST /api/auth/password-reset/confirm — on success the backend blacklists every
 * refresh token for that user, so the local session must be dropped too.
 */
export async function confirmPasswordReset(payload: {
  token: string;
  password: string;
  password_confirm: string;
}): Promise<DetailResponse> {
  const response = await api.post<DetailResponse>(
    '/auth/password-reset/confirm',
    payload,
    { anonymous: true },
  );
  clearTokens();
  return response;
}
