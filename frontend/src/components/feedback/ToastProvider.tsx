import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { CheckCircle2, X, AlertTriangle } from 'lucide-react';
import { toastVariants } from '@/lib/motion';
import { cn } from '@/lib/cn';

/**
 * One live region for the whole app, mounted before any toast is inserted so
 * screen readers actually announce them. Confirmations are polite and auto-dismiss
 * after 5s; failures are assertive and stay until dismissed, because a message the
 * user needs to act on should not disappear while they are reading it.
 *
 * At most three are shown; a fourth evicts the oldest.
 */

type ToastTone = 'success' | 'error';

interface Toast {
  id: number;
  tone: ToastTone;
  message: string;
}

interface ToastContextValue {
  notify: (message: string, tone?: ToastTone) => void;
  success: (message: string) => void;
  failure: (message: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const MAX_VISIBLE = 3;
const AUTO_DISMISS_MS = 5000;

export function ToastProvider({ children }: { children: React.ReactNode }): JSX.Element {
  const reduced = useReducedMotion() ?? false;
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const notify = useCallback(
    (message: string, tone: ToastTone = 'success') => {
      const id = nextId.current;
      nextId.current += 1;

      setToasts((current) => {
        const next = [...current, { id, tone, message }];
        return next.length > MAX_VISIBLE ? next.slice(next.length - MAX_VISIBLE) : next;
      });

      if (tone === 'success') {
        window.setTimeout(() => dismiss(id), AUTO_DISMISS_MS);
      }
    },
    [dismiss],
  );

  const value = useMemo<ToastContextValue>(
    () => ({
      notify,
      success: (message: string) => notify(message, 'success'),
      failure: (message: string) => notify(message, 'error'),
    }),
    [notify],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}

      <div
        className="pointer-events-none fixed inset-x-0 bottom-0 z-40 flex flex-col items-center gap-3 p-4 sm:items-end"
        aria-live="polite"
        aria-atomic="false"
      >
        <AnimatePresence initial={false}>
          {toasts.map((toast) => (
            <motion.div
              key={toast.id}
              layout={!reduced}
              variants={toastVariants(reduced)}
              initial="hidden"
              animate="visible"
              exit="exit"
              role={toast.tone === 'error' ? 'alert' : 'status'}
              className={cn(
                'pointer-events-auto flex w-full max-w-[420px] items-start gap-3',
                'rounded-panel border bg-surface px-4 py-3 shadow-elevated',
                toast.tone === 'error' ? 'border-error' : 'border-border',
              )}
            >
              {toast.tone === 'error' ? (
                <AlertTriangle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-error" />
              ) : (
                <CheckCircle2 aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-success" />
              )}
              <p className="flex-1 text-small text-ink break-value">{toast.message}</p>
              <button
                type="button"
                onClick={() => dismiss(toast.id)}
                aria-label="Dismiss notification"
                className="-mr-1 -mt-1 rounded-control p-1 text-muted transition-colors duration-base hover:text-ink"
              >
                <X aria-hidden="true" className="h-4 w-4" />
              </button>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (context === null) throw new Error('useToast must be used inside a ToastProvider');
  return context;
}
