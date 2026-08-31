import { ApiError, NetworkFailure, parseEnvelope } from '@/lib/errors';

/**
 * The single HTTP boundary to the backend.
 *
 * Two behaviours here are dictated by the backend and are easy to get wrong:
 *
 * 1. Refresh tokens are SINGLE USE. `ROTATE_REFRESH_TOKENS` and
 *    `BLACKLIST_AFTER_ROTATION` are both true, so presenting one twice loses the
 *    session. Every 401 TOKEN_EXPIRED therefore funnels through one shared
 *    in-flight refresh promise; a second refresh is never issued concurrently.
 * 2. No list endpoint accepts anything but `page`. No filter backend is registered
 *    and no view reads `query_params`. `buildUrl` refuses any other parameter so a
 *    fake search or sort cannot be introduced by accident later.
 */

const RAW_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').trim();
export const API_BASE = (RAW_BASE.length > 0 ? RAW_BASE : 'http://localhost:8000/api').replace(
  /\/+$/,
  '',
);

const REQUEST_TIMEOUT_MS = 30_000;

/** The only query parameter any backend list route honours. */
const ALLOWED_QUERY_PARAMS = new Set(['page']);

/** Routes that must NOT carry an Authorization header. */
const UNAUTHENTICATED_PATHS = new Set([
  '/auth/register/owner',
  '/auth/login',
  '/auth/refresh',
  '/auth/verify-email',
  '/auth/password-reset',
  '/auth/password-reset/confirm',
]);

export type HttpMethod = 'GET' | 'POST' | 'PATCH';

export interface TokenPair {
  access: string;
  refresh: string;
}

/* ------------------------------------------------------------------ session */

const ACCESS_KEY = 'mk00.access';
const REFRESH_KEY = 'mk00.refresh';

/**
 * Tokens live in sessionStorage, scoped to the tab and dropped when it closes.
 * Nothing else from a backend response is ever persisted — no /api/me payload and
 * no resource data — so a reload restores the session without leaving cached
 * tenant data on disk.
 */
let access: string | null = null;
let refresh: string | null = null;

function readStorage(key: string): string | null {
  try {
    return window.sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string | null): void {
  try {
    if (value === null) window.sessionStorage.removeItem(key);
    else window.sessionStorage.setItem(key, value);
  } catch {
    /* Private mode or storage disabled: tokens stay in memory for this page. */
  }
}

export function loadTokensFromStorage(): void {
  access = readStorage(ACCESS_KEY);
  refresh = readStorage(REFRESH_KEY);
}

export function getTokens(): TokenPair | null {
  if (access === null || refresh === null) return null;
  return { access, refresh };
}

export function hasSession(): boolean {
  return access !== null;
}

export function setTokens(pair: TokenPair): void {
  access = pair.access;
  refresh = pair.refresh;
  writeStorage(ACCESS_KEY, pair.access);
  writeStorage(REFRESH_KEY, pair.refresh);
}

export function clearTokens(): void {
  access = null;
  refresh = null;
  writeStorage(ACCESS_KEY, null);
  writeStorage(REFRESH_KEY, null);
}

/* Session-ended fan-out, so the React tree can drop caches and route to sign-in
   without the client importing anything from the UI layer. */
type SessionEndedListener = () => void;
const sessionEndedListeners = new Set<SessionEndedListener>();

export function onSessionEnded(listener: SessionEndedListener): () => void {
  sessionEndedListeners.add(listener);
  return () => sessionEndedListeners.delete(listener);
}

let sessionEndedAnnounced = false;

function endSession(): void {
  clearTokens();
  // Announce once however many requests failed together, so the user sees one
  // redirect and one message rather than one per in-flight request.
  if (sessionEndedAnnounced) return;
  sessionEndedAnnounced = true;
  for (const listener of sessionEndedListeners) listener();
  window.setTimeout(() => {
    sessionEndedAnnounced = false;
  }, 0);
}

/* ---------------------------------------------------------------------- url */

export function buildUrl(path: string, query?: Record<string, string | number | undefined>): string {
  if (!path.startsWith('/')) {
    throw new Error(`API path must start with "/": ${path}`);
  }

  let url = `${API_BASE}${path}`;

  if (query) {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined) continue;
      if (!ALLOWED_QUERY_PARAMS.has(key)) {
        // Guard rail, not decoration: the backend registers no filter backend, so
        // a search/sort/filter parameter would be silently ignored and the UI
        // would present a partial result as if the server had produced it.
        throw new Error(
          `Query parameter "${key}" is not supported by the backend. Only "page" is accepted.`,
        );
      }
      search.set(key, String(value));
    }
    const qs = search.toString();
    if (qs.length > 0) url += `?${qs}`;
  }

  return url;
}

