import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { Loader2 } from 'lucide-react';
import { cn } from '@/lib/cn';

/**
 * genesis-DESIGN.md § Components > Buttons.
 *
 * Primary: indigo fill, white text, 6px radius, medium weight, glow shadow and a
 * 1px lift on hover. Secondary: transparent with a 1px border. Ghost: text only.
 * Sizes are Genesis's three heights: 32 / 38 / 44.
 *
 * Destructive is deliberately absent. Genesis defines the variant, but no backend
 * route accepts DELETE, so shipping it would create a control with nothing behind
 * it. See LIMITATIONS.md.
 */

type Variant = 'primary' | 'secondary' | 'ghost';
type Size = 'sm' | 'md' | 'lg';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}

const BASE =
  'inline-flex items-center justify-center gap-2 rounded-control font-body font-medium ' +
  'transition-[transform,box-shadow,background-color,color,border-color] duration-base ' +
  'ease-standard select-none disabled:cursor-not-allowed aria-disabled:cursor-not-allowed';

const VARIANTS: Record<Variant, string> = {
  primary: cn(
    'bg-primary text-surface border border-primary',
    'hover:bg-primary-hover hover:border-primary-hover hover:shadow-button-hover hover:-translate-y-px',
    'disabled:bg-chip-surface disabled:text-neutral disabled:border-border disabled:shadow-none disabled:translate-y-0',
    'aria-disabled:bg-chip-surface aria-disabled:text-neutral aria-disabled:border-border aria-disabled:shadow-none aria-disabled:translate-y-0',
  ),
  secondary: cn(
    'bg-transparent text-ink border border-border',
    'hover:border-primary hover:text-primary hover:-translate-y-px',
    'disabled:text-neutral disabled:border-border disabled:translate-y-0',
    'aria-disabled:text-neutral aria-disabled:border-border aria-disabled:translate-y-0',
  ),
  ghost: cn(
    'bg-transparent text-muted border border-transparent',
    'hover:text-primary',
    'disabled:text-neutral aria-disabled:text-neutral',
  ),
};

const SIZES: Record<Size, string> = {
  // Height and a matching min-width keep small icon buttons square.
  sm: 'h-8 min-w-8 px-3 text-control',
  md: 'h-[38px] min-w-[38px] px-4 text-control',
  lg: 'h-11 min-w-11 px-5 text-body',
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', loading = false, className, children, disabled, ...rest },
  ref,
) {
  // aria-disabled rather than the disabled attribute where a reason is shown, so
  // the control stays reachable by Tab and its explanation stays announceable.
  const inert = disabled === true || loading;

  return (
    <button
      ref={ref}
      type={rest.type ?? 'button'}
      aria-disabled={inert || undefined}
      disabled={disabled}
      className={cn(BASE, VARIANTS[variant], SIZES[size], className)}
      {...rest}
    >
      {loading ? (
        <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin motion-reduce:animate-none" />
      ) : null}
      {children}
    </button>
  );
});
