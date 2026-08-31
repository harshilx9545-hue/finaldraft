import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query';
import * as resources from '@/api/resources';
import type {
  Gym,
  GymUpdate,
  Invoice,
  MemberInvite,
  MemberProfile,
  MemberUpdate,
  MembershipPlan,
  MembershipPlanWrite,
  Me,
  MeUpdate,
  Paginated,
  TrainerInvite,
  TrainerProfile,
} from '@/api/types';
import { ApiError } from '@/lib/errors';

/**
 * Query keys and hooks.
 *
 * A few backend facts shape the cache policy here:
 *
 * - Derived state (`is_active`, `is_active_member`, `current_period_end`,
 *   `subscription_status`) is recomputed per request against the GYM's calendar, so
 *   it goes stale on the wall clock rather than on our writes. 60s staleTime.
 * - `GET /api/invoices` has a side effect: it calls `ensure_period_invoice`, which
 *   can ISSUE the upcoming subscription invoice. So invoices never refetch on focus
 *   and never poll.
 * - A 401 is already handled inside the API client (single-flight refresh, then
 *   session end), so retrying it here would be noise. 4xx is never retried.
 */

export const keys = {
  me: ['me'] as const,
  gym: ['gym'] as const,
  members: (page: number) => ['members', page] as const,
  membersAll: ['members'] as const,
  member: (id: number) => ['member', id] as const,
  trainers: (page: number) => ['trainers', page] as const,
  trainersAll: ['trainers'] as const,
  trainersEvery: ['trainers', 'all'] as const,
  plans: (page: number) => ['membership-plans', page] as const,
  plansAll: ['membership-plans'] as const,
  plansEvery: ['membership-plans', 'all'] as const,
  plan: (id: number) => ['membership-plan', id] as const,
  invoices: (page: number) => ['invoices', page] as const,
  invoicesAll: ['invoices'] as const,
  invoicesEvery: ['invoices', 'all'] as const,
  invoice: (id: number) => ['invoice', id] as const,
} as const;

const DERIVED_STALE_MS = 60_000;

// Typed against Error rather than unknown so TanStack keeps TError = Error and the
// hooks' declared return types line up.
function retryPolicy(failureCount: number, error: Error): boolean {
  // Client errors are the server's considered answer, not a blip.
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 2;
}

/* ------------------------------------------------------------------ reads */

export function useMeQuery(enabled = true): UseQueryResult<Me> {
  return useQuery({
    queryKey: keys.me,
    queryFn: resources.getMe,
    staleTime: DERIVED_STALE_MS,
    retry: retryPolicy,
    enabled,
  });
}

export function useGymQuery(): UseQueryResult<Gym> {
  return useQuery({ queryKey: keys.gym, queryFn: resources.getGym, retry: retryPolicy });
}

export function useMembersQuery(page: number, enabled = true): UseQueryResult<Paginated<MemberProfile>> {
  return useQuery({
    queryKey: keys.members(page),
    queryFn: () => resources.listMembers(page),
    staleTime: DERIVED_STALE_MS,
    retry: retryPolicy,
    enabled,
  });
}

export function useMemberQuery(id: number | null): UseQueryResult<MemberProfile> {
  return useQuery({
    queryKey: keys.member(id ?? -1),
    queryFn: () => resources.getMember(id as number),
    enabled: id !== null,
    staleTime: DERIVED_STALE_MS,
    retry: retryPolicy,
  });
}

export function useTrainersQuery(page: number, enabled = true): UseQueryResult<Paginated<TrainerProfile>> {
  return useQuery({
    queryKey: keys.trainers(page),
    queryFn: () => resources.listTrainers(page),
    retry: retryPolicy,
    enabled,
  });
}

export function usePlansQuery(page: number, enabled = true): UseQueryResult<Paginated<MembershipPlan>> {
  return useQuery({
    queryKey: keys.plans(page),
    queryFn: () => resources.listMembershipPlans(page),
    retry: retryPolicy,
    enabled,
  });
}

export function useInvoicesQuery(page: number, enabled = true): UseQueryResult<Paginated<Invoice>> {
  return useQuery({
    queryKey: keys.invoices(page),
    queryFn: () => resources.listInvoices(page),
    // Reading this list can cause the backend to issue an invoice. Never automatic.
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    refetchInterval: false,
    retry: retryPolicy,
    enabled,
  });
}

export function useInvoiceQuery(id: number | null): UseQueryResult<Invoice> {
  return useQuery({
    queryKey: keys.invoice(id ?? -1),
    queryFn: () => resources.getInvoice(id as number),
    enabled: id !== null,
    refetchOnWindowFocus: false,
    retry: retryPolicy,
  });
}

/**
 * Every page of the plan collection, for resolving a member's bare `plan` id to a
 * name. The backend serialises foreign keys as integers and offers no lookup, so
 * this is the only honest way to show a plan name.
 */
export function useAllPlansQuery(enabled = true) {
  return useQuery({
    queryKey: keys.plansEvery,
    queryFn: () => resources.fetchAllPages(resources.listMembershipPlans),
    staleTime: 5 * 60_000,
    retry: retryPolicy,
    enabled,
  });
}

/** Every page of trainers, owner only — `GET /api/trainers` 403s for anyone else. */
export function useAllTrainersQuery(enabled: boolean) {
  return useQuery({
    queryKey: keys.trainersEvery,
    queryFn: () => resources.fetchAllPages(resources.listTrainers),
    staleTime: 5 * 60_000,
    retry: retryPolicy,
    enabled,
  });
}

/* ----------------------------------------------------------------- writes */

export function useUpdateMe() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: MeUpdate) => resources.updateMe(payload),
    onSuccess: (me) => {
      // Replace rather than invalidate: role and gating derive from this payload.
      client.setQueryData(keys.me, me);
    },
  });
}

export function useUpdateGym() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: GymUpdate) => resources.updateGym(payload),
    onSuccess: (gym) => {
      client.setQueryData(keys.gym, gym);
      // /api/me carries the gym object, so it is now stale too.
      void client.invalidateQueries({ queryKey: keys.me });
    },
  });
}

export function useCreateMember() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: MemberInvite) => resources.createMember(payload),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.membersAll });
    },
  });
}

export function useUpdateMember(id: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: MemberUpdate) => resources.updateMember(id, payload),
    onSuccess: (member) => {
      client.setQueryData(keys.member(id), member);
      void client.invalidateQueries({ queryKey: keys.membersAll });
    },
  });
}

export function useCreateTrainer() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: TrainerInvite) => resources.createTrainer(payload),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.trainersAll });
    },
  });
}

export function useCreatePlan() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: MembershipPlanWrite) => resources.createMembershipPlan(payload),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.plansAll });
    },
  });
}

export function useUpdatePlan(id: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<MembershipPlanWrite>) =>
      resources.updateMembershipPlan(id, payload),
    onSuccess: (plan) => {
      client.setQueryData(keys.plan(id), plan);
      void client.invalidateQueries({ queryKey: keys.plansAll });
    },
  });
}

export function usePayInvoice(id: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => resources.payInvoice(id),
    onSuccess: () => {
      // The invoice status does NOT change here — only the gateway webhook settles
      // it. Invalidating keeps the displayed record honest if it changed for another
      // reason, but the UI must not claim the invoice is paid.
      void client.invalidateQueries({ queryKey: keys.invoice(id) });
    },
  });
}