/** Extract the `page` value from a DRF `next`/`previous` URL. */
export function pageFromUrl(url: string | null): number | null {
  if (url === null) return null;
  try {
    const value = new URL(url, API_BASE).searchParams.get('page');
    if (value === null) return 1; // DRF omits page=1 on `previous`
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/* ------------------------------------------------------------------ refresh */

let refreshInFlight: Promise<boolean> | null = null;

async function performRefresh(): Promise<boolean> {
  const token = refresh;
  if (token === null) return false;

  try {
    const response = await rawFetch('POST', '/auth/refresh', { refresh: token }, null);
    if (!response.ok) return false;
    const body = (await response.json()) as Partial<TokenPair>;
    if (typeof body.access !== 'string' || typeof body.refresh !== 'string') return false;
    setTokens({ access: body.access, refresh: body.refresh });
    return true;
  } catch {
    return false;
  }
}

/**
 * At most one refresh at a time. Callers await the same promise, so five requests
 * that all expire together consume exactly one refresh token.
 */
function refreshOnce(): Promise<boolean> {
  if (refreshInFlight === null) {
    refreshInFlight = performRefresh().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

/* ----------------------------------------------------------------- requests */

async function rawFetch(
  method: HttpMethod,
  path: string,
  body: unknown,
  bearer: string | null,
  signal?: AbortSignal,
): Promise<Response> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (body !== undefined && body !== null) headers['Content-Type'] = 'application/json';
  if (bearer !== null) headers.Authorization = `Bearer ${bearer}`;

  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  if (signal) signal.addEventListener('abort', () => controller.abort(), { once: true });

  try {
    return await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: body === undefined || body === null ? undefined : JSON.stringify(body),
      signal: controller.signal,
      // CORS_ALLOW_CREDENTIALS is false on the backend; sending credentials would
      // make the browser reject the response.
      credentials: 'omit',
      mode: 'cors',
    });
  } finally {
    window.clearTimeout(timeout);
  }
}

export interface RequestOptions {
  query?: Record<string, string | number | undefined>;
  body?: unknown;
  signal?: AbortSignal;
  /** Set for the six auth routes that must not carry a bearer token. */
  anonymous?: boolean;
}

async function parseBody(response: Response): Promise<unknown> {
  if (response.status === 204) return null;
  const text = await response.text();
  if (text.length === 0) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return null;
  }
}

export async function request<T>(
  method: HttpMethod,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const anonymous = options.anonymous === true || UNAUTHENTICATED_PATHS.has(path);
  // Validate the query shape even though rawFetch takes the path, so an
  // unsupported parameter throws before a request goes out.
  const url = buildUrl(path, options.query);
  const pathWithQuery = url.slice(API_BASE.length);

  const send = async (): Promise<Response> =>
    rawFetch(method, pathWithQuery, options.body, anonymous ? null : access, options.signal);

  let response: Response;
  try {
    response = await send();
  } catch {
    throw new NetworkFailure();
  }

  if (response.status === 401 && !anonymous) {
    const envelope = parseEnvelope(await parseBody(response));
    const code = envelope?.code ?? null;

    if (code === 'TOKEN_EXPIRED' && refresh !== null) {
      const refreshed = await refreshOnce();
      if (!refreshed) {
        endSession();
        throw new ApiError(401, envelope);
      }
      // Exactly one retry, with the rotated access token.
      let retried: Response;
      try {
        retried = await send();
      } catch {
        throw new NetworkFailure();
      }
      if (retried.status === 401) {
        endSession();
        throw new ApiError(401, parseEnvelope(await parseBody(retried)));
      }
      return finish<T>(retried);
    }

    // TOKEN_INVALID, TOKEN_CONSUMED, NOT_AUTHENTICATED, or TOKEN_EXPIRED with no
    // refresh token: no refresh attempt, session is over.
    endSession();
    throw new ApiError(401, envelope);
  }

  return finish<T>(response);
}

async function finish<T>(response: Response): Promise<T> {
  const body = await parseBody(response);
  if (!response.ok) {
    throw new ApiError(response.status, parseEnvelope(body));
  }
  return body as T;
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) => request<T>('GET', path, options),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>('POST', path, { ...options, body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>('PATCH', path, { ...options, body }),
};
