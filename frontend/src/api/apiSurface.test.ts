import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ENDPOINTS, isKnownEndpoint, rolesFor, toTemplate } from './endpoints';
import { buildUrl, setTokens, clearTokens, API_BASE } from './client';
import * as resources from './resources';
import { NAV_MODEL } from '@/nav/navModel';
import { ROLES } from './types';

/**
 * The guard rail against the frontend inventing backend capability.
 *
 * Every request the API layer can construct is exercised against a mocked fetch,
 * and the method and path are checked against the route inventory taken from
 * `core/urls.py`. A call to a route that does not exist fails here rather than
 * 404ing in front of a user.
 */

interface Captured {
  method: string;
  url: string;
  body: string | null;
}

const captured: Captured[] = [];

function mockFetch(): void {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: string, init?: RequestInit) => {
      captured.push({
        method: init?.method ?? 'GET',
        url: String(input),
        body: typeof init?.body === 'string' ? init.body : null,
      });
      return Promise.resolve(
        new Response(JSON.stringify({ count: 0, next: null, previous: null, results: [] }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    }),
  );
}

beforeEach(() => {
  captured.length = 0;
  mockFetch();
  setTokens({ access: 'access-token', refresh: 'refresh-token' });
});

/** Every call the resource layer exposes, with throwaway ids. */
async function exerciseEveryCall(): Promise<void> {
  await resources.getMe();
  await resources.updateMe({ first_name: 'A' });
  await resources.getGym();
  await resources.updateGym({ name: 'G' });
  await resources.listMembers(1);
  await resources.getMember(7);
  await resources.createMember({ email: 'a@b.com', join_date: '2026-01-01' });
  await resources.updateMember(7, { goal: 'bulk' });
  await resources.listTrainers(1);
  await resources.createTrainer({ email: 'a@b.com' });
  await resources.listMembershipPlans(1);
  await resources.getMembershipPlan(3);
  await resources.createMembershipPlan({ name: 'P', price: '10.00', duration_days: 30 });
  await resources.updateMembershipPlan(3, { name: 'Q' });
  await resources.listSaasPlans(1);
  await resources.listInvoices(1);
  await resources.getInvoice(9);
  await resources.payInvoice(9);
}

describe('the request surface', () => {
  it('only ever targets a route that exists in the backend', async () => {
    await exerciseEveryCall();
    expect(captured.length).toBeGreaterThan(0);

    for (const request of captured) {
      const path = new URL(request.url).pathname.replace(
        new URL(API_BASE).pathname.replace(/\/$/, ''),
        '',
      );
      expect(
        isKnownEndpoint(request.method, toTemplate(path)),
        `${request.method} ${path} is not in the backend route inventory`,
      ).toBe(true);
    }
  });

  it('never issues a DELETE, because no route accepts one', async () => {
    await exerciseEveryCall();
    for (const request of captured) {
      expect(request.method).not.toBe('DELETE');
    }
    expect(ENDPOINTS.some((endpoint) => endpoint.method === ('DELETE' as string))).toBe(false);
  });

  it('sends no query parameter other than page', async () => {
    await exerciseEveryCall();
    for (const request of captured) {
      const params = [...new URL(request.url).searchParams.keys()];
      for (const key of params) {
        expect(key, `unexpected query parameter on ${request.url}`).toBe('page');
      }
    }
  });

  it('refuses to construct a search, filter, sort or page-size parameter', () => {
    // The backend registers no filter backend and no view reads query_params, so
    // any of these would be silently ignored — and a UI that appears to filter but
    // does not is worse than one that admits it cannot.
    for (const key of ['search', 'q', 'ordering', 'sort', 'status', 'page_size']) {
      expect(() => buildUrl('/members', { [key]: 'x' })).toThrowError();
    }
    expect(() => buildUrl('/members', { page: 2 })).not.toThrow();
  });

  it('sends an empty body to the pay route and no card data anywhere', async () => {
    await exerciseEveryCall();
    const pay = captured.find((request) => request.url.includes('/pay'));
    expect(pay?.body).toBe('{}');

    const cardTokens = ['card', 'cvv', 'cvc', 'pan', 'expiry', 'exp_month', 'exp_year', 'cardholder'];
    for (const request of captured) {
      const body = (request.body ?? '').toLowerCase();
      for (const token of cardTokens) {
        expect(body, `card-like key "${token}" in a request body`).not.toContain(`"${token}`);
      }
    }
  });

  it('attaches a bearer token to authenticated routes and withholds it from auth routes', async () => {
    // Verified through the client's own path selection rather than by reading
    // headers, since the six anonymous paths are declared in one place.
    for (const path of [
      '/auth/register/owner',
      '/auth/login',
      '/auth/refresh',
      '/auth/verify-email',
      '/auth/password-reset',
      '/auth/password-reset/confirm',
    ]) {
      const spec = ENDPOINTS.find((endpoint) => endpoint.path === path);
      expect(spec?.anonymous, path).toBe(true);
    }
    clearTokens();
  });
});

describe('navigation matches real permissions', () => {
  it('declares a destination only where the role is admitted by every route it reads', () => {
    for (const role of ROLES) {
      for (const destination of NAV_MODEL[role]) {
        for (const requirement of destination.requires) {
          const [method, path] = requirement.split(' ');
          const roles = rolesFor(method as string, path as string);
          expect(roles, `${requirement} is not a known endpoint`).not.toBeNull();
          expect(
            roles?.includes(role),
            `${role} cannot reach ${requirement}, but ${destination.label} needs it`,
          ).toBe(true);
        }
      }
    }
  });

  it('gives each role exactly the destinations the audit found', () => {
    expect(NAV_MODEL.owner.map((d) => d.label)).toEqual([
      'Overview',
      'Members',
      'Trainers',
      'Membership Plans',
      'Invoices',
      'Gym',
      'Profile',
    ]);
    expect(NAV_MODEL.trainer.map((d) => d.label)).toEqual([
      'Overview',
      'Members',
      'Membership Plans',
      'Gym',
      'Profile',
    ]);
    expect(NAV_MODEL.member.map((d) => d.label)).toEqual([
      'Overview',
      'My Membership',
      'Membership Plans',
      'Invoices',
      'Gym',
      'Profile',
    ]);
  });

  it('keeps trainers out of the trainer roster, which is owner-only', () => {
    expect(NAV_MODEL.trainer.some((d) => d.path === '/trainers')).toBe(false);
    expect(NAV_MODEL.member.some((d) => d.path === '/trainers')).toBe(false);
    expect(rolesFor('GET', '/trainers')).toEqual(['owner']);
  });

  it('keeps members out of the member roster, which they cannot list', () => {
    expect(NAV_MODEL.member.some((d) => d.path === '/members')).toBe(false);
    expect(rolesFor('GET', '/members')).toEqual(['owner', 'trainer']);
  });
});
