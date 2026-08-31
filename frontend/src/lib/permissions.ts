import type { Invoice, Me, Role } from '@/api/types';

/**
 * Frontend gating, mirroring the backend's permission classes.
 *
 * This is UX only. The backend is the security authority and re-evaluates every
 * request. The rule followed throughout: a ROLE refusal is expressed by OMITTING
 * the control, because it can never succeed; a STATE refusal is expressed by
 * DISABLING it with a stated reason, because the state can change.
 */

export interface WriteGate {
  allowed: boolean;
  /** Present when `allowed` is false. Shown next to the disabled control. */
  reason?: string;
}

const ALLOWED = { allowed: true } as const;

/**
 * `SubscriptionWriteGate`: when the gym's subscription is not trialing or active,
 * every unsafe method returns 403. Safe methods always pass. `InvoicePayView` is
 * the single exempt view, so paying stays possible.
 */
export function subscriptionWriteGate(me: Me): WriteGate {
  const status = me.subscription_status;
  if (status === 'trialing' || status === 'active') return ALLOWED;

  if (status === null) {
    return {
      allowed: false,
      reason:
        'This gym has no subscription, so the API refuses every create and update request.',
    };
  }
  return {
    allowed: false,
    reason: `This gym's subscription is ${status}. The API is read-only until the outstanding invoice is settled.`,
  };
}

/**
 * `ActiveMemberGate`: a member with no settled, in-period membership may read but
 * not write. Evaluated after the subscription gate.
 */
export function activeMemberGate(me: Me): WriteGate {
  if (me.role !== 'member') return ALLOWED;
  if (me.is_active_member !== false) return ALLOWED;
  return {
    allowed: false,
    reason:
      'Your membership is not active. Settle the outstanding invoice to regain write access.',
  };
}

/** The combined write gate for everything except invoice payment. */
export function canWrite(me: Me): WriteGate {
  const subscription = subscriptionWriteGate(me);
  if (!subscription.allowed) return subscription;
  return activeMemberGate(me);
}

/**
 * Member creation is special: `RequiresSubscription` is declared only on
 * `MemberListCreateView` and answers 402 SUBSCRIPTION_REQUIRED where every other
 * unsafe method answers 403. The distinction is worth preserving in the wording.
 */
export function canCreateMember(me: Me): WriteGate {
  if (me.role !== 'owner' && me.role !== 'trainer') {
    return { allowed: false, reason: 'Only an owner or a trainer can add a member.' };
  }
  const status = me.subscription_status;
  if (status !== 'trialing' && status !== 'active') {
    return {
      allowed: false,
      reason: 'Adding a member requires a trialing or active subscription.',
    };
  }
  return ALLOWED;
}

/** `MembershipPlanListCreateView` / `GymDetailView` declare write_roles = {owner}. */
export function canEditPlans(role: Role): boolean {
  return role === 'owner';
}

export function canEditGym(role: Role): boolean {
  return role === 'owner';
}

/** `MemberDetailView` PATCH admits owner and trainer, never member. */
export function canEditMembers(role: Role): boolean {
  return role === 'owner' || role === 'trainer';
}

/** `TrainerListCreateView` declares allowed_roles = {owner}. */
export function canSeeTrainers(role: Role): boolean {
  return role === 'owner';
}

/**
 * `InvoicePayView` admits owner and member, declares `subscription_exempt = True`
 * and is exempt from `ActiveMemberGate` — so a lapsed gym can still pay its way
 * back. Only the invoice's own status limits it.
 */
export function canPayInvoice(me: Me, invoice: Invoice): WriteGate {
  if (me.role === 'trainer') {
    return { allowed: false, reason: 'Trainers cannot pay invoices.' };
  }
  if (invoice.status !== 'open') {
    return {
      allowed: false,
      reason: `Only an invoice whose status is open can be paid. This one is ${invoice.status}.`,
    };
  }
  return ALLOWED;
}
