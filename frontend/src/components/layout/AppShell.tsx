import { Outlet } from 'react-router-dom';
import { motion, useReducedMotion } from 'framer-motion';
import { TopNav } from './TopNav';
import { pageVariants } from '@/lib/motion';
import { cn } from '@/lib/cn';

/**
 * The authenticated chrome: a skip link, the sticky nav, and a single <main>.
 *
 * Section rhythm follows Genesis: 32px on mobile, 48px at tablet, 64px at desktop,
 * inside a 1280px container with 24px of horizontal padding.
 */
export function AppShell(): JSX.Element {
  const reduced = useReducedMotion() ?? false;

  return (
    <div className="min-h-screen bg-background">
      <a
        href="#main"
        className="sr-only rounded-control bg-surface px-4 py-2 text-control font-medium text-primary focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50"
      >
        Skip to content
      </a>

      <TopNav />

      <motion.main
        id="main"
        tabIndex={-1}
        variants={pageVariants(reduced)}
        initial="hidden"
        animate="visible"
        className="container-page py-8 md:py-12 lg:py-16 focus:outline-none"
      >
        <Outlet />
      </motion.main>
    </div>
  );
}

/** The unauthenticated shell: no nav, centred card, same tokens. */
export function AuthShell({ children }: { children: React.ReactNode }): JSX.Element {
  const reduced = useReducedMotion() ?? false;

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <a
        href="#main"
        className="sr-only rounded-control bg-surface px-4 py-2 text-control font-medium text-primary focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50"
      >
        Skip to content
      </a>

      <header className="container-page flex h-nav items-center">
        <span className="font-display text-body font-bold tracking-[-0.03em] text-ink">MK00</span>
      </header>

      <motion.main
        id="main"
        tabIndex={-1}
        variants={pageVariants(reduced)}
        initial="hidden"
        animate="visible"
        className="container-page flex flex-1 items-start justify-center py-12 focus:outline-none md:py-16"
      >
        <div className="w-full max-w-[520px]">{children}</div>
      </motion.main>
    </div>
  );
}

/** A page title block. `heading` is 32px, Genesis's section-heading step. */
export function PageHeader({
  title,
  description,
  actions,
  className,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}): JSX.Element {
  return (
    <div className={cn('flex flex-wrap items-start justify-between gap-4', className)}>
      <div className="flex flex-col gap-2">
        <h1 className="font-display text-section font-bold text-ink">{title}</h1>
        {description ? (
          <p className="max-w-prose text-body text-muted break-value">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-3">{actions}</div> : null}
    </div>
  );
}

/** Vertical rhythm between major page sections, per Genesis's section spacing. */
export function PageSections({ children }: { children: React.ReactNode }): JSX.Element {
  return <div className="flex flex-col gap-8 md:gap-12 lg:gap-16">{children}</div>;
}
