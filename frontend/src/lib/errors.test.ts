import { describe, expect, it } from 'vitest';
import {
  ApiError,
  ERROR_CODES,
  NetworkFailure,
  NOT_FOUND_MESSAGE,
  parseEnvelope,
  retryAfterSeconds,
  UNEXPECTED_MESSAGE,
  mapFailure,
  type ErrorCode,
} from './errors';

function envelope(code: ErrorCode, message = 'Server said so.', details?: object) {
  return { error: { code, message, ...(details ? { details } : {}) } };
}

describe('the error code catalogue', () => {
  it('covers exactly the 22 codes the backend can emit', () => {
    // Property test 17 in the backend asserts the API emits nothing outside this
    // set. If the backend grows a code, this fails and the mapping gets updated
    // rather than silently falling through to "something went wrong".
    expect(ERROR_CODES).toHaveLength(22);
    expect(new Set(ERROR_CODES).size).toBe(22);
  });

  it('maps every code to a usable message', () => {
    for (const code of ERROR_CODES) {
      const failure = mapFailure(new ApiError(400, { code, message: 'Server said so.' }));
      expect(failure.message.length, code).toBeGreaterThan(0);
      expect(failure.message.length, code).toBeLessThanOrEqual(200);
      expect(failure.code, code).toBe(code);
    }
  });

  it('never leaks a stack trace, a method or a URL', () => {
    for (const code of ERROR_CODES) {
      const failure = mapFailure(new ApiError(500, { code, message: 'Server said so.' }));
      expect(failure.message).not.toMatch(/https?:\/\//);
      expect(failure.message).not.toMatch(/\b(GET|POST|PATCH|DELETE)\b/);
      expect(failure.message).not.toContain('    at ');
    }
  });
});

describe('parseEnvelope', () => {
  it('accepts the documented shape', () => {
    expect(parseEnvelope(envelope('FORBIDDEN'))).toEqual({
      code: 'FORBIDDEN',
      message: 'Server said so.',
      details: undefined,
    });
  });

  it('rejects anything off-contract', () => {
    expect(parseEnvelope(null)).toBeNull();
    expect(parseEnvelope('nope')).toBeNull();
    expect(parseEnvelope({})).toBeNull();
    expect(parseEnvelope({ error: {} })).toBeNull();
    expect(parseEnvelope({ error: { code: 'NOT_A_REAL_CODE', message: 'x' } })).toBeNull();
    expect(parseEnvelope({ error: { code: 'FORBIDDEN' } })).toBeNull();
  });
});

describe('mapFailure', () => {
  it('falls back to the unexpected message for an off-contract body', () => {
    const failure = mapFailure(new ApiError(500, null));
    expect(failure.message).toBe(UNEXPECTED_MESSAGE);
    expect(failure.failureClass).toBe('unexpected');
  });

  it('reports a request that never got a response', () => {
    const failure = mapFailure(new NetworkFailure());
    expect(failure.message).toContain('could not reach the server');
    expect(failure.code).toBeNull();
  });

  it('keeps a 404 free of any permissions language', () => {
    // The backend returns a byte-identical 404 for a nonexistent id and another
    // gym's id. Wording it as a permissions problem would hand back the existence
    // information that identical response exists to hide.
    const failure = mapFailure(
      new ApiError(404, { code: 'NOT_FOUND', message: 'You may not view member 42.' }),
    );
    expect(failure.message).toBe(NOT_FOUND_MESSAGE);
    expect(failure.message.toLowerCase()).not.toContain('permission');
    expect(failure.message.toLowerCase()).not.toContain('access');
    expect(failure.message).not.toContain('42');
  });

  it('prefers the server sentence for a 403, which is specific and actionable', () => {
    const failure = mapFailure(
      new ApiError(403, {
        code: 'FORBIDDEN',
        message: "This gym's subscription is not active.",
      }),
    );
    expect(failure.message).toBe("This gym's subscription is not active.");
  });

  it('surfaces the seat figures when the backend supplies them', () => {
    const failure = mapFailure(
      new ApiError(409, {
        code: 'SEAT_LIMIT_REACHED',
        message: 'Seat limit reached.',
        details: { seat_count: 50, limit: 50 },
      }),
    );
    expect(failure.message).toContain('50');
  });

  it('names the offending form control when the backend does', () => {
    const failure = mapFailure(
      new ApiError(400, {
        code: 'VALIDATION_ERROR',
        message: 'An account with this phone number already exists.',
        details: { field: 'phone' },
      }),
    );
    expect(failure.field).toBe('phone');
    expect(failure.message).toContain('phone number');
  });

  it('treats a rejected card field as our bug, not the user\'s', () => {
    const failure = mapFailure(new ApiError(400, { code: 'CARD_DATA_REJECTED', message: 'x' }));
    expect(failure.failureClass).toBe('frontend_defect');
  });

  it('marks the webhook-only signature code unreachable', () => {
    const failure = mapFailure(new ApiError(400, { code: 'SIGNATURE_INVALID', message: 'x' }));
    expect(failure.failureClass).toBe('unreachable');
  });

  it('classifies the three session-ending codes together', () => {
    for (const code of ['TOKEN_EXPIRED', 'TOKEN_INVALID', 'NOT_AUTHENTICATED'] as const) {
      expect(mapFailure(new ApiError(401, { code, message: 'x' })).failureClass).toBe(
        'session_ended',
      );
    }
  });
});

describe('retryAfterSeconds', () => {
  it('clamps a throttle wait into something sane', () => {
    expect(retryAfterSeconds({ retry_after_seconds: 30 })).toBe(30);
    expect(retryAfterSeconds({ retry_after_seconds: 0 })).toBe(1);
    expect(retryAfterSeconds({ retry_after_seconds: 99999 })).toBe(300);
    expect(retryAfterSeconds(undefined)).toBe(60);
    expect(retryAfterSeconds({})).toBe(60);
  });
});
