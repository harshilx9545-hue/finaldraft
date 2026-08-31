/**
 * TypeScript mirrors of the backend serializers in `core/serializers.py`.
 *
 * Three conventions come from the backend and are load-bearing:
 *
 * 1. Money is a STRING. `COERCE_DECIMAL_TO_STRING` is not overridden, so every
 *    DRF DecimalField arrives as e.g. "1500.00". These are typed `string` and must
 *    never be converted to `number` outside the single chart geometry module.
 * 2. Dates are `YYYY-MM-DD` strings evaluated in the GYM's timezone, not the
 *    browser's. Timestamps are ISO 8601 with offset.
 * 3. Foreign keys are bare integers with no nested representation and no name.
 */

export type Role = 'owner' | 'trainer' | 'member';

export const ROLES: readonly Role[] = ['owner', 'trainer', 'member'] as const;

/** `SaasSubscription.effective_status()`. Null when the gym holds no subscription. */
export type SubscriptionStatus = 'trialing' | 'active' | 'past_due' | 'cancelled';

/** `Invoice.status`. */
export type InvoiceStatus = 'open' | 'settled' | 'void' | 'refunded';

/** `TrainerProfile.status`. */
export type TrainerStatus = 'active' | 'inactive';

/** `MemberProfile.goal` choices. Blank is permitted and arrives as "". */
export type Goal = 'strength' | 'aesthetics' | 'cut' | 'bulk';

export const GOALS: readonly Goal[] = ['strength', 'aesthetics', 'cut', 'bulk'] as const;

/** `MembershipPlan.currency` / `SaasPlan.currency` choices. */
export type Currency = 'INR' | 'USD' | 'EUR' | 'GBP' | 'AED' | 'SGD' | 'AUD' | 'CAD';

export const CURRENCIES: readonly Currency[] = [
  'INR',
  'USD',
  'EUR',
  'GBP',
  'AED',
  'SGD',
  'AUD',
  'CAD',
] as const;

/** DRF `PageNumberPagination`, PAGE_SIZE 25, `page` the only accepted parameter. */
export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

/** `GymSerializer`. `slug` and `is_active` are read-only; `created_at` is never sent. */
export interface Gym {
  id: number;
  name: string;
  slug: string;
  contact_email: string | null;
  contact_phone: string | null;
  timezone: string;
  gstin: string | null;
  is_active: boolean;
}

export interface GymUpdate {
  name?: string;
  contact_email?: string;
  contact_phone?: string;
  timezone?: string;
  gstin?: string;
}

/** `MeSerializer`. `id` is the USER id and must never appear in a request path. */
export interface Me {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  phone: string | null;
  role: Role;
  email_verified: boolean;
  gym: Gym | null;
  subscription_status: SubscriptionStatus | null;
  /** Null for owner and trainer. */
  is_active_member: boolean | null;
  /** Null for owner and trainer, and for a member holding no membership. */
  current_period_end: string | null;
  /**
   * The caller's own MemberProfile pk, or null for a non-member role. The only
   * field of this response permitted to appear in a request path, and only as the
   * `{id}` segment of `GET /api/members/{id}`.
   */
  member_profile_id: number | null;
}

/** `MeUpdateSerializer` — the complete writable set. */
export interface MeUpdate {
  first_name?: string;
  last_name?: string;
  phone?: string;
}

/** `SaasPlanSerializer`. Entirely read-only. */
export interface SaasPlan {
  id: number;
  name: string;
  price: string;
  currency: Currency;
  billing_interval_months: number;
  max_members_allowed: number;
}

/** `MembershipPlanSerializer`. */
export interface MembershipPlan {
  id: number;
  name: string;
  price: string;
  currency: Currency;
  duration_days: number;
  includes_trainer: boolean;
  includes_diet: boolean;
}

export interface MembershipPlanWrite {
  name: string;
  price: string;
  duration_days: number;
  currency?: Currency;
  includes_trainer?: boolean;
  includes_diet?: boolean;
}

/** `TrainerProfileSerializer`. No detail or update route exists for this resource. */
export interface TrainerProfile {
  id: number;
  email: string;
  full_name: string;
  specialization: string;
  status: TrainerStatus;
}

/** `TrainerInviteSerializer`. `email` required; the rest optional. */
export interface TrainerInvite {
  email: string;
  first_name?: string;
  last_name?: string;
  phone?: string;
  specialization?: string;
}

/** `MemberProfileSerializer`. `plan` and `trainer` are bare pks. */
export interface MemberProfile {
  id: number;
  email: string;
  full_name: string;
  plan: number | null;
  trainer: number | null;
  join_date: string;
  goal: Goal | '';
  photo_url: string;
  /** Derived server-side from membership dates and invoice settlement. */
  is_active: boolean;
  current_period_end: string | null;
}

/** `MemberInviteSerializer`. `email` and `join_date` are required. */
export interface MemberInvite {
  email: string;
  join_date: string;
  first_name?: string;
  last_name?: string;
  phone?: string;
  plan?: number | null;
  trainer?: number | null;
  goal?: Goal;
  photo_url?: string;
}

/** The writable subset of `PATCH /api/members/{id}`. */
export interface MemberUpdate {
  plan?: number | null;
  trainer?: number | null;
  join_date?: string;
  goal?: Goal | '';
  photo_url?: string;
}

/**
 * `InvoiceSerializer`. Fully read-only.
 *
 * `cgst`, `sgst`, `igst` and `hsn_sac` are null when the issuing gym has no
 * GSTIN, meaning "tax not applicable". Null is deliberately distinct from "0.00".
 * `membership` and `saas_subscription` are bare pks with no resolving route.
 */
export interface Invoice {
  id: number;
  number: string;
  financial_year: string;
  sequence_no: number;
  taxable_value: string;
  cgst: string | null;
  sgst: string | null;
  igst: string | null;
  hsn_sac: string | null;
  total_amount: string;
  currency: Currency;
  status: InvoiceStatus;
  issue_date: string;
  due_date: string;
  membership: number | null;
  saas_subscription: number | null;
}

/**
 * Response of `POST /api/invoices/{id}/pay`.
 *
 * `amount_minor` is the one integer money value in the whole API — minor units,
 * paise for INR. It goes to the gateway checkout and is never rendered as a
 * human-readable amount. `key_id` is Razorpay's PUBLIC key, delivered at runtime.
 * No Payment id is returned, which is why no receipt surface can exist.
 */
export interface PayOrder {
  order_ref: string;
  amount_minor: number;
  currency: Currency;
  key_id: string;
  receipt: string;
}

/* --- Authentication --- */

export interface LoginRequest {
  /** An email address or an E.164 phone number. The backend accepts either. */
  identifier: string;
  password: string;
}

export interface TokenPair {
  access: string;
  refresh: string;
}

export interface OwnerRegistrationRequest {
  email: string;
  password: string;
  password_confirm: string;
  business_name: string;
  contact_phone: string;
  first_name?: string;
  last_name?: string;
  phone?: string;
  gym_name?: string;
  contact_email?: string;
  timezone_name?: string;
  gstin?: string;
}

export interface OwnerRegistrationResponse {
  gym: Gym;
  user: { id: number; email: string; role: Role; email_verified: boolean };
  tokens: TokenPair;
}

export interface DetailResponse {
  detail: string;
}

export interface EmailVerifiedResponse {
  email_verified: boolean;
}
