import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api, clearTokens, getTokens, onSessionEnded, setTokens } from './client';
import { ApiError } from '@/lib/errors';

/**
 * Token refresh.
 *
 * The backend sets ROTATE_REFRESH_TOKENS and BLACKLIST_AFTER_ROTATION, so a refresh
 * token works exactly once. Two concurrent refreshes therefore destroy the session:
 * the second presents a blacklisted token. Single-flight is not an optimisation
 * here, it is a correctness requirement, which is why it is tested.
 */

function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const expired = { error: { code: 'TOKEN_EXPIRED', message: 'Token expired.' } };

beforeEach(() => {
  clearTokens();
  setTokens({ access: 'stale-access', refresh: 'refresh-1' });
});

describe('a single expired request', () => {
  it('refreshes once, stores the rotated pair, and retries the original once', async () => {
    let refreshCalls = 0;
    const seen: string[] = [];

    vi.stubGlobal(
      'fetch',
      vi.fn((input: string, init?: RequestInit) => {
        const url = String(input);
        seen.push(url);

        if (url.endsWith('/auth/refresh')) {
          refreshCalls += 1;
          return Promise.resolve(
            jsonResponse({ access: 'fresh-access', refresh: 'refresh-2' }, 200),
          );
        }

        const bearer = (init?.headers as Record<string, string>).Authorization;
        if (bearer === 'Bearer stale-access') return Promise.resolve(jsonResponse(expired, 401));
        return Promise.resolve(jsonResponse({ id: 1 }, 200));
      }),
    );

    const result = await api.get<{ id: number }>('/me');

    expect(result).toEqual({ id: 1 });
    expect(refreshCalls).toBe(1);
    expect(getTokens()).toEqual({ access: 'fresh-access', refresh: 'refresh-2' });
    // Original, refresh, retry — and no more.
    expect(seen.filter((url) => url.endsWith('/me'))).toHaveLength(2);
  });
});

describe('concurrent expired requests', () => {
  it('consumes exactly one refresh token for five simultaneous 401s', async () => {
    let refreshCalls = 0;
    const refreshBodies: string[] = [];

    vi.stubGlobal(
      'fetch',
      vi.fn((input: string, init?: RequestInit) => {
        const url = String(input);

        if (url.endsWith('/auth/refresh')) {
          refreshCalls += 1;
          refreshBodies.push(String(init?.body));
          // Deliberately slow, so all five callers are waiting at once.
          return new Promise<Response>((resolve) => {
            setTimeout(
              () => resolve(jsonResponse({ access: 'fresh-access', refresh: 'refresh-2' }, 200)),
              20,
            );
          });
        }

        const bearer = (init?.headers as Record<string, string>).Authorization;
        if (bearer === 'Bearer stale-access') return Promise.resolve(jsonResponse(expired, 401));
        return Promise.resolve(jsonResponse({ ok: true }, 200));
      }),
    );

    const results = await Promise.all([
      api.get('/me'),
      api.get('/gym'),
      api.get('/members', { query: { page: 1 } }),
      api.get('/invoices', { query: { page: 1 } }),
      api.get('/membership-plans', { query: { page: 1 } }),
    ]);

    expect(results).toHaveLength(5);
    // The whole point: one refresh, not five.
    expect(refreshCalls).toBe(1);
    expect(refreshBodies).toEqual([JSON.stringify({ refresh: 'refresh-1' })]);
  });
});

describe('a failed refresh', () => {
  it('clears the session, announces it once, and does not try again', async () => {
    let refreshCalls = 0;
    let announcements = 0;
    const stop = onSessionEnded(() => {
      announcements += 1;
    });

    vi.stubGlobal(
      'fetch',
      vi.fn((input: string) => {
        const url = String(input);
        if (url.endsWith('/auth/refresh')) {
          refreshCalls += 1;
          return Promise.resolve(
            jsonResponse({ error: { code: 'TOKEN_INVALID', message: 'Blacklisted.' } }, 401),
          );
        }
        return Promise.resolve(jsonResponse(expired, 401));
      }),
    );

    await expect(api.get('/me')).rejects.toBeInstanceOf(ApiError);

    expect(refreshCalls).toBe(1);
    expect(getTokens()).toBeNull();
    expect(announcements).toBe(1);
    stop();
  });
});

describe('a 401 that is not an expiry', () => {
  it('ends the session without attempting a refresh at all', async () => {
    let refreshCalls = 0;

    vi.stubGlobal(
      'fetch',
      vi.fn((input: string) => {
        if (String(input).endsWith('/auth/refresh')) {
          refreshCalls += 1;
          return Promise.resolve(jsonResponse({ access: 'a', refresh: 'b' }, 200));
        }
        return Promise.resolve(
          jsonResponse({ error: { code: 'TOKEN_INVALID', message: 'Malformed.' } }, 401),
        );
      }),
    );

    await expect(api.get('/me')).rejects.toBeInstanceOf(ApiError);
    expect(refreshCalls).toBe(0);
    expect(getTokens()).toBeNull();
  });
});
