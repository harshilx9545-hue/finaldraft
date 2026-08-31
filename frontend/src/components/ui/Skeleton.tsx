import { cn } from '@/lib/cn';

/**
 * Loading placeholders shaped like the content that replaces them.
 *
 * Genesis has no animated shimmer and its Don'ts rule out shadows on static
 * elements, so these are flat tinted blocks. They also do not pulse: the motion
 * rule forbids anything animating continuously, which a shimmer does by
 * definition.
 *
 * Collection skeletons render 25 rows because the backend's PAGE_SIZE is 25, so
 * the placeholder matches the page that arrives.
 */

export function Skeleton({ className }: { className?: string }): JSX.Element {
  return <div aria-hidden="true" className={cn('rounded-chip bg-chip-surface', className)} />;
}

export function SkeletonText({
  lines = 1,
  className,
}: {
  lines?: number;
  className?: string;
}): JSX.Element {
  return (
    <div className={cn('flex flex-col gap-2', className)}>
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton key={index} className={cn('h-4', index === lines - 1 ? 'w-2/3' : 'w-full')} />
      ))}
    </div>
  );
}

/** Matches the shape of a DataList: a caption, a header row, then `rows` rows. */
export function SkeletonTable({
  rows = 25,
  columns = 4,
  label,
}: {
  rows?: number;
  columns?: number;
  label: string;
}): JSX.Element {
  return (
    <div role="status" aria-live="polite" aria-busy="true" className="flex flex-col">
      <span className="sr-only">Loading {label}</span>
      <div className="flex gap-4 border-b border-border px-4 py-3">
        {Array.from({ length: columns }, (_, index) => (
          <Skeleton key={index} className="h-3 flex-1" />
        ))}
      </div>
      {Array.from({ length: rows }, (_, rowIndex) => (
        <div key={rowIndex} className="flex gap-4 border-b border-border px-4 py-4">
          {Array.from({ length: columns }, (_, colIndex) => (
            <Skeleton key={colIndex} className="h-4 flex-1" />
          ))}
        </div>
      ))}
    </div>
  );
}

/** Matches a field group: `fields` label-and-value pairs. */
export function SkeletonFields({
  fields = 6,
  label,
}: {
  fields?: number;
  label: string;
}): JSX.Element {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-busy="true"
      className="grid gap-6 sm:grid-cols-2"
    >
      <span className="sr-only">Loading {label}</span>
      {Array.from({ length: fields }, (_, index) => (
        <div key={index} className="flex flex-col gap-2">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-5 w-full" />
        </div>
      ))}
    </div>
  );
}

export function SkeletonStats({ count = 4 }: { count?: number }): JSX.Element {
  return (
    <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="rounded-card border border-border bg-surface p-5">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="mt-4 h-8 w-16" />
        </div>
      ))}
    </div>
  );
}
