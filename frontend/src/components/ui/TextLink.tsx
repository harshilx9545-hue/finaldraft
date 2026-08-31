import { Link, type LinkProps } from 'react-router-dom';
import { cn } from '@/lib/cn';

/**
 * genesis-DESIGN.md § Components > Text Link with Arrow.
 *
 * Indigo text, no background or border. Genesis's Don'ts say inline links are not
 * underlined at rest — the arrow suffix carries the affordance — and underline
 * appears on hover. Keyboard focus also underlines, because a focus ring alone is
 * not always enough to say "this is a link".
 *
 * The arrow is aria-hidden so it does not end up in the accessible name.
 */

export interface TextLinkProps extends Omit<LinkProps, 'className'> {
  withArrow?: boolean;
  className?: string;
}

export function TextLink({
  withArrow = true,
  className,
  children,
  ...rest
}: TextLinkProps): JSX.Element {
  return (
    <Link
      className={cn(
        'inline-flex items-center gap-1 text-control font-medium text-primary',
        'no-underline hover:underline focus-visible:underline',
        'transition-colors duration-base ease-standard hover:text-primary-hover',
        className,
      )}
      {...rest}
    >
      <span>{children}</span>
      {withArrow ? <span aria-hidden="true">&rarr;</span> : null}
    </Link>
  );
}
