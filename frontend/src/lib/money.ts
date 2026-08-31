/**
 * Money rendering that never converts a backend decimal string to a number.
 *
 * The backend serialises every DecimalField as a string ("1500.00") because
 * `COERCE_DECIMAL_TO_STRING` is left at its DRF default. A `Number()` round trip
 * on a 12-digit decimal can lose the last cent, and these are invoice totals, so
 * every operation here is textual. There is exactly one place in the codebase
 * permitted to produce a number from one of these strings — the chart geometry
 * module — and it may only feed plotting coordinates.
 */

/** At most 12 total digits, exactly 2 after the point, per the model fields. */
const DECIMAL = /^-?\d{1,10}\.\d{2}$/;

/** Shown instead of a figure when the backend value is unusable. Never "0.00". */
export const UNAVAILABLE = 'Unavailable';
/** Shown for a null tax field, which means "not applicable" — not zero. */
export const NOT_APPLICABLE = 'Not applicable';

export function isDecimalString(value: unknown): value is string {
  return typeof value === 'string' && DECIMAL.test(value);
}

/** Insert thousands separators into a run of digits, right to left, as text. */
function groupDigits(digits: string): string {
  let out = '';
  for (let i = 0; i < digits.length; i += 1) {
    const fromRight = digits.length - i;
    out += digits[i];
    if (fromRight > 1 && fromRight % 3 === 1) out += ',';
  }
  return out;
}

/**
 * Render a backend decimal string with its currency code.
 *
 *   formatMoney('1500.00', 'INR') -> 'INR 1,500.00'
 *
 * The currency code must come from the same response object as the amount; there
 * is deliberately no default, because guessing a currency on an invoice is worse
 * than showing nothing.
 */
export function formatMoney(amount: string | null | undefined, currency: string | null | undefined): string {
  if (!isDecimalString(amount)) return UNAVAILABLE;
  if (typeof currency !== 'string' || currency.length === 0) return UNAVAILABLE;

  const negative = amount.startsWith('-');
  const unsigned = negative ? amount.slice(1) : amount;
  const pointAt = unsigned.indexOf('.');
  const whole = unsigned.slice(0, pointAt);
  const fraction = unsigned.slice(pointAt + 1);

  return `${currency} ${negative ? '-' : ''}${groupDigits(whole)}.${fraction}`;
}

/**
 * A tax field. Null means the issuing gym has no GSTIN and tax does not apply,
 * which the backend deliberately distinguishes from a zero amount.
 */
export function formatTax(amount: string | null | undefined, currency: string | null | undefined): string {
  if (amount === null || amount === undefined) return NOT_APPLICABLE;
  return formatMoney(amount, currency);
}

/** An HSN/SAC code. Null carries the same "not applicable" meaning as tax. */
export function formatHsnSac(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return NOT_APPLICABLE;
  return value;
}

/**
 * The gateway order amount, in minor units (paise for INR). Labelled as such
 * wherever shown, and never presented as a human-readable amount.
 */
export function formatMinorUnits(amountMinor: number, currency: string): string {
  return `${amountMinor} (${currency} minor units)`;
}

/**
 * Validate a money value typed by a user, as text. Kept as a string all the way
 * into the request body so nothing is reformatted or rounded on the way.
 */
const MONEY_INPUT = /^\d{1,10}(\.\d{1,2})?$/;

export function isValidMoneyInput(value: string): boolean {
  return MONEY_INPUT.test(value.trim());
}

/** Normalise a valid user-typed amount to the two-decimal form the API expects. */
export function normaliseMoneyInput(value: string): string {
  const trimmed = value.trim();
  if (!MONEY_INPUT.test(trimmed)) return trimmed;
  const pointAt = trimmed.indexOf('.');
  if (pointAt === -1) return `${trimmed}.00`;
  const fraction = trimmed.slice(pointAt + 1);
  return fraction.length === 1 ? `${trimmed}0` : trimmed;
}
