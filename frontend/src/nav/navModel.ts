import type { Role } from '@/api/types';

/**
 * Navigation, derived from what each role can actually reach.
 *
 * Every destination records the backend endpoints its surface reads, so a test can
 * assert that the signed-in role appears in the admitted-role set of each of them.
 * Nothing here is a design preference: a role that cannot call `/api/trainers` does
 * not get a Trainers link, because the page would only be able to render a 403.
 */

export interface NavDestination {
  label: string;
  path: string;
  /** Method + path pairs from ENDPOINTS that this surface requires. */
  requires: readonly string[];
}

const OVERVIEW_OWNER: NavDestination = {
  label: 'Overview',
  path: '/overview',
  requires: ['GET /me', 'GET /members', 'GET /trainers', 'GET /membership-plans', 'GET /invoices'],
};

const OVERVIEW_TRAINER: NavDestination = {
  label: 'Overview',
  path: '/overview',
  requires: ['GET /me', 'GET /members', 'GET /membership-plans'],
};

const OVERVIEW_MEMBER: NavDestination = {
  label: 'Overview',
  path: '/overview',
  requires: ['GET /me', 'GET /invoices'],
};

const MEMBERS: NavDestination = {
  label: 'Members',
  path: '/members',
  requires: ['GET /members', 'GET /membership-plans'],
};

const TRAINERS: NavDestination = {
  label: 'Trainers',
  path: '/trainers',
  requires: ['GET /trainers'],
};

const PLANS: NavDestination = {
  label: 'Membership Plans',
  path: '/membership-plans',
  requires: ['GET /membership-plans'],
};

const INVOICES: NavDestination = {
  label: 'Invoices',
  path: '/invoices',
  requires: ['GET /invoices'],
};

const GYM: NavDestination = { label: 'Gym', path: '/gym', requires: ['GET /gym'] };

const PROFILE: NavDestination = { label: 'Profile', path: '/profile', requires: ['GET /me'] };

const MY_MEMBERSHIP: NavDestination = {
  label: 'My Membership',
  path: '/my-membership',
  // Reached with member_profile_id from /api/me. MemberSelfScope admits a member
  // to their own MemberProfile; the identifier was the only thing missing.
  requires: ['GET /me', 'GET /members/{id}', 'GET /membership-plans'],
};

export const NAV_MODEL: Record<Role, readonly NavDestination[]> = {
  owner: [OVERVIEW_OWNER, MEMBERS, TRAINERS, PLANS, INVOICES, GYM, PROFILE],
  trainer: [OVERVIEW_TRAINER, MEMBERS, PLANS, GYM, PROFILE],
  member: [OVERVIEW_MEMBER, MY_MEMBERSHIP, PLANS, INVOICES, GYM, PROFILE],
};

export function destinationsFor(role: Role | null): readonly NavDestination[] {
  if (role === null) return [];
  return NAV_MODEL[role] ?? [];
}

/** Routes each role may enter. Detail routes are included by prefix. */
const EXTRA_ROUTES: Record<Role, readonly string[]> = {
  owner: ['/members/', '/invoices/'],
  trainer: ['/members/', '/invoices/'],
  member: ['/invoices/'],
};

export function roleMayEnter(role: Role | null, pathname: string): boolean {
  if (role === null) return false;
  const destinations = destinationsFor(role);
  if (destinations.some((d) => d.path === pathname)) return true;
  return (EXTRA_ROUTES[role] ?? []).some((prefix) => pathname.startsWith(prefix));
}

export function homeFor(role: Role | null): string {
  return role === null ? '/sign-in' : '/overview';
}
