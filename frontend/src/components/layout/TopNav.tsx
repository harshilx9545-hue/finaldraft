import { useEffect, useRef, useState } from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { LogOut, Menu, X } from 'lucide-react';
import { useSession } from '@/session/SessionProvider';
import { destinationsFor } from '@/nav/navModel';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { dropdownVariants } from '@/lib/motion';
import { cn } from '@/lib/cn';

/**
 * genesis-DESIGN.md § Components > Navigation:
 * "Sticky top nav with backdrop-blur, 56px height, 1px bottom border. Logo left,
 * links center (desktop) or hamburger drawer (mobile), user avatar dropdown right.
 * Nav links: 14px medium weight, hover shows bg-alt background."
 *
 * Destinations come entirely from the Nav_Model keyed on the role in /api/me. A
 * role that cannot reach a route never sees a link to it.
 *
 * Genesis also specifies a global ⌘K search bar here. It is deliberately absent:
 * no backend endpoint accepts a search term, so the control could not work. See
 * LIMITATIONS.md.
 */

const NAV_LINK =
  'rounded-control px-3 py-2 text-control font-medium no-underline transition-colors ' +
  'duration-base ease-standard';

export function TopNav(): JSX.Element {
  const { me, signOut } = useSession();
  const reduced = useReducedMotion() ?? false;
  const location = useLocation();

  const [menuOpen, setMenuOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const drawerButtonRef = useRef<HTMLButtonElement | null>(null);

  const destinations = destinationsFor(me?.role ?? null);

  // Close both on navigation, so a link tap does not leave the drawer covering
  // the page it just opened.
  useEffect(() => {
    setDrawerOpen(false);
    setMenuOpen(false);
  }, [location.pathname]);

  // Close the drawer when the viewport reaches the desktop breakpoint, and return
  // focus to the trigger if it is still mounted.
  useEffect(() => {
    if (!drawerOpen) return;
    const query = window.matchMedia('(min-width: 768px)');
    const onChange = (): void => {
      if (query.matches) {
        setDrawerOpen(false);
        drawerButtonRef.current?.focus();
      }
    };
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, [drawerOpen]);

  // Dismiss the avatar menu on outside click or Escape.
  useEffect(() => {
    if (!menuOpen) return;
    const onPointerDown = (event: MouseEvent): void => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) setMenuOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setMenuOpen(false);
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [menuOpen]);

  const displayName =
    me === null ? '' : `${me.first_name} ${me.last_name}`.trim() || me.email;

  return (
    <header className="sticky top-0 z-30 border-b border-border bg-surface/80 backdrop-blur">
      <nav aria-label="Main" className="container-page flex h-nav items-center gap-4">
        {/* Logo, left */}
        <Link
          to="/overview"
          className="font-display text-body font-bold tracking-[-0.03em] text-ink no-underline"
        >
          MK00
        </Link>

        {/* Links, centre, desktop only */}
        <ul className="mx-auto hidden list-none items-center gap-1 p-0 md:flex">
          {destinations.map((destination) => (
            <li key={destination.path}>
              <NavLink
                to={destination.path}
                className={({ isActive }) =>
                  cn(
                    NAV_LINK,
                    isActive
                      ? 'bg-chip-surface text-ink underline decoration-primary decoration-2 underline-offset-[6px]'
                      : 'text-muted hover:bg-background hover:text-ink',
                  )
                }
                aria-current={
                  location.pathname === destination.path ? 'page' : undefined
                }
              >
                {destination.label}
              </NavLink>
            </li>
          ))}
        </ul>

        {/* Avatar dropdown, right */}
        <div className="ml-auto flex items-center gap-2 md:ml-0">
          {me !== null ? (
            <div className="relative" ref={menuRef}>
              <button
                type="button"
                onClick={() => setMenuOpen((open) => !open)}
                aria-expanded={menuOpen}
                aria-haspopup="menu"
                className="flex items-center gap-2 rounded-pill p-1 transition-colors duration-base hover:bg-background"
              >
                <Avatar name={displayName} size="sm" />
                <span className="sr-only">Account menu for {me.email}</span>
              </button>

              <AnimatePresence>
                {menuOpen ? (
                  <motion.div
                    role="menu"
                    variants={dropdownVariants(reduced)}
                    initial="hidden"
                    animate="visible"
                    exit="exit"
                    className="absolute right-0 top-full mt-2 w-64 rounded-panel border border-border bg-surface p-2 shadow-elevated"
                  >
                    <div className="flex flex-col gap-1 border-b border-border px-3 pb-3 pt-2">
                      <span className="text-control font-medium text-ink break-value">
                        {me.email}
                      </span>
                      <span className="text-caption text-muted">
                        {me.role} &middot; {me.gym?.name ?? 'No gym'}
                      </span>
                    </div>
                    <button
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setMenuOpen(false);
                        void signOut();
                      }}
                      className="mt-1 flex w-full items-center gap-2 rounded-control px-3 py-2 text-control text-ink transition-colors duration-base hover:bg-background"
                    >
                      <LogOut aria-hidden="true" className="h-4 w-4" />
                      <span>Sign out</span>
                    </button>
                  </motion.div>
                ) : null}
              </AnimatePresence>
            </div>
          ) : null}

          {/* Hamburger, mobile only */}
          <Button
            ref={drawerButtonRef}
            variant="ghost"
            size="sm"
            className="md:hidden"
            onClick={() => setDrawerOpen(true)}
            aria-expanded={drawerOpen}
            aria-controls="mobile-nav-panel"
            aria-label="Open navigation"
          >
            <Menu aria-hidden="true" className="h-5 w-5" />
          </Button>
        </div>
      </nav>

      {/* Mobile drawer: full height, same destinations, same order. */}
      <AnimatePresence>
        {drawerOpen ? (
          <MobileDrawer
            onClose={() => {
              setDrawerOpen(false);
              drawerButtonRef.current?.focus();
            }}
          />
        ) : null}
      </AnimatePresence>
    </header>
  );
}

