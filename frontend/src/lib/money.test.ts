import { describe, expect, it } from 'vitest';
import {
  formatHsnSac,
  formatMinorUnits,
  formatMoney,
  formatTax,
  isValidMoneyInput,
  normaliseMoneyInput,
  NOT_APPLICABLE,
  UNAVAILABLE,
} from './money';

describe('formatMoney', () => {
  it('preserves every digit and the decimal position', () => {
    expect(formatMoney('0.00', 'INR')).toBe('INR 0.00');
    expect(formatMoney('0.01', 'INR')).toBe('INR 0.01');
    expect(formatMoney('1500.00', 'INR')).toBe('INR 1,500.00');
    expect(formatMoney('999.99', 'USD')).toBe('USD 999.99');
    expect(formatMoney('1000000.50', 'EUR')).toBe('EUR 1,000,000.50');
  });

  it('survives the backend maximum without losing a cent', () => {
    // 12 digits total, 2 after the point, is the widest the model allows. This is
    // the case a Number() round trip would corrupt.
    expect(formatMoney('9999999999.99', 'INR')).toBe('INR 9,999,999,999.99');
  });

  it('uses the currency supplied alongside the amount, never a default', () => {
    expect(formatMoney('10.00', 'GBP')).toBe('GBP 10.00');
    expect(formatMoney('10.00', undefined)).toBe(UNAVAILABLE);
    expect(formatMoney('10.00', '')).toBe(UNAVAILABLE);
  });

  it('refuses anything that is not a two-decimal string', () => {
    expect(formatMoney('1500', 'INR')).toBe(UNAVAILABLE);
    expect(formatMoney('1500.5', 'INR')).toBe(UNAVAILABLE);
    expect(formatMoney('1500.000', 'INR')).toBe(UNAVAILABLE);
    expect(formatMoney(null, 'INR')).toBe(UNAVAILABLE);
    expect(formatMoney(undefined, 'INR')).toBe(UNAVAILABLE);
    // Never renders as zero, which would be a factual claim the backend never made.
    expect(formatMoney('abc', 'INR')).not.toContain('0');
  });

  it('handles a negative amount without mangling the grouping', () => {
    expect(formatMoney('-1234.56', 'INR')).toBe('INR -1,234.56');
  });
});

describe('formatTax', () => {
  it('distinguishes tax-not-applicable from a tax of zero', () => {
    // The backend nulls these when the issuing gym has no GSTIN. Null and "0.00"
    // mean different things and must not render the same.
    expect(formatTax(null, 'INR')).toBe(NOT_APPLICABLE);
    expect(formatTax(undefined, 'INR')).toBe(NOT_APPLICABLE);
    expect(formatTax('0.00', 'INR')).toBe('INR 0.00');
    expect(formatTax(null, 'INR')).not.toBe(formatTax('0.00', 'INR'));
  });
});

describe('formatHsnSac', () => {
  it('reports an absent code as not applicable', () => {
    expect(formatHsnSac(null)).toBe(NOT_APPLICABLE);
    expect(formatHsnSac('')).toBe(NOT_APPLICABLE);
    expect(formatHsnSac('998341')).toBe('998341');
  });
});

describe('formatMinorUnits', () => {
  it('labels the gateway amount so it cannot be read as a price', () => {
    const rendered = formatMinorUnits(150000, 'INR');
    expect(rendered).toContain('150000');
    expect(rendered).toContain('minor units');
    // Crucially not "INR 1,500.00" — that would imply it is a display amount.
    expect(rendered).not.toBe('INR 1,500.00');
  });
});

describe('money input', () => {
  it('accepts what the backend accepts and rejects the rest', () => {
    expect(isValidMoneyInput('0')).toBe(true);
    expect(isValidMoneyInput('1500')).toBe(true);
    expect(isValidMoneyInput('1500.5')).toBe(true);
    expect(isValidMoneyInput('1500.50')).toBe(true);
    expect(isValidMoneyInput('9999999999.99')).toBe(true);
    expect(isValidMoneyInput('1500.505')).toBe(false);
    expect(isValidMoneyInput('12345678901')).toBe(false);
    expect(isValidMoneyInput('-5')).toBe(false);
    expect(isValidMoneyInput('abc')).toBe(false);
  });

  it('pads to two decimals as text, without arithmetic', () => {
    expect(normaliseMoneyInput('1500')).toBe('1500.00');
    expect(normaliseMoneyInput('1500.5')).toBe('1500.50');
    expect(normaliseMoneyInput('1500.50')).toBe('1500.50');
    expect(normaliseMoneyInput('0')).toBe('0.00');
  });
});
