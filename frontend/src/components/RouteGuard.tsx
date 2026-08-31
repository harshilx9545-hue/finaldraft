import { useEffect } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useSession } from '@/session/SessionProvider';
import { useToast } from '@/components/feedback/ToastProvider';
import { homeFor, roleMayEnter } from '@/nav/navModel';

/**
 * Route admission, decided from the role in the most recent /api/me response.
 *
 * Never from a JWT claim: the backend re-reads role and gym from the database on
 * every request, so a token's `role` claim can be stale and grants nothing. This
 * mirrors that.
 *
 * This is a UX guard, not a security boundary. A mistake here produces a backend
 * 403, not an unauthorised effect.
 */

export function RequireAuth({ children }: { children: React.ReactNode }): JSX.Element {
  const { status } = useSession();
  const location = useLocation();

  if (status === 'loading') {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex min-h-screen items-center justify-center bg-background"
      >
        <span className="text-small text-muted">Restoring your session…</span>
      </div>
    );
  }

  if (status === 'anonymous') {
    return <Navigate to="/sign-in" replace state={{ from: location.pathname }} />;
  }

  return <>{children}</>;
}

export function RequireRole({ children }: { children: React.ReactNode }): JSX.Element {
  const { role } = useSession();
  const location = useLocation();
  const toast = useToast();

  const permitted = roleMayEnter(role, location.pathname);

  useEffect(() => {
    if (!permitted) toast.failure('That area is not available for your role.');
  }, [permitted, toast]);

  if (!permitted) {
    // Replace the refused entry so Back does not bounce between the two.
    return <Navigate to={homeFor(role)} replace />;
  }

  return <>{children}</>;
}

/** Keeps a signed-in user off the sign-in and registration surfaces. */
export function RedirectIfAuthenticated({
  children,
}: {
  children: React.ReactNode;
}): JSX.Element {
  const { status, role } = useSession();

  if (status === 'loading') {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex min-h-screen items-center justify-center bg-background"
      >
        <span className="text-small text-muted">Restoring your session…</span>
      </div>
    );
  }

  if (status === 'authenticated') return <Navigate to={homeFor(role)} replace />;

  return <>{children}</>;
}
