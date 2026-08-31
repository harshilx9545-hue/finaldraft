import type { Config } from 'tailwindcss';

/**
 * Every theme key below resolves to a CSS custom property declared in
 * src/styles/tokens.css, which is derived from genesis-DESIGN.md. This file is
 * the only place Tailwind learns about the design system, and tokens.css is the
 * only place literal values appear. A component that needs a colour, radius,
 * spacing step or type size uses a utility backed by one of these keys.
 */
const config: Config = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    // Replaced rather than extended: Tailwind's default palette is not part of
    // this design system, and leaving it in place would let a component reach
    // for bg-blue-500 and silently drift.
    colors: {
      transparent: 'transparent',
      current: 'currentColor',
      primary: {
        DEFAULT: 'var(--color-primary)',
        hover: 'var(--color-primary-hover)',
      },
      secondary: 'var(--color-secondary)',
      neutral: 'var(--color-neutral)',
      background: 'var(--color-background)',
      surface: 'var(--color-surface)',
      ink: 'var(--color-text-primary)',
      muted: 'var(--color-text-secondary)',
      border: 'var(--color-border)',
      success: 'var(--color-success)',
      warning: 'var(--color-warning)',
      error: 'var(--color-error)',
      chip: {
        surface: 'var(--color-chip-surface)',
        text: 'var(--color-chip-text)',
      },
    },
    fontFamily: {
      display: 'var(--font-display)',
      body: 'var(--font-body)',
      mono: 'var(--font-mono)',
    },
    fontSize: {
      display: ['var(--text-display)', { lineHeight: '1.05', letterSpacing: 'var(--tracking-display)' }],
      headline: ['var(--text-headline)', { lineHeight: '1.08', letterSpacing: 'var(--tracking-display)' }],
      section: ['var(--text-section)', { lineHeight: '1.2', letterSpacing: 'var(--tracking-heading)' }],
      subhead: ['var(--text-subhead)', { lineHeight: '1.3', letterSpacing: 'var(--tracking-heading)' }],
      body: ['var(--text-body)', { lineHeight: '1.55' }],
      control: ['var(--text-control)', { lineHeight: '1.4' }],
      small: ['var(--text-small)', { lineHeight: '1.5' }],
      caption: ['var(--text-caption)', { lineHeight: '1.45' }],
      overline: ['var(--text-overline)', { lineHeight: '1.4', letterSpacing: 'var(--tracking-overline)' }],
    },
    fontWeight: {
      regular: 'var(--weight-regular)',
      medium: 'var(--weight-medium)',
      bold: 'var(--weight-bold)',
    },
    spacing: {
      0: '0px',
      1: 'var(--spacing-4)',
      2: 'var(--spacing-8)',
      3: 'var(--spacing-12)',
      4: 'var(--spacing-16)',
      5: 'var(--spacing-20)',
      6: 'var(--spacing-24)',
      8: 'var(--spacing-32)',
      10: 'var(--spacing-40)',
      12: 'var(--spacing-48)',
      16: 'var(--spacing-64)',
      20: 'var(--spacing-80)',
      24: 'var(--spacing-96)',
      nav: 'var(--nav-height)',
    },
    borderRadius: {
      none: '0px',
      chip: 'var(--radius-chip)',
      control: 'var(--radius-control)',
      panel: 'var(--radius-panel)',
      card: 'var(--radius-card)',
      pill: 'var(--radius-pill)',
    },
    borderWidth: { DEFAULT: '1px', 0: '0px', 1: '1px', 2: '2px' },
    boxShadow: {
      none: 'none',
      'card-hover': 'var(--shadow-card-hover)',
      'button-hover': 'var(--shadow-button-hover)',
      elevated: 'var(--shadow-elevated)',
      focus: 'var(--ring-focus)',
    },
    maxWidth: { container: 'var(--container-max)', prose: '68ch', none: 'none', full: '100%' },
    transitionDuration: {
      fast: 'var(--duration-fast)',
      DEFAULT: 'var(--duration-base)',
      base: 'var(--duration-base)',
      slow: 'var(--duration-slow)',
      0: '0ms',
    },
    transitionTimingFunction: { standard: 'var(--ease-standard)' },
    screens: { sm: '640px', md: '768px', lg: '1024px', xl: '1280px' },
    extend: {
      gridTemplateColumns: {
        'auto-fill-cards': 'repeat(auto-fill, minmax(280px, 1fr))',
      },
    },
  },
  plugins: [],
};

export default config;
