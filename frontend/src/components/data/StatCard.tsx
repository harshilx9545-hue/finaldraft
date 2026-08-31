import { useEffect, useRef, useState } from 'react';
import { useReducedMotion } from 'framer-motion';
import { Card } from '@/components/ui/Card';
import { mapFailure } from '@/lib/errors';
import { Button } from '@/components/ui/Button';
import { DURATION } from '@/lib/motion';

/**
 * A single metric.
 *
 * Every value here is either a `count` from a paginated response or a scalar from
 * /api/me. The backend exposes no aggregate endpoint, so there is deliberately no
 * trend arrow, no percentage, no sparkline and no period comparison — there is no
 * data to compute any of them from.
 *
 * The count-up applies to integers only. Money is never animated: interpolating a
 * decimal string would mean turning it into a number, which is exactly what the
 * money rules forbid.
 */

function useCountUp(target: number, enabled: boolean): number {
  const [value, setValue] = useState(enabled ? 0 : target);
  const done = useRef(false);

  useEffect(() => {
    if (!enabled) {
      setValue(target);
      return;
    }
    // Once per mount, and not again on a refetch that returns the same number.
    if (done.current) {
      setValue(target);
      return;
    }
    done.current = true;

    if (target === 0) {
      setValue(0);
      return;
    }

    const durationMs = DURATION.countUp * 1000;
    const started = performance.now();
    let frame = 0;

    const tick = (now: number): void => {
      const progress = Math.min(1, (now - started) / durationMs);
      // Ease-out so it settles rather than stopping dead.
      const eased = 1 - (1 - progress) ** 3;
      setValue(Math.round(target * eased));
      if (progress < 1) frame = requestAnimationFrame(tick);
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target, enabled]);

  return value;
}

export interface StatCardProps {
  label: string;
  /** An integer count. Mutually exclusive with `display`. */
  value?: number;
  /** Pre-rendered content, for anything that is not a plain integer. */
  display?: React.ReactNode;
  hint?: string;
  error?: unknown;
  onRetry?: () => void;
  loading?: boolean;
}

export function StatCard({
  label,
  value,
  display,
  hint,
  error,
  onRetry,
  loading = false,
}: StatCardProps): JSX.Element {
  const reduced = useReducedMotion() ?? false;
  const animate = value !== undefined && !reduced && !loading && error === undefined;
  const counted = useCountUp(value ?? 0, animate);

  return (
    <Card className="p-5">
      <p className="text-caption font-medium uppercase tracking-[0.08em] text-muted">{label}</p>

      <div className="mt-3">
        {error !== undefined ? (
          // No numeral and no zero for a metric that failed: a zero would be a
          // factual claim the backend never made.
          <div className="flex flex-col gap-2">
            <p className="text-small text-error">{mapFailure(error).message}</p>
            {onRetry ? (
              <Button variant="ghost" size="sm" onClick={onRetry} className="self-start px-0">
                Retry
              </Button>
            ) : null}
          </div>
        ) : loading ? (
          <div aria-hidden="true" className="h-8 w-16 rounded-chip bg-chip-surface" />
        ) : display !== undefined ? (
          <div className="text-subhead font-medium text-ink">{display}</div>
        ) : (
          <p className="font-display text-section font-bold text-ink tabular">
            {animate ? counted : (value ?? 0)}
          </p>
        )}
      </div>

      {hint ? <p className="mt-3 text-caption text-muted">{hint}</p> : null}
    </Card>
  );
}
