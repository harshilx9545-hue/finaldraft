import { forwardRef, type HTMLAttributes } from 'react';
import { cn } from '@/lib/cn';

/**
 * genesis-DESIGN.md § Components > Cards.
 *
 * "White surface, 1px subtle border, 12px radius, overflow hidden. Hover lifts the
 * card 2px and increases shadow. Transition duration 200ms."
 *
 * Genesis is explicit in its Don'ts that static elements carry no shadow, so the
 * resting state has a border only. `interactive` opts into the hover lift; a card
 * that is not a link or a button should not move under the pointer.
 */

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  interactive?: boolean;
  /** Genesis uses 8px for "metadata cards, dropdowns, panels". */
  density?: 'card' | 'panel';
}

export const Card = forwardRef<HTMLDivElement, CardProps>(function Card(
  { interactive = false, density = 'card', className, ...rest },
  ref,
) {
  return (
    <div
      ref={ref}
      className={cn(
        'bg-surface border border-border overflow-hidden',
        density === 'card' ? 'rounded-card' : 'rounded-panel',
        interactive &&
          'transition-[transform,box-shadow] duration-base ease-standard hover:-translate-y-0.5 hover:shadow-card-hover',
        className,
      )}
      {...rest}
    />
  );
});

export function CardHeader({ className, ...rest }: HTMLAttributes<HTMLDivElement>): JSX.Element {
  return (
    <div
      className={cn('flex flex-wrap items-start justify-between gap-3 px-5 pt-5 pb-3', className)}
      {...rest}
    />
  );
}

export function CardTitle({ className, ...rest }: HTMLAttributes<HTMLHeadingElement>): JSX.Element {
  return (
    <h2
      className={cn('font-display text-subhead font-bold text-ink', className)}
      {...rest}
    />
  );
}

export function CardDescription({
  className,
  ...rest
}: HTMLAttributes<HTMLParagraphElement>): JSX.Element {
  return <p className={cn('text-small text-muted', className)} {...rest} />;
}

export function CardBody({ className, ...rest }: HTMLAttributes<HTMLDivElement>): JSX.Element {
  return <div className={cn('px-5 pb-5', className)} {...rest} />;
}

export function CardFooter({ className, ...rest }: HTMLAttributes<HTMLDivElement>): JSX.Element {
  return (
    <div
      className={cn('flex flex-wrap items-center gap-3 border-t border-border px-5 py-4', className)}
      {...rest}
    />
  );
}
