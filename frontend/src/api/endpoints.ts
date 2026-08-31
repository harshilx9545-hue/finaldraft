/**
 * The complete inventory of backend routes this client is allowed to call.
 *
 * Taken from `core/urls.py`. Twenty-six role-reachable method-and-path pairs
 * exist, plus the Razorpay webhook, which is authenticated by an HMAC signature
 * and is not a frontend surface. There is no DELETE method on any route.
 *
 * A test asserts that every path the API modules can construct appears here, so
 * adding a call to a route that does not exist fails the build rather than 404ing
 * in front of a user.
 */

import type { Role } from './types';

export interface EndpointSpec {
  method: 'GET' | 'POST' | 'PATCH';
  /** `{id}` marks a path parameter. */
  path: string;
  /** Empty set means anonymous. */
  roles: readonly Role[];
  anonymous?: boolean;
  paginated?: boolean;
}

const ALL: readonly Role[] = ['owner', 'trainer', 'member'];

export const ENDPOINTS: readonly EndpointSpec[] = [
  // --- auth (anonymous) ---
  { method: 'POST', path: '/auth/register/owner', roles: [], anonymous: true },
  { method: 'POST', path: '/auth/login', roles: [], anonymous: true },
  { method: 'POST', path: '/auth/refresh', roles: [], anonymous: true },
  { method: 'POST', path: '/auth/verify-email', roles: [], anonymous: true },
  { method: 'POST', path: '/auth/password-reset', roles: [], anonymous: true },
  { method: 'POST', path: '/auth/password-reset/confirm', roles: [], anonymous: true },

  // --- auth (authenticated) ---
  { method: 'POST', path: '/auth/logout', roles: ALL },

  // --- catalogue ---
  { method: 'GET', path: '/saas-plans', roles: ALL, paginated: true },
  { method: 'GET', path: '/membership-plans', roles: ALL, paginated: true },
  { method: 'POST', path: '/membership-plans', roles: ['owner'] },
  { method: 'GET', path: '/membership-plans/{id}', roles: ALL },
  { method: 'PATCH', path: '/membership-plans/{id}', roles: ['owner'] },

  // --- identity and tenant ---
  { method: 'GET', path: '/me', roles: ALL },
  { method: 'PATCH', path: '/me', roles: ALL },
  { method: 'GET', path: '/gym', roles: ALL },
  { method: 'PATCH', path: '/gym', roles: ['owner'] },

  // --- profiles ---
  { method: 'GET', path: '/trainers', roles: ['owner'], paginated: true },
  { method: 'POST', path: '/trainers', roles: ['owner'] },
  { method: 'GET', path: '/members', roles: ['owner', 'trainer'], paginated: true },
  { method: 'POST', path: '/members', roles: ['owner', 'trainer'] },
  // A member reaches their OWN record here, via member_profile_id from /api/me.
  { method: 'GET', path: '/members/{id}', roles: ALL },
  { method: 'PATCH', path: '/members/{id}', roles: ['owner', 'trainer'] },

  // --- billing ---
  { method: 'GET', path: '/invoices', roles: ALL, paginated: true },
  { method: 'GET', path: '/invoices/{id}', roles: ALL },
  { method: 'POST', path: '/invoices/{id}/pay', roles: ['owner', 'member'] },
  // Present in the backend but unreachable from any UI: no route returns a Payment
  // id, so the identifier this route needs cannot be obtained. Listed for
  // completeness; deliberately never called.
  { method: 'GET', path: '/payments/{id}/receipt', roles: ['owner', 'member'] },
] as const;

/** Collapse a concrete path to its template form, for inventory comparison. */
export function toTemplate(path: string): string {
  return path.replace(/\/\d+(?=\/|$)/g, '/{id}');
}

export function isKnownEndpoint(method: string, path: string): boolean {
  const template = toTemplate(path);
  return ENDPOINTS.some((e) => e.method === method && e.path === template);
}

export function rolesFor(method: string, path: string): readonly Role[] | null {
  const template = toTemplate(path);
  const found = ENDPOINTS.find((e) => e.method === method && e.path === template);
  return found ? found.roles : null;
}
