/**
 * The backend's error envelope, and the total mapping from its codes to messages.
 *
 * `core/exceptions.api_exception_handler` is the DRF EXCEPTION_HANDLER, so EVERY
 * non-2xx response in the API has the shape
 *   { "error": { "code": string, "message": string, "details"?: object } }
 * and property test 17 asserts the API can emit no code outside the 22 below.
 *
 * `details` is omitted entirely when empty, so every key must be treated as
 * optional. Validation failures lift the first offending field into
 * `details.field`; throttling sets `details.retry_after_seconds`; seat failures set
 * `details.seat_count` and `details.limit`.
 */

export const ERROR_CODES = [
  'INVALID_CREDENTIALS',
  'TOKEN_EXPIRED',
  'TOKEN_INVALID',
  'TOKEN_CONSUMED',
  'AUTH_UNAVAILABLE',
  'NOT_AUTHENTICATED',
  'FORBIDDEN',
  'NOT_FOUND',
  'VALIDATION_ERROR',
  'SEAT_LIMIT_REACHED',
  'PLAN_DOWNGRADE_BLOCKED',
  'SUBSCRIPTION_REQUIRED',
  'INVOICE_ALREADY_PAID',
  'INVOICE_IMMUTABLE',
  'CURRENCY_MISMATCH',
  'GATEWAY_ERROR',
  'CARD_DATA_REJECTED',
  'SIGNATURE_INVALID',
  'RATE_LIMITED',
  'METHOD_NOT_ALLOWED',
  'CONFLICT',
  'SERVER_ERROR',
] as const;

export type ErrorCode = (typeof ERROR_CODES)[number];

/**
 * How a failure should be treated, which is separate from what it says.
 * - user_actionable: the user can fix it and retry.
 * - session_ended:   the session is gone; route to sign-in.
 * - frontend_defect: we sent something we should never have sent.
 * - unexpected:      off-contract response.
 * - unreachable:     only reachable by the gateway webhook, never by this client.
 */
export type FailureClass =
  | 'user_actionable'
  | 'session_ended'
  | 'frontend_defect'
  | 'unexpected'
  | 'unreachable';

export interface ErrorDetails {
  field?: string;
  retry_after_seconds?: number;
  seat_count?: number;
  limit?: number;
  [key: string]: unknown;
}

export interface ErrorEnvelope {
  code: ErrorCode;
  message: string;
  details?: ErrorDetails;
}

export interface MappedFailure {
  code: ErrorCode | null;
  status: number | null;
  message: string;
  failureClass: FailureClass;
  /** Form control name to attach the message to, when the backend named one. */
  field?: string;
  details?: ErrorDetails;
}

export const UNEXPECTED_MESSAGE = 'Something went wrong. Please try again.';
export const NETWORK_MESSAGE =
  'We could not reach the server. Check your connection and try again.';
export const SESSION_ENDED_MESSAGE = 'Your session has ended. Please sign in again.';
/** Fixed text for a 404. Must never imply the record exists but is off-limits. */
export const NOT_FOUND_MESSAGE = 'We could not find that record.';

interface Entry {
  message: string;
  failureClass: FailureClass;
  /** Prefer the backend's own message, which is specific and actionable. */
  preferServerMessage?: boolean;
}

const CATALOGUE: Record<ErrorCode, Entry> = {
  INVALID_CREDENTIALS: {
    message: 'That identifier and password do not match.',
    failureClass: 'user_actionable',
  },
  TOKEN_EXPIRED: { message: SESSION_ENDED_MESSAGE, failureClass: 'session_ended' },
  TOKEN_INVALID: { message: SESSION_ENDED_MESSAGE, failureClass: 'session_ended' },
  TOKEN_CONSUMED: {
    message: 'That code has already been used. Request a new one.',
    failureClass: 'user_actionable',
  },
  AUTH_UNAVAILABLE: {
    message: 'Sign-in is temporarily unavailable. Please try again in a moment.',
    failureClass: 'unexpected',
  },
  NOT_AUTHENTICATED: { message: SESSION_ENDED_MESSAGE, failureClass: 'session_ended' },
  FORBIDDEN: {
    // Each of SubscriptionWriteGate, ActiveMemberGate, RoleAllowed, TrainerScope
    // and MemberSelfScope supplies its own actionable sentence.
    message: 'That action is not permitted for your account right now.',
    failureClass: 'user_actionable',
    preferServerMessage: true,
  },
  NOT_FOUND: { message: NOT_FOUND_MESSAGE, failureClass: 'user_actionable' },
  VALIDATION_ERROR: {
    message: 'Please correct the highlighted field.',
    failureClass: 'user_actionable',
    preferServerMessage: true,
  },
  SEAT_LIMIT_REACHED: {
    message: 'This gym has reached its member limit.',
    failureClass: 'user_actionable',
  },
  PLAN_DOWNGRADE_BLOCKED: {
    message: 'That plan allows fewer members than this gym currently has.',
    failureClass: 'user_actionable',
  },
  SUBSCRIPTION_REQUIRED: {
    message:
      'This gym has no trialing or active subscription, so members cannot be added.',
    failureClass: 'user_actionable',
  },
  INVOICE_ALREADY_PAID: {
    message: 'This invoice has already been paid.',
    failureClass: 'user_actionable',
  },
  INVOICE_IMMUTABLE: {
    message: 'This invoice can no longer be changed.',
    failureClass: 'user_actionable',
    preferServerMessage: true,
  },
  CURRENCY_MISMATCH: {
    message: 'The currency does not match the one on record.',
    failureClass: 'user_actionable',
    preferServerMessage: true,
  },
  GATEWAY_ERROR: {
    message: 'The payment gateway could not be reached. No payment was recorded.',
    failureClass: 'unexpected',
  },
  CARD_DATA_REJECTED: {
    // We never send card data, so reaching this is our bug, not the user's.
    message: UNEXPECTED_MESSAGE,
    failureClass: 'frontend_defect',
  },
  SIGNATURE_INVALID: {
    // Reachable only on the gateway webhook route, which this client never calls.
    message: UNEXPECTED_MESSAGE,
    failureClass: 'unreachable',
  },
  RATE_LIMITED: {
    message: 'Too many attempts. Please wait before trying again.',
    failureClass: 'user_actionable',
  },
  METHOD_NOT_ALLOWED: {
    message: 'That action is not available here.',
    failureClass: 'frontend_defect',
  },
  CONFLICT: {
    message: 'That conflicts with the current state of the record.',
    failureClass: 'user_actionable',
    preferServerMessage: true,
  },
  SERVER_ERROR: {
    message: 'Something went wrong on the server. Please try again.',
    failureClass: 'unexpected',
  },
};

