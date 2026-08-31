import { useCallback, useEffect, useRef, useState } from 'react';
import type { FieldValues, UseFormSetError, Path } from 'react-hook-form';
import { mapFailure, retryAfterSeconds, type MappedFailure } from './errors';

/**
 * Routes a backend failure into a form.
 *
 * The backend lifts the first offending field into `details.field`, so a
 * VALIDATION_ERROR can usually be attached to the exact control that caused it.
 * When it names no field, or names one this form does not render, the message goes
 * to form level rather than being dropped.
 *
 * 429 gets its own treatment: the submit control is held disabled for the
 * `retry_after_seconds` the backend reports, counting down, because the login,
 * registration and password-reset routes are all throttled and a user who keeps
 * clicking makes it worse.
 */
export function useFormFailure<T extends FieldValues>(setError: UseFormSetError<T>) {
  const [formError, setFormError] = useState<string | null>(null);
  const [lockedSeconds, setLockedSeconds] = useState(0);
  const timer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearInterval(timer.current);
    },
    [],
  );

  const startLock = useCallback((seconds: number) => {
    setLockedSeconds(seconds);
    if (timer.current !== null) window.clearInterval(timer.current);
    timer.current = window.setInterval(() => {
      setLockedSeconds((current) => {
        if (current <= 1) {
          if (timer.current !== null) window.clearInterval(timer.current);
          timer.current = null;
          return 0;
        }
        return current - 1;
      });
    }, 1000);
  }, []);

  const handle = useCallback(
    (error: unknown, knownFields: readonly string[] = []): MappedFailure => {
      const failure = mapFailure(error);

      if (failure.code === 'RATE_LIMITED') {
        startLock(retryAfterSeconds(failure.details));
        setFormError(failure.message);
        return failure;
      }

      if (failure.field !== undefined && knownFields.includes(failure.field)) {
        setError(failure.field as Path<T>, { type: 'server', message: failure.message });
        setFormError(null);
        return failure;
      }

      setFormError(failure.message);
      return failure;
    },
    [setError, startLock],
  );

  return {
    formError,
    clearFormError: () => setFormError(null),
    handle,
    lockedSeconds,
    locked: lockedSeconds > 0,
  };
}
