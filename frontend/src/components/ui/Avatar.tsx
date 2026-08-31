import { cn } from '@/lib/cn';

/**
 * genesis-DESIGN.md § Components > Avatar Bubble: circular, 9999px radius, a
 * two-letter monogram at medium weight.
 *
 * Genesis specifies tinted backgrounds ("light green for JB, light blue for AF"),
 * which its own Do rule forbids: "use indigo only for interactive elements — never
 * for decoration", and the palette admits no other chromatic colour. An avatar is
 * decoration, so the monogram uses the neutral chip surface instead. Recorded in
 * LIMITATIONS.md as deviation D5.
 *
 * The cursor-pointer motif Genesis attaches to avatars signals live multi-user
 * presence, which this product has no backend support for, so it is not drawn.
 */

function monogram(nameOrEmail: string): string {
  const cleaned = nameOrEmail.trim();
  if (cleaned.length === 0) return '?';

  const words = cleaned.split(/\s+/).filter(Boolean);
  if (words.length >= 2) {
    const first = words[0]?.[0] ?? '';
    const second = words[1]?.[0] ?? '';
    return (first + second).toUpperCase();
  }
  // An email address: take the first two characters of the local part.
  const local = cleaned.split('@')[0] ?? cleaned;
  return local.slice(0, 2).toUpperCase();
}

export function Avatar({
  name,
  size = 'md',
  className,
}: {
  name: string;
  size?: 'sm' | 'md';
  className?: string;
}): JSX.Element {
  return (
    <span
      aria-hidden="true"
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-pill bg-chip-surface font-medium text-chip-text',
        size === 'sm' ? 'h-8 w-8 text-caption' : 'h-10 w-10 text-control',
        className,
      )}
    >
      {monogram(name)}
    </span>
  );
}
