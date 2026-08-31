import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from '@/components/layout/AppShell';
import { RedirectIfAuthenticated, RequireAuth, RequireRole } from '@/components/RouteGuard';
import { NotFoundState } from '@/components/data/States';
import { TextLink } from '@/components/ui/TextLink';

/**
 * Routes, one lazily loaded chunk each.
 *
 * There is a route for every navigation destination and nothing else. No
 * placeholder route, no "coming soon" surface: a route that cannot show real
 * backend data does not exist here.
 *
 * `RequireRole` reads the role from /api/me and sends a refused navigation back to
 * that role's overview. It is a UX guard — the backend refuses the request anyway.
 */

const SignIn = lazy(() => import('@/pages/auth/SignIn'));
const RegisterOwner = lazy(() => import('@/pages/auth/RegisterOwner'));
const PasswordResetRequest = lazy(() => import('@/pages/auth/PasswordResetRequest'));
const PasswordResetConfirm = lazy(() => import('@/pages/auth/PasswordResetConfirm'));
const VerifyEmail = lazy(() => import('@/pages/auth/VerifyEmail'));

const Overview = lazy(() => import('@/pages/Overview'));
const Members = lazy(() => import('@/pages/Members'));
const MemberDetail = lazy(() => import('@/pages/MemberDetail'));
const MyMembership = lazy(() => import('@/pages/MyMembership'));
const Trainers = lazy(() => import('@/pages/Trainers'));
const MembershipPlans = lazy(() => import('@/pages/MembershipPlans'));
const Invoices = lazy(() => import('@/pages/Invoices'));
const InvoiceDetail = lazy(() => import('@/pages/InvoiceDetail'));
const GymPage = lazy(() => import('@/pages/Gym'));
const Profile = lazy(() => import('@/pages/Profile'));

function RouteFallback(): JSX.Element {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex min-h-[40vh] items-center justify-center"
    >
      <span className="text-small text-muted">Loading…</span>
    </div>
  );
}

export default function App(): JSX.Element {
  return (
    <Suspense fallback={<RouteFallback />}>
      <Routes>
        {/* Unauthenticated */}
        <Route
          path="/sign-in"
          element={
            <RedirectIfAuthenticated>
              <SignIn />
            </RedirectIfAuthenticated>
          }
        />
        <Route
          path="/register"
          element={
            <RedirectIfAuthenticated>
              <RegisterOwner />
            </RedirectIfAuthenticated>
          }
        />
        <Route path="/password-reset" element={<PasswordResetRequest />} />
        <Route path="/password-reset/confirm" element={<PasswordResetConfirm />} />
        <Route path="/verify-email" element={<VerifyEmail />} />

        {/* Authenticated */}
        <Route
          element={
            <RequireAuth>
              <AppShell />
            </RequireAuth>
          }
        >
          <Route path="/overview" element={<Overview />} />

          <Route
            path="/members"
            element={
              <RequireRole>
                <Members />
              </RequireRole>
            }
          />
          <Route
            path="/members/:id"
            element={
              <RequireRole>
                <MemberDetail />
              </RequireRole>
            }
          />
          <Route
            path="/my-membership"
            element={
              <RequireRole>
                <MyMembership />
              </RequireRole>
            }
          />
          <Route
            path="/trainers"
            element={
              <RequireRole>
                <Trainers />
              </RequireRole>
            }
          />
          <Route path="/membership-plans" element={<MembershipPlans />} />
          <Route
            path="/invoices"
            element={
              <RequireRole>
                <Invoices />
              </RequireRole>
            }
          />
          <Route
            path="/invoices/:id"
            element={
              <RequireRole>
                <InvoiceDetail />
              </RequireRole>
            }
          />
          <Route path="/gym" element={<GymPage />} />
          <Route path="/profile" element={<Profile />} />

          <Route
            path="*"
            element={
              <NotFoundState action={<TextLink to="/overview">Back to overview</TextLink>} />
            }
          />
        </Route>

        <Route path="/" element={<Navigate to="/overview" replace />} />
      </Routes>
    </Suspense>
  );
}
