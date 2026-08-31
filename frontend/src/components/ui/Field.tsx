import { forwardRef, useId, type InputHTMLAttributes, type SelectHTMLAttributes } from 'react';
import { cn } from '@/lib/cn';

/**
 * genesis-DESIGN.md § Components > Inputs.
 *
 * "1px subtle border, surface background, 6px radius, 10px vertical and 14px
 * horizontal padding, 14px font size. Focus: border turns indigo with a 3px rgba
 * ring. Error: border turns red. Placeholder text uses muted color."
 *
 * Every field is labelled by a visible `<label>`; a placeholder is never the only
 * label. Errors are text, associated by aria-describedby, with aria-invalid set.
 */

const CONTROL =
  'w-full bg-surface text-ink text-control rounded-control border px-[14px] py-[10px] ' +
  'placeholder:text-neutral transition-[border-color,box-shadow] duration-base ease-standard ' +
  'focus:outline-none focus:border-primary focus:shadow-focus ' +
  'disabled:bg-chip-surface disabled:text-neutral disabled:cursor-not-allowed';

export interface FieldShellProps {
  label: string;
  htmlFor: string;
  required?: boolean;
  error?: string | undefined;
  hint?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}

export function FieldShell({
  label,
  htmlFor,
  required = false,
  error,
  hint,
  children,
  className,
}: FieldShellProps): JSX.Element {
  return (
    <div className={cn('flex flex-col gap-2', className)}>
      <label htmlFor={htmlFor} className="text-small font-medium text-ink">
        {label}
        {required ? (
          <span className="text-error" aria-hidden="true">
            {' '}
            *
          </span>
        ) : null}
        {required ? <span className="sr-only"> (required)</span> : null}
      </label>
      {children}
      {hint ? (
        <p id={`${htmlFor}-hint`} className="text-caption text-muted break-value">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={`${htmlFor}-error`} className="text-caption text-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export interface TextFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'id'> {
  label: string;
  error?: string | undefined;
  hint?: React.ReactNode;
}

export const TextField = forwardRef<HTMLInputElement, TextFieldProps>(function TextField(
  { label, error, hint, required, className, ...rest },
  ref,
) {
  const id = useId();
  const describedBy = [hint ? `${id}-hint` : null, error ? `${id}-error` : null]
    .filter(Boolean)
    .join(' ');

  return (
    <FieldShell
      label={label}
      htmlFor={id}
      required={required}
      error={error}
      hint={hint}
      className={className}
    >
      <input
        ref={ref}
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy.length > 0 ? describedBy : undefined}
        aria-required={required || undefined}
        required={required}
        className={cn(CONTROL, error ? 'border-error' : 'border-border')}
        {...rest}
      />
    </FieldShell>
  );
});

export interface SelectFieldProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'id'> {
  label: string;
  error?: string | undefined;
  hint?: React.ReactNode;
}

export const SelectField = forwardRef<HTMLSelectElement, SelectFieldProps>(function SelectField(
  { label, error, hint, required, className, children, ...rest },
  ref,
) {
  const id = useId();
  const describedBy = [hint ? `${id}-hint` : null, error ? `${id}-error` : null]
    .filter(Boolean)
    .join(' ');

  return (
    <FieldShell
      label={label}
      htmlFor={id}
      required={required}
      error={error}
      hint={hint}
      className={className}
    >
      <select
        ref={ref}
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy.length > 0 ? describedBy : undefined}
        aria-required={required || undefined}
        required={required}
        className={cn(CONTROL, error ? 'border-error' : 'border-border')}
        {...rest}
      >
        {children}
      </select>
    </FieldShell>
  );
});

export interface CheckFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'id' | 'type'> {
  label: string;
  hint?: string;
}

export const CheckField = forwardRef<HTMLInputElement, CheckFieldProps>(function CheckField(
  { label, hint, className, ...rest },
  ref,
) {
  const id = useId();
  return (
    <div className={cn('flex items-start gap-3', className)}>
      <input
        ref={ref}
        id={id}
        type="checkbox"
        aria-describedby={hint ? `${id}-hint` : undefined}
        className="mt-0.5 h-5 w-5 shrink-0 rounded-chip border border-border accent-primary"
        {...rest}
      />
      <div className="flex flex-col gap-1">
        <label htmlFor={id} className="text-small font-medium text-ink">
          {label}
        </label>
        {hint ? (
          <p id={`${id}-hint`} className="text-caption text-muted">
            {hint}
          </p>
        ) : null}
      </div>
    </div>
  );
});

/** A read-only value with a visible label, for fields the backend will not accept. */
export function ReadOnlyField({
  label,
  value,
  hint,
  className,
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  className?: string;
}): JSX.Element {
  return (
    <div className={cn('flex flex-col gap-1', className)}>
      <span className="text-caption font-medium uppercase tracking-[0.08em] text-muted">
        {label}
      </span>
      <span className="text-body text-ink break-value">{value}</span>
      {hint ? <p className="text-caption text-muted">{hint}</p> : null}
    </div>
  );
}
