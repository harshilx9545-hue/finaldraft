import { useCallback, useEffect, useId, useRef, type ReactNode } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { X } from 'lucide-react';
import { Button } from './Button';
import { dialogVariants } from '@/lib/motion';

/**
 * A modal dialog with the accessibility behaviour that makes it usable:
 * focus moves in on open, Tab is confined while open, Escape closes without
 * submitting, and focus returns to whatever opened it.
 *
 * Elevation uses Genesis's Modal/Overlay recipe. Dialogs are one of the few things
 * Genesis allows a shadow on — its Don'ts reserve elevation for hover, focus,
 * dropdowns and modals.
 */

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), ' +
  'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children?: ReactNode;
  footer?: ReactNode;
}

export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
}: DialogProps): JSX.Element {
  const reduced = useReducedMotion() ?? false;
  const panelRef = useRef<HTMLDivElement | null>(null);
  const restoreFocusTo = useRef<HTMLElement | null>(null);
  const titleId = useId();
  const descriptionId = useId();

  // Remember the opener so focus can go back to it, and move focus inside.
  useEffect(() => {
    if (!open) return;
    restoreFocusTo.current = document.activeElement as HTMLElement | null;

    const panel = panelRef.current;
    const first = panel?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? panel)?.focus();

    return () => {
      const target = restoreFocusTo.current;
      // The opener may have unmounted; main is the documented fallback.
      if (target !== null && document.contains(target)) target.focus();
      else document.querySelector<HTMLElement>('main')?.focus();
    };
  }, [open]);

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== 'Tab') return;

      const panel = panelRef.current;
      if (panel === null) return;
      const focusable = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }
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
    },
    [onClose],
  );

  // Stop the page behind from scrolling while the dialog is up.
  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  return (
    <AnimatePresence>
      {open ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <motion.div
            className="absolute inset-0 bg-ink/40"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: reduced ? 0 : 0.14 }}
            onClick={onClose}
            aria-hidden="true"
          />
          <motion.div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            aria-describedby={description ? descriptionId : undefined}
            tabIndex={-1}
            onKeyDown={onKeyDown}
            variants={dialogVariants(reduced)}
            initial="hidden"
            animate="visible"
            exit="exit"
            className="relative z-10 w-full max-w-[560px] rounded-card border border-border bg-surface shadow-elevated"
          >
            <div className="flex items-start justify-between gap-4 px-5 pt-5">
              <div className="flex flex-col gap-1">
                <h2 id={titleId} className="font-display text-subhead font-bold text-ink">
                  {title}
                </h2>
                {description ? (
                  <p id={descriptionId} className="text-small text-muted">
                    {description}
                  </p>
                ) : null}
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={onClose}
                aria-label="Close dialog"
                className="-mr-2 -mt-1"
              >
                <X aria-hidden="true" className="h-4 w-4" />
              </Button>
            </div>
            {children ? <div className="px-5 py-4">{children}</div> : null}
            {footer ? (
              <div className="flex flex-wrap items-center justify-end gap-3 border-t border-border px-5 py-4">
                {footer}
              </div>
            ) : null}
          </motion.div>
        </div>
      ) : null}
    </AnimatePresence>
  );
}
