import { cn } from '@/lib/cn';
import type { InvoiceStatus, SubscriptionStatus, TrainerStatus } from '@/api/types';

/**
 * genesis-DESIGN.md § Components > Chips.
 *
 * "Tag chips use rounded-full (pill shape), gray-100 background, gray-600 text ...
 * Status chips follow the same shape but use semantic colors (green for published,
 * yellow for pending, red for rejected)."
 *
 * Every chip carries its backend value as TEXT as well as colour, so state is
 * never conveyed by colour alone. The label is always the real backend value, not
 * a prettified invention.
 */

export type Tone = 'success' | 'warning' | 'error' | 'neutral' | 'info';

const TONES: Record<Tone, string> = {
  // Semantic tones are tinted backgrounds with the semantic colour as text, which
  // keeps text contrast well clear of the 4.5:1 floor on a white card.
  success: 'bg-chip-surface text-success',
  warning: 'bg-chip-surface text-warning',
  error: 'bg-chip-surface text-error',
  neutral: 'bg-chip-surface text-chip-text',
  info: 'bg-chip-surface text-primary',
};

export interface ChipProps {
  tone?: Tone;
  children: React.ReactNode;
  className?: string;
}

export function Chip({ tone = 'neutral', children, className }: ChipProps): JSX.Element {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-pill px-3 py-1 text-caption font-medium whitespace-nowrap',
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/* ---- Mappings from real backend vocabularies to Genesis's semantic tones ---- */

const INVOICE_TONES: Record<InvoiceStatus, Tone> = {
  open: 'warning', // outstanding, action available
  settled: 'success',
  void: 'error', // cancelled, cannot be paid
  refunded: 'neutral', // informational, terminal
};

export function InvoiceStatusChip({ status }: { status: string }): JSX.Element {
  const tone = (INVOICE_TONES as Record<string, Tone | undefined>)[status];
  // An unrecognised value renders as its literal text with no status styling,
  // rather than being coerced into a tone that might misstate it.
  return <Chip tone={tone ?? 'neutral'}>{status}</Chip>;
}

const SUBSCRIPTION_TONES: Record<SubscriptionStatus, Tone> = {
  trialing: 'warning',
  active: 'success',
  past_due: 'error',
  cancelled: 'error',
};

const SUBSCRIPTION_LABELS: Record<SubscriptionStatus, string> = {
  trialing: 'Trialing',
  active: 'Active',
  past_due: 'Past due',
  cancelled: 'Cancelled',
};

export function SubscriptionStatusChip({
  status,
}: {
  status: SubscriptionStatus | null;
}): JSX.Element {
  if (status === null) return <Chip tone="neutral">No subscription</Chip>;
  const tone = SUBSCRIPTION_TONES[status];
  if (tone === undefined) return <Chip tone="neutral">{status}</Chip>;
  return <Chip tone={tone}>{SUBSCRIPTION_LABELS[status]}</Chip>;
}

/** `MemberProfile.is_active` / `Me.is_active_member`. Derived server-side. */
export function ActiveChip({ active }: { active: boolean }): JSX.Element {
  return <Chip tone={active ? 'success' : 'neutral'}>{active ? 'Active' : 'Not active'}</Chip>;
}

const TRAINER_TONES: Record<TrainerStatus, Tone> = { active: 'success', inactive: 'neutral' };

export function TrainerStatusChip({ status }: { status: string }): JSX.Element {
  const tone = (TRAINER_TONES as Record<string, Tone | undefined>)[status];
  return <Chip tone={tone ?? 'neutral'}>{status}</Chip>;
}

export function VerifiedChip({ verified }: { verified: boolean }): JSX.Element {
  return (
    <Chip tone={verified ? 'success' : 'warning'}>{verified ? 'Verified' : 'Not verified'}</Chip>
  );
}
