import { AlertCircle, Inbox } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { mapFailure } from '@/lib/errors';

/**
 * Empty and error states.
 *
 * An empty state offers a create action ONLY when the backend has a create route
 * that admits the signed-in role. Where it has none — invoices, for instance, which
 * the backend issues itself — the state says so instead of showing a button that
 * cannot work.
 */

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}): JSX.Element {
  return (
    <div className="flex flex-col items-center gap-4 px-6 py-16 text-center">
      <span className="flex h-12 w-12 items-center justify-center rounded-pill bg-chip-surface">
        <Inbox aria-hidden="true" className="h-5 w-5 text-chip-text" />
      </span>
      <div className="flex flex-col gap-2">
        <h3 className="font-display text-subhead font-bold text-ink">{title}</h3>
        <p className="mx-auto max-w-prose text-small text-muted">{description}</p>
      </div>
      {action}
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
  title = 'That did not load',
}: {
  error: unknown;
  onRetry?: () => void;
  title?: string;
}): JSX.Element {
  const failure = mapFailure(error);

  return (
    <div className="flex flex-col items-center gap-4 px-6 py-16 text-center" role="alert">
      <span className="flex h-12 w-12 items-center justify-center rounded-pill bg-chip-surface">
        <AlertCircle aria-hidden="true" className="h-5 w-5 text-error" />
      </span>
      <div className="flex flex-col gap-2">
        <h3 className="font-display text-subhead font-bold text-ink">{title}</h3>
        {/* The mapped message only. Never a status line, a URL or a stack trace. */}
        <p className="mx-auto max-w-prose text-small text-muted">{failure.message}</p>
      </div>
      {onRetry ? (
        <Button variant="secondary" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}

/**
 * The 404 surface. Its text is fixed and says nothing about permissions,
 * ownership or tenancy.
 *
 * This matters more than it looks: the backend returns a byte-identical 404 for an
 * id that does not exist and an id that belongs to another gym, specifically so a
 * client cannot probe for existence. Wording this as "you don't have access to
 * this member" would hand that information straight back.
 */
export function NotFoundState({ action }: { action?: React.ReactNode }): JSX.Element {
  return (
    <div className="flex flex-col items-center gap-4 px-6 py-16 text-center">
      <div className="flex flex-col gap-2">
        <h3 className="font-display text-subhead font-bold text-ink">Not found</h3>
        <p className="mx-auto max-w-prose text-small text-muted">We could not find that record.</p>
      </div>
      {action}
    </div>
  );
}
