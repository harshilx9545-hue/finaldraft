import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { clearTokens, hasSession, loadTokensFromStorage, onSessionEnded } from '@/api/client';
import { logout as apiLogout } from '@/api/auth';
import { getMe } from '@/api/resources';
import type { Me, Role } from '@/api/types';
import { mapFailure, SESSION_ENDED_MESSAGE } from '@/lib/errors';

/**
 * Holds the token-backed session and the `/api/me` payload it resolves to.
 *
 * Role and tenant are read from `/api/me` on every session start and never from a
 * JWT claim, mirroring the backend: `core/permissions.py` re-reads the role and
 * gym from the database each request, so the access token's `role` and `gym_id`
 * claims grant nothing and must not be trusted here either.
 */

export type SessionStatus = 'loading' | 'authenticated' | 'anonymous';

interface SessionContextValue {
  status: SessionStatus;
  me: Me | null;
  role: Role | null;
  /** Message to show on the sign-in surface after an involuntary sign-out. */
  endedMessage: string | null;
  clearEndedMessage: () => void;
  /** Called after login/registration has stored tokens, to resolve /api/me. */
  establish: () => Promise<void>;
  signOut: () => Promise<void>;
  refreshMe: () => Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }): JSX.Element {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<SessionStatus>('loading');
  const [me, setMe] = useState<Me | null>(null);
  const [endedMessage, setEndedMessage] = useState<string | null>(null);
  const previousIdentity = useRef<string | null>(null);

  /** Drop every cached backend response. Prevents cross-role and cross-tenant bleed. */
  const purgeCaches = useCallback(() => {
    queryClient.cancelQueries();
    queryClient.clear();
  }, [queryClient]);

  const applyMe = useCallback(
    (next: Me) => {
      // Requirement: if the role or the tenant changed between two /api/me reads,
      // discard every cached response before rendering anything authenticated.
      const identity = `${next.role}:${next.gym?.id ?? 'none'}`;
      if (previousIdentity.current !== null && previousIdentity.current !== identity) {
        purgeCaches();
      }
      previousIdentity.current = identity;
      setMe(next);
      setStatus('authenticated');
    },
    [purgeCaches],
  );

  const establish = useCallback(async () => {
    try {
      applyMe(await getMe());
      setEndedMessage(null);
    } catch (error) {
      // A session whose /api/me does not resolve is not a session.
      clearTokens();
      previousIdentity.current = null;
      setMe(null);
      setStatus('anonymous');
      setEndedMessage(mapFailure(error).message);
      throw error;
    }
  }, [applyMe]);

  const refreshMe = useCallback(async () => {
    if (!hasSession()) return;
    try {
      applyMe(await getMe());
    } catch {
      /* The client's 401 handling already ends the session where appropriate. */
    }
  }, [applyMe]);

  const signOut = useCallback(async () => {
    await apiLogout();
    purgeCaches();
    previousIdentity.current = null;
    setMe(null);
    setStatus('anonymous');
    setEndedMessage(null);
  }, [purgeCaches]);

  // Restore a session on first mount, so a reload does not sign the user out.
  useEffect(() => {
    loadTokensFromStorage();
    if (!hasSession()) {
      setStatus('anonymous');
      return;
    }
    void establish().catch(() => {
      /* establish() has already routed to anonymous with a message. */
    });
  }, [establish]);

  // The API client ends the session when a refresh fails or a token is invalid.
  useEffect(
    () =>
      onSessionEnded(() => {
        purgeCaches();
        previousIdentity.current = null;
        setMe(null);
        setStatus('anonymous');
        setEndedMessage(SESSION_ENDED_MESSAGE);
      }),
    [purgeCaches],
  );

  const value = useMemo<SessionContextValue>(
    () => ({
      status,
      me,
      role: me?.role ?? null,
      endedMessage,
      clearEndedMessage: () => setEndedMessage(null),
      establish,
      signOut,
      refreshMe,
    }),
    [status, me, endedMessage, establish, signOut, refreshMe],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const context = useContext(SessionContext);
  if (context === null) {
    throw new Error('useSession must be used inside a SessionProvider');
  }
  return context;
}

/** The signed-in user, for surfaces that only render when authenticated. */
export function useMe(): Me {
  const { me } = useSession();
  if (me === null) {
    throw new Error('useMe used outside an authenticated route');
  }
  return me;
}
