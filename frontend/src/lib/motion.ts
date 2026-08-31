import type { Variants } from 'framer-motion';

/**
 * Motion variants. Genesis's transition duration is 200ms and its movements are
 * small (a 1px button lift, a 2px card lift), so nothing here is showy.
 *
 * Every consumer passes the result of `useReducedMotion()` into these builders.
 * With reduced motion the element renders at its final position, opacity and
 * value immediately — the end state is identical either way, only the journey
 * differs. The global CSS rule in index.css zeroes plain CSS transitions too.
 */

export const DURATION = {
  fast: 0.14,
  base: 0.2,
  slow: 0.24,
  chart: 0.6,
  countUp: 0.8,
} as const;

/** The cubic bezier behind --ease-standard, as a tuple Framer Motion accepts. */
const EASE: [number, number, number, number] = [0.4, 0, 0.2, 1];

export function pageVariants(reduced: boolean): Variants {
  return {
    hidden: { opacity: 0, y: reduced ? 0 : 8 },
    visible: {
      opacity: 1,
      y: 0,
      transition: { duration: reduced ? 0 : DURATION.slow, ease: EASE },
    },
  };
}

/** Cards enter staggered, capped at eight so a long list does not crawl in. */
export function cardListVariants(reduced: boolean): Variants {
  return {
    hidden: {},
    visible: {
      transition: {
        staggerChildren: reduced ? 0 : 0.04,
        delayChildren: 0,
      },
    },
  };
}

export function cardVariants(reduced: boolean): Variants {
  return {
    hidden: { opacity: 0, y: reduced ? 0 : 8 },
    visible: {
      opacity: 1,
      y: 0,
      transition: { duration: reduced ? 0 : DURATION.slow, ease: EASE },
    },
  };
}

export function dialogVariants(reduced: boolean): Variants {
  return {
    hidden: { opacity: 0, scale: reduced ? 1 : 0.98 },
    visible: {
      opacity: 1,
      scale: 1,
      transition: { duration: reduced ? 0 : 0.18, ease: EASE },
    },
    exit: {
      opacity: 0,
      scale: reduced ? 1 : 0.98,
      transition: { duration: reduced ? 0 : 0.14, ease: EASE },
    },
  };
}

export function dropdownVariants(reduced: boolean): Variants {
  return {
    hidden: { opacity: 0, y: reduced ? 0 : -4 },
    visible: {
      opacity: 1,
      y: 0,
      transition: { duration: reduced ? 0 : DURATION.fast, ease: EASE },
    },
    exit: {
      opacity: 0,
      y: reduced ? 0 : -4,
      transition: { duration: reduced ? 0 : DURATION.fast, ease: EASE },
    },
  };
}

export function toastVariants(reduced: boolean): Variants {
  return {
    hidden: { opacity: 0, y: reduced ? 0 : 8 },
    visible: {
      opacity: 1,
      y: 0,
      transition: { duration: reduced ? 0 : DURATION.base, ease: EASE },
    },
    exit: {
      opacity: 0,
      y: reduced ? 0 : 8,
      transition: { duration: reduced ? 0 : DURATION.fast, ease: EASE },
    },
  };
}