function isErrorCode(value: unknown): value is ErrorCode {
  return typeof value === 'string' && (ERROR_CODES as readonly string[]).includes(value);
}

/** Parse a response body into an envelope, or null when it is off-contract. */
export function parseEnvelope(body: unknown): ErrorEnvelope | null {
  if (typeof body !== 'object' || body === null) return null;
  const wrapper = (body as { error?: unknown }).error;
  if (typeof wrapper !== 'object' || wrapper === null) return null;

  const { code, message, details } = wrapper as Record<string, unknown>;
  if (!isErrorCode(code)) return null;
  if (typeof message !== 'string') return null;

  return {
    code,
    message,
    details:
      typeof details === 'object' && details !== null ? (details as ErrorDetails) : undefined,
  };
}

/** A failure with no HTTP response at all — offline, DNS, abort, timeout. */
export class NetworkFailure extends Error {
  constructor(message = NETWORK_MESSAGE) {
    super(message);
    this.name = 'NetworkFailure';
  }
}

/** A non-2xx response, carrying whatever we could make of the body. */
export class ApiError extends Error {
  readonly status: number;
  readonly envelope: ErrorEnvelope | null;

  constructor(status: number, envelope: ErrorEnvelope | null) {
    super(envelope?.message ?? UNEXPECTED_MESSAGE);
    this.name = 'ApiError';
    this.status = status;
    this.envelope = envelope;
  }

  get code(): ErrorCode | null {
    return this.envelope?.code ?? null;
  }
}

/** Clamp a throttle wait into something sane. Absent or wild values become 60s. */
export function retryAfterSeconds(details: ErrorDetails | undefined): number {
  const raw = details?.retry_after_seconds;
  if (typeof raw !== 'number' || !Number.isFinite(raw)) return 60;
  return Math.min(300, Math.max(1, Math.floor(raw)));
}

/**
 * Total over the 22 codes, plus the two off-contract cases. Never returns an
 * empty message, never leaks a stack trace, a method, a URL or a raw body.
 */
export function mapFailure(error: unknown): MappedFailure {
  if (error instanceof NetworkFailure) {
    return { code: null, status: null, message: NETWORK_MESSAGE, failureClass: 'unexpected' };
  }

  if (!(error instanceof ApiError)) {
    return { code: null, status: null, message: UNEXPECTED_MESSAGE, failureClass: 'unexpected' };
  }

  const { envelope, status } = error;
  if (envelope === null) {
    return { code: null, status, message: UNEXPECTED_MESSAGE, failureClass: 'unexpected' };
  }

  const entry = CATALOGUE[envelope.code];
  const details = envelope.details;

  // A 404 always gets our own fixed sentence. Using the server's message risks
  // wording that confirms the record exists but belongs to someone else, which
  // would undo the byte-identical 404 the backend goes to trouble to produce.
  if (envelope.code === 'NOT_FOUND') {
    return {
      code: envelope.code,
      status,
      message: NOT_FOUND_MESSAGE,
      failureClass: entry.failureClass,
    };
  }

  let message =
    entry.preferServerMessage && envelope.message.trim().length > 0
      ? envelope.message
      : entry.message;

  if (envelope.code === 'SEAT_LIMIT_REACHED' || envelope.code === 'PLAN_DOWNGRADE_BLOCKED') {
    const { seat_count: seats, limit } = details ?? {};
    if (typeof seats === 'number' && typeof limit === 'number') {
      message =
        envelope.code === 'SEAT_LIMIT_REACHED'
          ? `This gym is using ${seats} of ${limit} member seats.`
          : `That plan allows ${limit} members and this gym has ${seats}.`;
    }
  }

  if (envelope.code === 'RATE_LIMITED') {
    message = `Too many attempts. Try again in ${retryAfterSeconds(details)} seconds.`;
  }

  const field = typeof details?.field === 'string' ? details.field : undefined;

  return {
    code: envelope.code,
    status,
    message,
    failureClass: entry.failureClass,
    ...(field ? { field } : {}),
    ...(details ? { details } : {}),
  };
}

/** True when the failure means the session is over and sign-in must be shown. */
export function isSessionEnded(error: unknown): boolean {
  return mapFailure(error).failureClass === 'session_ended';
}
