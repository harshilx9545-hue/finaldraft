import { Info } from 'lucide-react';
import { cn } from '@/lib/cn';

/**
 * A standing statement about what the API cannot do.
 *
 * These exist because the honest alternative to a missing feature is saying so.
 * Several appear on permanent display: the members list cannot start a paid
 * membership period, the trainers list cannot edit a trainer, no list can be
 * searched. Each is visible without hover or disclosure, because a limitation
 * hidden behind a tooltip is a limitation the user discovers by failing.
 */
export function Note({
  children,
  className,
  tone = 'neutral',
}: {
  children: React.ReactNode;
  className?: string;
  tone?: 'neutral' | 'warning';
}): JSX.Element {
  return (
    <p
      className={cn(
        'flex items-start gap-2 rounded-panel border px-4 py-3 text-small',
        tone === 'warning'
          ? 'border-warning bg-surface text-ink'
          : 'border-border bg-surface text-muted',
        className,
      )}
    >
      <Info aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
      <span className="break-value">{children}</span>
    </p>
  );
}
