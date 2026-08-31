import { cloneElement, useId, type ReactElement } from 'react';
import { Info } from 'lucide-react';
import { cn } from '@/lib/cn';

/**
 * The single mechanism for a control that exists but cannot currently act.
 *
 * The project rule is that no control is ever disabled silently. A control is
 * either omitted entirely — because the signed-in role can never use it, so
 * showing it would be a lie — or it is disabled WITH a visible sentence saying
 * what refuses it and what would change that. This component enforces the second
 * case: it cannot render a disabled control without a reason, because `reason` is
 * a required prop.
 *
 * The control keeps its place in the tab order and carries aria-disabled rather
 * than the disabled attribute, so a screen reader user can find it and hear why
 * it is unavailable instead of it silently vanishing.
 */

export interface DisabledWithReasonProps {
  /** False renders the child untouched. */
  disabled: boolean;
  reason: string;
  children: ReactElement<{
    'aria-disabled'?: boolean;
    'aria-describedby'?: string;
    disabled?: boolean;
    onClick?: (event: React.MouseEvent) => void;
  }>;
  className?: string;
}

export function DisabledWithReason({
  disabled,
  reason,
  children,
  className,
}: DisabledWithReasonProps): JSX.Element {
  const id = useId();

  if (!disabled) return <>{children}</>;

  const control = cloneElement(children, {
    'aria-disabled': true,
    'aria-describedby': id,
    // Deliberately NOT the disabled attribute: that would remove the control from
    // the tab order and take its description with it.
    disabled: false,
    onClick: (event: React.MouseEvent) => {
      event.preventDefault();
      event.stopPropagation();
    },
  });

  return (
    <div className={cn('flex flex-col gap-2', className)}>
      <div className="opacity-60">{control}</div>
      <p id={id} className="flex items-start gap-2 text-caption text-muted">
        <Info aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>{reason}</span>
      </p>
    </div>
  );
}
