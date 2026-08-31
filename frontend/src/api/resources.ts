import { api, pageFromUrl } from './client';
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
  PayOrder,
  SaasPlan,
  TrainerInvite,
  TrainerProfile,
} from './types';

/* -------------------------------------------------------------- identity */

export const getMe = (): Promise<Me> => api.get<Me>('/me');

export const updateMe = (payload: MeUpdate): Promise<Me> => api.patch<Me>('/me', payload);

/* ------------------------------------------------------------------- gym */

export const getGym = (): Promise<Gym> => api.get<Gym>('/gym');

export const updateGym = (payload: GymUpdate): Promise<Gym> => api.patch<Gym>('/gym', payload);

/* --------------------------------------------------------------- members */

export const listMembers = (page = 1): Promise<Paginated<MemberProfile>> =>
  api.get<Paginated<MemberProfile>>('/members', { query: { page } });

export const getMember = (id: number): Promise<MemberProfile> =>
  api.get<MemberProfile>(`/members/${id}`);

export const createMember = (payload: MemberInvite): Promise<MemberProfile> =>
  api.post<MemberProfile>('/members', payload);

export const updateMember = (id: number, payload: MemberUpdate): Promise<MemberProfile> =>
  api.patch<MemberProfile>(`/members/${id}`, payload);

/* -------------------------------------------------------------- trainers */

export const listTrainers = (page = 1): Promise<Paginated<TrainerProfile>> =>
  api.get<Paginated<TrainerProfile>>('/trainers', { query: { page } });

export const createTrainer = (payload: TrainerInvite): Promise<TrainerProfile> =>
  api.post<TrainerProfile>('/trainers', payload);

/* -------------------------------------------------------- membership plans */

export const listMembershipPlans = (page = 1): Promise<Paginated<MembershipPlan>> =>
  api.get<Paginated<MembershipPlan>>('/membership-plans', { query: { page } });

export const getMembershipPlan = (id: number): Promise<MembershipPlan> =>
  api.get<MembershipPlan>(`/membership-plans/${id}`);

export const createMembershipPlan = (payload: MembershipPlanWrite): Promise<MembershipPlan> =>
  api.post<MembershipPlan>('/membership-plans', payload);

export const updateMembershipPlan = (
  id: number,
  payload: Partial<MembershipPlanWrite>,
): Promise<MembershipPlan> => api.patch<MembershipPlan>(`/membership-plans/${id}`, payload);

/* ------------------------------------------------------------ saas plans */

export const listSaasPlans = (page = 1): Promise<Paginated<SaasPlan>> =>
  api.get<Paginated<SaasPlan>>('/saas-plans', { query: { page } });

/* -------------------------------------------------------------- invoices */

/**
 * GET /api/invoices
 *
 * Scoped by the backend: an owner receives the whole gym's invoices, every other
 * role only invoices whose `payer_user` is that user. There is no payer, status or
 * date parameter — the scoping is not a filter the client can influence.
 *
 * Side effect worth knowing: `InvoiceListView.list` calls `ensure_period_invoice`,
 * so reading this list can cause the backend to ISSUE the upcoming subscription
 * invoice. Do not poll it.
 */
export const listInvoices = (page = 1): Promise<Paginated<Invoice>> =>
  api.get<Paginated<Invoice>>('/invoices', { query: { page } });

export const getInvoice = (id: number): Promise<Invoice> => api.get<Invoice>(`/invoices/${id}`);

/**
 * POST /api/invoices/{id}/pay
 *
 * The body is an empty object, deliberately. The backend scans request bodies at
 * every nesting depth for card-data field names and answers 400
 * CARD_DATA_REJECTED, and this client collects no card data anywhere.
 */
export const payInvoice = (id: number): Promise<PayOrder> =>
  api.post<PayOrder>(`/invoices/${id}/pay`, {});

/* ------------------------------------------------- exhaustive page walking */

const MAX_PAGES = 40; // 1,000 records at PAGE_SIZE 25

export interface FullCollection<T> {
  items: T[];
  count: number;
  /** True when the walk stopped at MAX_PAGES with more pages still available. */
  truncated: boolean;
}

/**
 * Fetch every page of a collection, in order, one request at a time.
 *
 * Needed for two honest purposes only: resolving a plan or trainer id to a name
 * (the backend serialises bare integers and offers no lookup), and building the
 * invoice chart, which must not plot a partial series. Stops when `next` is null.
 */
export async function fetchAllPages<T>(
  fetchPage: (page: number) => Promise<Paginated<T>>,
  onProgress?: (received: number, count: number) => void,
): Promise<FullCollection<T>> {
  const items: T[] = [];
  let page: number | null = 1;
  let count = 0;
  let requests = 0;

  while (page !== null) {
    if (requests >= MAX_PAGES) {
      return { items, count, truncated: true };
    }
    const response: Paginated<T> = await fetchPage(page);
    requests += 1;
    count = response.count;
    items.push(...response.results);
    onProgress?.(items.length, count);
    page = pageFromUrl(response.next);
  }

  return { items, count, truncated: false };
}