const FOCUSABLE = 'a[href], button:not([disabled])';

function MobileDrawer({ onClose }: { onClose: () => void }): JSX.Element {
  const { me } = useSession();
  const reduced = useReducedMotion() ?? false;
  const panelRef = useRef<HTMLDivElement | null>(null);
  const destinations = destinationsFor(me?.role ?? null);

  useEffect(() => {
    panelRef.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus();
  }, []);

  const onKeyDown = (event: React.KeyboardEvent): void => {
    if (event.key === 'Escape') {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== 'Tab') return;

    const panel = panelRef.current;
    if (panel === null) return;
    const focusable = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE));
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (first === undefined || last === undefined) return;

    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <motion.div
      id="mobile-nav-panel"
      ref={panelRef}
      onKeyDown={onKeyDown}
      initial={{ opacity: 0, y: reduced ? 0 : -4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: reduced ? 0 : -4 }}
      transition={{ duration: reduced ? 0 : 0.14 }}
      className="fixed inset-0 top-nav z-40 flex flex-col gap-2 bg-surface p-4 md:hidden"
    >
      <div className="flex items-center justify-between">
        <span className="text-caption font-medium uppercase tracking-[0.08em] text-muted">
          Navigation
        </span>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close navigation">
          <X aria-hidden="true" className="h-5 w-5" />
        </Button>
      </div>

      <ul className="flex list-none flex-col gap-1 p-0">
        {destinations.map((destination) => (
          <li key={destination.path}>
            <NavLink
              to={destination.path}
              onClick={onClose}
              className={({ isActive }) =>
                cn(
                  'flex min-h-11 items-center rounded-control px-3 text-body no-underline',
                  isActive ? 'bg-chip-surface font-medium text-ink' : 'text-muted',
                )
              }
            >
              {destination.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </motion.div>
  );
}
