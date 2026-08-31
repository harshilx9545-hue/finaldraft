# Requirements Document

## Introduction

This specification covers `mk00-frontend`: a production React + TypeScript web client for the
MK00 Gym SaaS backend that already exists in this repository. There is currently no frontend
directory anywhere in the workspace, so this is greenfield work against a finished, test-covered
API.

Two sources of truth, strictly separated:

| Question | Authority |
| --- | --- |
| What exists — features, data, endpoints, fields, roles, permissions, validation, workflows | The Django code in `core/` and `gymapp/` |
| How it looks — colour, type, spacing, radius, motion | `DESIGN.md` at the workspace root, restated as criteria in Requirement 3 |

Nothing else has authority. The two documents in `.kiro/specs/gym-saas-core/` and
`.kiro/specs/gym-saas-platform/` describe the backend's intent and were read for background, but
where they disagree with the code, the code wins.

### Audit method

Phase 1 was a read of the backend, not an inference from filenames. The following were read in
full: `core/urls.py`, `gymapp/urls.py`, `core/models.py`, `core/serializers.py`,
`core/permissions.py`, `core/scoping.py`, `core/authentication.py`, `core/exceptions.py`,
`core/throttling.py`, `core/validators.py`, all five modules in `core/views/`, all fourteen
modules in `core/services/`, `gymapp/settings.py`, `gymapp/config.py`, `.env.example`,
`core/management/commands/check_api_surface.py`,
`core/management/commands/check_tenant_scoping.py`, `core/tests/endpoints.py`,
`core/tests/factories.py`, and the property tests for tenant isolation (01), existence
non-disclosure (02), access gates (03), error envelope (17), minor units (18), API surface (38),
and write gates (35). Two repository-wide searches confirmed the most consequential negative
finding recorded below.

### Two findings that shape everything downstream

**1. `DESIGN.md` at the workspace root is the visual source of truth, and it is not ours to
write.** The file is authored by the requester and supersedes the design summary this
specification was originally drafted from. Requirement 3 restates its token set, type scale,
weights, radii, elevation recipes, surface levels, and accent rules as testable criteria, and
forbids the Frontend from editing the file. Requirement 3 also does two things a faithful
transcription cannot: it resolves two internal contradictions in `DESIGN.md` (the display-font
fallback stack and the avatar tint) and records each resolution as an explicit deviation, and it
governs the translation from the marketing site `DESIGN.md` describes to the authenticated data
application MK00 actually is.

One caution for the design phase: `genesis-DESIGN.md` at the workspace root is **not** this
design system. It describes an unrelated product — a community platform for sharing design system
files — in an indigo and green palette with General Sans, DM Sans, and JetBrains Mono. It holds no
authority over any criterion in this specification and is to be ignored entirely.

**2. There is no server-side search, filter, or ordering. At all.** `REST_FRAMEWORK` in
`gymapp/settings.py` declares no `DEFAULT_FILTER_BACKENDS`. A search for `SearchFilter`,
`OrderingFilter`, `filterset`, `search_fields`, and `ordering_fields` matched only
`core/admin.py`, which configures the Django admin and is not part of the API. A search for
`query_params` and `request.GET` across `core/` returned zero matches. The only query parameter
any list endpoint honours is `page`, supplied by DRF's `PageNumberPagination` with
`PAGE_SIZE = 25`. `page_size` is not accepted because no pagination subclass sets
`page_size_query_param`.

### Resolved decision: quiet top navigation, not a sidebar

The requester's brief mentioned both a sidebar and a transparent top navigation. The audit
resolves this in favour of top navigation: the widest role (owner) reaches seven destinations,
and the design system explicitly rejects "heavy dashboard chrome / giant sidebar". Seven
destinations do not need a persistent 240px column. Requirement 4 specifies the top navigation.

---

## Backend Audit Findings

Everything in this section was read from the code. It is the map the requirements are written
against.

### A. The complete route inventory

Every route below is registered in `core/urls.py` under the `/api/` prefix from
`gymapp/urls.py`. Twenty patterns exist; nineteen are frontend-reachable. There are no others,
and `check_api_surface.py` fails the build if any are added in a deferred category or if any
listed in `REQUIRED_ROUTE_NAMES` are removed.

| # | Method | Path | View | Roles admitted | Success status |
| --- | --- | --- | --- | --- | --- |
| 1 | POST | `/api/auth/register/owner` | `OwnerRegistrationView` | anonymous | 201 |
| 2 | POST | `/api/auth/login` | `LoginView` | anonymous | 200 |
| 3 | POST | `/api/auth/refresh` | `TokenRefreshView` | anonymous | 200 |
| 4 | POST | `/api/auth/logout` | `LogoutView` | authenticated | 204 |
| 5 | POST | `/api/auth/verify-email` | `EmailVerificationView` | anonymous | 200 |
| 6 | POST | `/api/auth/password-reset` | `PasswordResetRequestView` | anonymous | 202 |
| 7 | POST | `/api/auth/password-reset/confirm` | `PasswordResetConfirmView` | anonymous | 200 |
| 8 | GET | `/api/saas-plans` | `SaasPlanListView` | any authenticated user | 200 |
| 9 | GET | `/api/membership-plans` | `MembershipPlanListCreateView` | owner, trainer, member | 200 |
| 10 | POST | `/api/membership-plans` | `MembershipPlanListCreateView` | owner | 201 |
| 11 | GET | `/api/membership-plans/{id}` | `MembershipPlanDetailView` | owner, trainer, member | 200 |
| 12 | PATCH | `/api/membership-plans/{id}` | `MembershipPlanDetailView` | owner | 200 |
| 13 | GET | `/api/me` | `MeView` | owner, trainer, member | 200 |
| 14 | PATCH | `/api/me` | `MeView` | owner, trainer, member | 200 |
| 15 | GET | `/api/gym` | `GymDetailView` | owner, trainer, member | 200 |
| 16 | PATCH | `/api/gym` | `GymDetailView` | owner | 200 |
| 17 | GET | `/api/trainers` | `TrainerListCreateView` | owner | 200 |
| 18 | POST | `/api/trainers` | `TrainerListCreateView` | owner | 201 |
| 19 | GET | `/api/members` | `MemberListCreateView` | owner, trainer | 200 |
| 20 | POST | `/api/members` | `MemberListCreateView` | owner, trainer | 201 |
| 21 | GET | `/api/members/{id}` | `MemberDetailView` | owner, trainer, member | 200 |
| 22 | PATCH | `/api/members/{id}` | `MemberDetailView` | owner, trainer | 200 |
| 23 | GET | `/api/invoices` | `InvoiceListView` | owner, trainer, member | 200 |
| 24 | GET | `/api/invoices/{id}` | `InvoiceDetailView` | owner, trainer, member | 200 |
| 25 | POST | `/api/invoices/{id}/pay` | `InvoicePayView` | owner, member | 201 |
| 26 | GET | `/api/payments/{id}/receipt` | `ReceiptView` | owner, member | 200 |
| — | POST | `/api/webhooks/razorpay` | `RazorpayWebhookView` | Payment_Gateway only | 200 |

There is **no DELETE method on any route**. `MeView`, `GymDetailView`, `MemberDetailView`, and
`MembershipPlanDetailView` set `http_method_names = ["get", "patch", "head", "options"]`;
`TrainerListCreateView` and `MemberListCreateView` are `ListCreateAPIView`; `InvoicePayView`
defines only `post`; `ReceiptView` defines only `get`.

The webhook is the gateway's inbound endpoint. It is unauthenticated, CSRF-exempt, and
authenticated solely by an HMAC-SHA256 signature in `X-Razorpay-Signature`. It is not a frontend
surface.

### B. Role and gate matrix

Roles come from `User.role`, whose `ROLE_CHOICES` are exactly `owner`, `trainer`, `member`.
`core/permissions.py` re-reads role and Gym from the database every request; the `role` and
`gym_id` JWT claims are a client convenience and grant nothing.

Gates, in evaluation order as declared per view:

- `IsAuthenticatedWithProfile` — 401 anonymous; 403 when the caller holds no non-soft-deleted
  profile or the Gym has `is_active` false. Staff accounts hold no profile and are refused here.
- `RoleAllowed` — the project `DEFAULT_PERMISSION_CLASS`. Closed by default: a view with no
  `allowed_roles` denies every role (`core/tests/test_default_denial.py`).
- `TrainerScope` — a trainer reaches only members whose `trainer` foreign key is that trainer.
  Writes to `payment`, `invoice`, `creditnote`, and `saasplan` models are refused unconditionally.
- `MemberSelfScope` — a member reaches only their own records, and may only write where a view
  declares `member_writable`. No view declares it.
- `SubscriptionWriteGate` — when the Gym's subscription is not `trialing` or `active`, all unsafe
  methods return **403 FORBIDDEN**. Safe methods always pass. Exempt: `InvoicePayView`.
- `RequiresSubscription` — declared only on `MemberListCreateView`. Returns **402
  SUBSCRIPTION_REQUIRED** rather than 403, because 5.7 gives member creation its own status.
- `ActiveMemberGate` — a member with no settled, in-period Membership may issue safe methods
  only. Exempt: `InvoicePayView`, `ReceiptView`.

Payer scoping on billing routes (`PayerScopedInvoiceQuerysetMixin`): an owner sees the whole
Gym's invoices; every other role sees only invoices where `payer_user` is that user. `ReceiptView`
is payer-scoped for **every** role, owner included.

### C. Write payload contracts

Exact field sets, read from `core/serializers.py`. `id` and every field listed as read-only are
rejected as input by being absent from the writable set. `to_internal_value` on
`TenantScopedSerializerMixin` silently strips `gym`, `gym_id`, `role`, `is_staff`,
`is_superuser`, `email_verified`, `status`, `is_active_member`, and `active` from every payload.

**POST `/api/auth/register/owner`** (`OwnerRegistrationSerializer`)
Required: `email`, `password`, `password_confirm`, `business_name`, `contact_phone`.
Optional: `first_name`, `last_name`, `phone`, `gym_name`, `contact_email`, `timezone_name`
(default `Asia/Kolkata`), `gstin`.
Response 201: `{gym: {...}, user: {id, email, role, email_verified}, tokens: {access, refresh}}`.

**POST `/api/auth/login`** (`LoginSerializer`) — `identifier`, `password`. `identifier` is an
email address or an E.164 phone number. Response 200: `{access, refresh}`.

**POST `/api/auth/refresh`** — `refresh`. Response 200: `{access, refresh}`. The presented token
is blacklisted; refresh tokens are single-use.

**POST `/api/auth/logout`** — `refresh`, with a valid `Authorization` header. Response 204.

**POST `/api/auth/verify-email`** — `token`. Response 200: `{email_verified: true}`.

**POST `/api/auth/password-reset`** — `email`. Response 202 with a fixed `detail` string,
identical whether or not the address is registered.

**POST `/api/auth/password-reset/confirm`** — `token`, `password`, `password_confirm`.
Response 200: `{detail}`. Every refresh token for that user is blacklisted.

**POST `/api/members`** (`MemberInviteSerializer`)
Required: `email`, `join_date`. Optional: `first_name`, `last_name`, `phone`, `plan`, `trainer`,
`goal`, `photo_url`. Response 201 is a `MemberProfileSerializer` body.

**PATCH `/api/members/{id}`** (`MemberProfileSerializer`)
Writable: `plan`, `trainer`, `join_date`, `goal`, `photo_url`.
Read-only: `id`, `email`, `full_name`, `is_active`, `current_period_end`.

**POST `/api/trainers`** (`TrainerInviteSerializer`)
Required: `email`. Optional: `first_name`, `last_name`, `phone`, `specialization`.
Response 201 is a `TrainerProfileSerializer` body: `id`, `email`, `full_name`, `specialization`,
`status`.

**POST `/api/membership-plans`** (`MembershipPlanSerializer`)
Required: `name`, `price`, `duration_days`. Optional: `currency` (default `INR`),
`includes_trainer`, `includes_diet` (both default false).

**PATCH `/api/membership-plans/{id}`** — the same writable set.

**PATCH `/api/me`** (`MeUpdateSerializer`) — `first_name`, `last_name`, `phone`. Nothing else.

**PATCH `/api/gym`** (`GymSerializer`)
Writable: `name`, `contact_email`, `contact_phone`, `timezone`, `gstin`.
Read-only: `id`, `slug`, `is_active`. `created_at` is never serialised at all.

**POST `/api/invoices/{id}/pay`** — no required body. The body is scanned for card-data field
names at any nesting depth and rejected with 400 `CARD_DATA_REJECTED` if any is found. Response
201: `{order_ref, amount_minor, currency, key_id, receipt}`. `key_id` is the public Razorpay key.

### D. Field-level validation the frontend must mirror

From `core/validators.py` and the model fields:

- `phone` / `contact_phone`: E.164, regex `^\+[1-9]\d{7,14}$`, max 16 characters. Unique
  platform-wide, so a clash is a 400 naming `phone`.
- `gstin`: exactly 15 characters, regex
  `^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$`. Nullable.
- `timezone`: must be a name in `zoneinfo.available_timezones()`.
- `currency`: one of `INR`, `USD`, `EUR`, `GBP`, `AED`, `SGD`, `AUD`, `CAD`.
- `duration_days`: integer, 1 to 3650 inclusive.
- `price`: decimal, max 12 digits, 2 decimal places, minimum `0.00`.
- `email`: unique case-insensitively across the platform.
- `password`: validated by Django's configured validators — minimum length 10, not similar to
  user attributes, not a common password, not entirely numeric.
- `MemberProfile.goal` choices: `strength`, `aesthetics`, `cut`, `bulk`, or blank.
- `TrainerProfile.status` choices: `active`, `inactive`.
- `MembershipPlan.name` is unique per gym, case-insensitively.

### E. Response representation

- **Money is a JSON string.** `COERCE_DECIMAL_TO_STRING` is not overridden, so DRF's default
  applies and every `DecimalField` serialises as a string such as `"1500.00"`. This holds for
  `price`, `taxable_value`, `cgst`, `sgst`, `igst`, `total_amount`, and `amount`.
  The single integer money value in the whole API is `amount_minor` in the pay-order response,
  which is minor units (paise for INR) per `core/services/money.py`.
- **Dates** are ISO `YYYY-MM-DD` strings (`join_date`, `issue_date`, `due_date`, `start_date`,
  `end_date`, `current_period_end`). Timestamps are ISO 8601 with offset (`paid_at`).
- **Null is not zero.** When the issuing Gym has no `gstin`, `cgst`, `sgst`, `igst`, and
  `hsn_sac` are all `null`, meaning "tax not applicable" — deliberately distinct from `0.00`
  (`core/services/invoicing.compute_tax`).
- **Lists are paginated**: `{count, next, previous, results}`, 25 rows per page, `?page=N`.
- **Foreign keys serialise as bare integers.** `MemberProfileSerializer.plan` and `.trainer`,
  `InvoiceSerializer.membership` and `.saas_subscription` are primary keys with no nested
  representation and no name.

### F. Derived state, computed server-side

Never stored, always computed, and therefore never something the frontend may recalculate:

- `MemberProfileSerializer.is_active` — true only when the member holds a Membership whose period
  contains today *and* whose Invoice is settled (or whose plan price is zero).
  `MemberProfile` has no stored status field.
- `MemberProfileSerializer.current_period_end` — the furthest-reaching Membership `end_date`, or
  null.
- `MeSerializer.is_active_member` — the same computation, null for non-member roles.
- `MeSerializer.subscription_status` — `effective_status()`, one of `trialing`, `active`,
  `past_due`, `cancelled`, or null. `past_due` is derived from the calendar, not written by a job.
- All date comparisons happen in the **Gym's** timezone (`Gym.timezone`), not the server's and
  not the browser's.

### G. The error envelope

`core/exceptions.api_exception_handler` is the DRF `EXCEPTION_HANDLER`, so every non-2xx
response in the entire API has this shape, verified by property 17:

```json
{"error": {"code": "SEAT_LIMIT_REACHED", "message": "...", "details": {"seat_count": 50, "limit": 50, "field": "member"}}}
```

`details` is omitted entirely when empty. For validation failures the handler lifts the first
offending field into `details.field`. For throttling it sets `details.retry_after_seconds`.

The complete code catalogue is 22 values, and property 17 asserts the API can emit nothing
outside it: `INVALID_CREDENTIALS`, `TOKEN_EXPIRED`, `TOKEN_INVALID`, `TOKEN_CONSUMED`,
`AUTH_UNAVAILABLE`, `NOT_AUTHENTICATED`, `FORBIDDEN`, `NOT_FOUND`, `VALIDATION_ERROR`,
`SEAT_LIMIT_REACHED`, `PLAN_DOWNGRADE_BLOCKED`, `SUBSCRIPTION_REQUIRED`,
`INVOICE_ALREADY_PAID`, `INVOICE_IMMUTABLE`, `CURRENCY_MISMATCH`, `GATEWAY_ERROR`,
`CARD_DATA_REJECTED`, `SIGNATURE_INVALID`, `RATE_LIMITED`, `METHOD_NOT_ALLOWED`, `CONFLICT`,
`SERVER_ERROR`.

### H. Existence non-disclosure

Property 02 compares responses byte for byte: for every detail route and every method, a request
naming **another tenant's real id** returns an identical status and an identical body to a
request naming an id that matches nothing on the platform. This holds *within* a tenant too — one
member requesting another member's id in the same gym gets the same 404.

The distinction the backend draws: **403 means the role is refused**, **404 means the record is
hidden**. The frontend must not undo this by phrasing a 404 as "you do not have permission to see
this member", which would confirm the record exists.

### I. Auth and session mechanics

- Header: `Authorization: Bearer <access>`.
- `ACCESS_TOKEN_LIFETIME` 15 minutes, `REFRESH_TOKEN_LIFETIME` 7 days (both env-configurable).
- `ROTATE_REFRESH_TOKENS` and `BLACKLIST_AFTER_ROTATION` are both true, so **each refresh token
  works exactly once** and a concurrent double-refresh loses one of the two.
- `DistinguishingJWTAuthentication` separates an expired-but-validly-signed token from a
  malformed one, so `TOKEN_EXPIRED` and `TOKEN_INVALID` are distinguishable and mean different
  things to the client.
- Verification and reset emails deliver a **raw token code, not a clickable link**
  (`core/services/email.py`). Token lifetimes: 72 hours for email verification, 60 minutes for
  password reset. Both are single-use.
- Throttles, keyed on user id when authenticated and IP otherwise, with a hard floor of 5/min:
  login 10/min, registration 5/min, password reset 5/min. Exceeding one yields 429
  `RATE_LIMITED`.
- CORS: `CORS_ALLOWED_ORIGINS` defaults to `http://localhost:3000` and `http://127.0.0.1:3000`
  under `DEBUG`. `CORS_ALLOW_ALL_ORIGINS` is false, `CORS_ALLOW_CREDENTIALS` is false, and
  `CORS_URLS_REGEX` restricts CORS handling to `^/api/.*$`.

### J. Models that exist with no route — these get no UI

`check_api_surface.py` enforces the absence of the deferred categories, and property 38 asserts
the models exist but are unreachable. Routing any of them would fail the build.

Deliberately deferred and build-guarded: `WorkoutSplit`, `Exercise`, `WorkoutLog`,
`StrengthStandard`, `BodyMetric`, `FormCheck`, `DietPlan`, `Attendance`, `Equipment`,
`Notification`.

Present but unrouted for other reasons: `OwnerProfile` (reachable only indirectly through
`/api/me` and `/api/gym`), `SaasSubscription` (surfaced only as the `subscription_status` string
on `/api/me`), `Membership`, `InvoiceSequence`, `CreditNote`, `Payment` (no list or detail route;
only `/api/payments/{id}/receipt`), `WebhookEvent`, `AuditRecord`, `RecoveryAttempt`,
`EmailVerificationToken`, `PasswordResetToken`.

### K. Confirmed backend gaps that constrain this frontend

Each of these was verified in the code, not assumed. Twelve of the thirteen are to be handled
Frontend-side with no Backend change. The single exception is `G13`, which the requester has
approved in writing to be resolved by one targeted, additive Backend change, scoped and bounded
by Requirement 25.

| # | Gap | Frontend consequence |
| --- | --- | --- |
| G1 | No Membership endpoint. `MembershipSerializer` exists in `core/serializers.py` but `core/urls.py` routes nothing to it, and `create_membership` is only reachable from Python. | No UI can sell, start, or renew a membership period. A member created through `POST /api/members` has no Membership, therefore no membership Invoice, therefore `is_active` is false and stays false. |
| G2 | No Payment list or detail route, and `InvoiceSerializer` has no `payments` field. `order_response` returns `order_ref` but not the Payment `id`. | A Payment id is undiscoverable through the API, so `/api/payments/{id}/receipt` is unreachable from the UI. No receipt surface can be built. |
| G3 | No trainer detail or update route. `TrainerProfileSerializer` exposes writable `specialization` and `status`, but no route accepts a PATCH. | Trainers are list-and-create only. No trainer edit or deactivate UI. |
| G4 | No SaasSubscription or plan-change route. `seats.change_saas_plan` exists but is unrouted, and `/api/me` reports only a status string, never which SaasPlan the Gym holds. | No subscription management UI, no upgrade/downgrade, and **no way to know the Gym's seat limit**, so no seat-usage widget is possible even though `SaasPlan.max_members_allowed` is serialised by `/api/saas-plans`. |
| G5 | No DELETE on any route. | No delete, archive, or deactivate action for any entity. |
| G6 | No aggregate, statistics, or reporting endpoint. | Dashboard metrics are limited to the `count` field of paginated list responses and the scalar fields of `/api/me`. |
| G7 | `create_member_atomically` sends no email. The `MEMBER_INVITE` constant in `core/services/email.py` is never used, and the generated temporary password is discarded. | A newly created member cannot sign in. The UI must direct the owner to tell the member to use the password-reset flow. Trainers, by contrast, do receive `send_invite_email` with a temporary password. |
| G8 | No email-verification resend route. | If the registration email is lost, the UI has no recovery action to offer. |
| G9 | Foreign keys serialise as bare integers with no name (§E). `GET /api/trainers` is owner-only. | A trainer viewing an assigned member sees `trainer: 7` and cannot resolve any trainer's name. Plan names are resolvable by every role because `/api/membership-plans` is readable by all three. |
| G10 | `photo_url` is a `URLField` and no upload endpoint exists. | Member photo is a URL text input, not a file picker. |
| G11 | Invoice `membership` and `saas_subscription` are bare ids with no resolving endpoint. | An invoice can be labelled as a membership invoice or a subscription invoice, but the specific period behind it cannot be named. |
| G12 | Vite's default dev port is 5173; the backend's default `CORS_ALLOWED_ORIGINS` is port 3000. | Frontend-side fix: pin the dev server to port 3000. No backend change. |
| G13 | **Resolved by approved Backend change.** `MeSerializer.id` is the **`User`** id, and as originally audited no response exposed a caller their own `MemberProfile` id, so `GET /api/members/{id}` was unreachable for the `member` Role. The requester has approved in writing the addition of a `member_profile_id` field to `MeSerializer`, returning the caller's `MemberProfile` primary key for the `member` role and null for `owner` and `trainer`. | The `member` Role's own surface is populated from `GET /api/members/{member_profile_id}` using the identifier from `GET /api/me`, in addition to `/api/me`, so `plan`, `trainer`, `join_date`, `goal`, and `photo_url` are presented as real values. The surface stays read-only. Guessing identifiers remains forbidden by Requirement 7 criterion 6; the identifier is now supplied, not guessed. |

#### The one approved Backend change, and why it is safe and sufficient

The requester has approved in writing exactly one Backend change: adding `member_profile_id` to
`MeSerializer`. No other Backend change is approved. Four facts were read from the code and make
the change both safe and sufficient on its own.

1. **A member may already read their own member record; only the identifier was missing.**
   `MemberSelfScope.has_object_permission` in `core/permissions.py` returns
   `_owning_member_id(obj) == getattr(ctx.profile, "pk", None)` for a `member` caller, and
   `_owning_member_id` returns `obj.pk` when `obj` is a `MemberProfile`. A member requesting their
   own `MemberProfile` id therefore already passes the object-level check, and
   `TenantScopedQuerysetMixin` already admits the row. No permission class, no queryset filter,
   and no view needs to change — the identifier was the only thing undiscoverable.
2. **The field shape is already established in the same serializer.**
   `MeSerializer.get_is_active_member` and `MeSerializer.get_current_period_end` both return
   `None` when `resolve_profile(user)` is None or `user.role != "member"`. `member_profile_id`
   follows that exact pattern, so it is additive and nullable and introduces no new convention.
3. **No test asserts an exact key set for `/api/me`.** The only exact-key-set assertion on an API
   response body in the suite is `assert set(body) == {"order_ref", "amount_minor", "currency",
   "key_id", "receipt"}` on the pay-order response in
   `core/tests/test_property_22_order_creation.py`. Property 17 asserts `set(body) == {"error"}`
   on error envelopes only. Adding a key to `/api/me` therefore breaks no existing assertion.
4. **The change touches no conformance guard.** It adds no route, so
   `check_api_surface.py` is unaffected; it adds no queryset, so `check_tenant_scoping.py` is
   unaffected; and it alters no behaviour asserted by properties 01, 02, 03, 17, 18, 35, or 38.

Requirement 25 bounds the change to `core/serializers.py` and to `MeSerializer` alone, and
requires the full Backend test suite to pass afterwards.

---

## Glossary

- **Backend**: The audited Django + DRF application in `core/` and `gymapp/`, served under
  `/api/`. Authoritative for all behaviour. Out of scope for modification.
- **Frontend**: The React + TypeScript single-page application delivered by this specification.
- **API_Client**: The Frontend module that issues every HTTP request to the Backend, attaches the
  `Authorization` header, and performs access-token refresh.
- **Session_Store**: The Frontend module holding the access token, the refresh token, and the
  `/api/me` payload for the signed-in user.
- **Route_Guard**: The Frontend component that decides, before a route renders, whether the
  current session's role admits that route.
- **Error_Mapper**: The Frontend module that converts a Backend error envelope into a
  user-facing message and a presentation decision.
- **Query_Layer**: The TanStack Query configuration that caches, invalidates, and retries
  Backend reads and writes.
- **Design_System**: The token set, component conventions, and motion rules recorded in
  `DESIGN.md`.
- **Token_Layer**: The CSS custom properties implementing the Design_System, mapped into the
  Tailwind theme.
- **App_Shell**: The persistent Frontend chrome: top navigation, page container, and toast
  region.
- **Nav_Model**: The declarative, role-keyed data structure from which App_Shell renders
  navigation.
- **Money_Formatter**: The Frontend module that renders Backend decimal strings for display
  without converting them to a JavaScript number.
- **Payment_Gateway**: Razorpay, the external payment provider. The Backend creates an order through
  it and receives settlement notice on its webhook route; the Frontend hands off to its client-side
  checkout using the public `key_id` and `order_ref` from the pay-order response.
- **Data_List**: A Frontend component rendering a paginated Backend collection.
- **Motion_Layer**: The Framer Motion variants and CSS transitions implementing the
  Design_System's animation rules.
- **Build_Pipeline**: The npm scripts for type-checking, linting, testing, and production
  bundling.
- **Limitations_Document**: `frontend/LIMITATIONS.md`, the honest record of what the Backend does
  not support.
- **Role**: One of exactly `owner`, `trainer`, `member`, as defined by `User.ROLE_CHOICES`.
- **Error_Envelope**: The Backend's uniform non-2xx body,
  `{"error": {"code", "message", "details"?}}`.
- **Derived_State**: A value the Backend computes per request and never stores: `is_active`,
  `is_active_member`, `current_period_end`, `subscription_status`.

---

## Requirements

### Requirement 1: Audit Fidelity — No Surface Without a Backing Endpoint

**User Story:** As a gym owner, I want every control in the interface to correspond to something
the system can actually do, so that I never waste time on a feature that does not exist.

#### Acceptance Criteria

1. THE API_Client SHALL issue HTTP requests only to the twenty-six role-reachable
   method-and-path pairs enumerated in Backend Audit Findings section A, and SHALL issue no
   request to `POST /api/webhooks/razorpay`, because that route is authenticated solely by an
   HMAC-SHA256 signature in `X-Razorpay-Signature` and is not a Frontend surface.
2. THE Frontend SHALL send, in each request body, only the field names enumerated for that
   endpoint in Backend Audit Findings section C, and SHALL omit `id`, `gym`, `gym_id`, `role`,
   `is_staff`, `is_superuser`, `email_verified`, `status`, `is_active_member`, and `active` from
   every request body, because `TenantScopedSerializerMixin.to_internal_value` strips those keys
   and every read-only field is absent from that endpoint's writable set.
3. THE Frontend SHALL render, for each Backend resource, only the field names present in that
   resource's serializer as recorded in Backend Audit Findings sections C and E, together with a
   name resolved from another Backend response the current session already received as
   Requirement 13 criteria 3 and 4 require, and SHALL render no field, label, or value obtained
   from any other origin.
4. THE Frontend SHALL present no navigation destination, page, tab, table column, metric, filter
   control, or action button whose initial render, or whose activation by a user, would require a
   method-and-path pair absent from Backend Audit Findings section A.
5. THE Frontend SHALL present no route, navigation destination, page, tab, table column, form
   control, action control, or detail surface for `WorkoutSplit`, `Exercise`, `WorkoutLog`,
   `StrengthStandard`, `BodyMetric`, `FormCheck`, `DietPlan`, `Attendance`, `Equipment`, or
   `Notification`, because `check_api_surface.py` fails the build if any of those ten models is
   routed.
6. THE Frontend SHALL present no create form, no update form, no list surface, and no detail
   route for `Membership`, `Payment`, `CreditNote`, `WebhookEvent`, `AuditRecord`,
   `RecoveryAttempt`, `InvoiceSequence`, `SaasSubscription`, `EmailVerificationToken`, or
   `PasswordResetToken`, and SHALL present a value belonging to one of those ten models only
   where that value appears as a field of a routed resource's serializer as recorded in Backend
   Audit Findings sections C and E.
7. THE Frontend SHALL contain, in every module that ships in the production bundle, no literal
   member name, trainer name, plan name, revenue figure, attendance count, analytics series, or
   record-shaped value that is rendered as though the Backend had supplied it.
8. WHERE a Frontend module requires sample data for a unit test, THE Frontend SHALL confine that
   data to modules unreachable from the production entry module's import graph, so that the
   Build_Pipeline emits none of that data into the production bundle.
9. THE Frontend SHALL derive every displayed collection total from the `count` field of a Backend
   paginated response, SHALL derive every other displayed figure from a scalar field of a Backend
   response body, and SHALL present the length of a `results` array only as the number of rows
   currently displayed and never as a collection total.
10. IF a Frontend module requests a method-and-path pair absent from Backend Audit Findings
    section A, or supplies a request body field absent from that endpoint's field set in Backend
    Audit Findings section C, THEN THE API_Client SHALL issue no request, SHALL classify the
    failure as a Frontend defect, and SHALL present the unexpected-failure message defined in
    Requirement 11 criterion 3.
11. THE Frontend SHALL issue no HTTP DELETE request to any Backend path, and SHALL present no
    delete, archive, or deactivate control for any Backend resource, because Backend Audit
    Findings section A records no DELETE method on any route.
12. IF a Backend response omits a field a rendered surface presents, or supplies null for that
    field, THEN THE Frontend SHALL present a textual indication that the value is not supplied
    and SHALL substitute no default value, no zero, and no value computed in the browser, because
    null on `cgst`, `sgst`, `igst`, and `hsn_sac` means tax is not applicable and is deliberately
    distinct from the string `"0.00"`.

### Requirement 2: Project Scaffold and Toolchain

**User Story:** As a developer, I want a conventional, minimal toolchain, so that the project is
predictable to build and extend.

#### Acceptance Criteria

1. THE Frontend SHALL reside in a `frontend/` directory at the workspace root and SHALL create,
   modify, or delete no file outside that directory other than `.kiro/specs/mk00-frontend/`, and
   SHALL leave the root `DESIGN.md` unmodified as Requirement 3 criterion 1 requires, this
   prohibition extending to every build artefact, installed dependency, lockfile, and tool cache
   the toolchain produces, because the workspace root is not a git repository and no ignore rule
   exempts a generated file from this criterion.
2. THE Frontend SHALL declare React at an exact version of 18.0.0 or later, TypeScript at an
   exact version of 5.0.0 or later, and Vite at an exact version of 5.0.0 or later.
3. THE Frontend SHALL enable `strict` in `tsconfig.json` and SHALL disable no individual
   compiler check that `strict` enables.
4. THE Frontend SHALL use Tailwind CSS for styling, React Router for routing, TanStack Query for
   Backend state, React Hook Form with Zod for forms, Framer Motion for animation, and Lucide for
   icons.
5. THE Frontend SHALL record every entry in its dependency manifest, both production and
   development, as a single exact semantic version carrying no range operator, no wildcard, no
   distribution tag, and no version-control or filesystem reference, and SHALL keep a committed
   lockfile resolving every transitive dependency.
6. THE Frontend SHALL configure the Vite development server to listen on port 3000 and SHALL be
   reachable at both `http://localhost:3000` and `http://127.0.0.1:3000`, so that the Backend's
   default `CORS_ALLOWED_ORIGINS` value admits the Frontend without a Backend change.
7. THE Frontend SHALL read the Backend base URL from a single build-time environment variable
   exposed to client code by Vite's `VITE_` prefix convention, SHALL use
   `http://localhost:8000/api` when that variable is absent or holds only whitespace, and SHALL
   join every request path to that value with exactly one `/` separator whether or not the
   configured value ends in `/`.
8. THE Frontend SHALL emit one separately loaded bundle chunk per top-level route and SHALL fetch
   a route's chunk only when that route is first activated, so that the initial page load fetches
   no chunk belonging to an inactive route.
9. THE Frontend SHALL add no second CSS framework or style-composition library, no second router,
   no second Backend-state or data-fetching library, no second form-state library, no second
   schema-validation library, no second animation library, and no second icon set beyond the
   dependencies named in criterion 4.
10. WHERE the single invoice chart required by Requirement 22 criterion 3 ships in the production
    bundle, THE Frontend SHALL declare Recharts at an exact version as its only charting
    dependency, and SHALL otherwise declare no charting dependency.
11. IF port 3000 is unavailable when the development server starts, THEN THE Frontend SHALL fail
    to start with an error indicating that port 3000 is in use and SHALL listen on no other port,
    because a fallback port produces an origin outside the Backend's `CORS_ALLOWED_ORIGINS` values
    and `CORS_ALLOW_ALL_ORIGINS` is false.
12. THE Frontend SHALL contain, in its source and in its production bundle, no password, no API
    secret, no signing key, and no Backend credential, and SHALL obtain the Payment_Gateway
    `key_id` solely from the pay-order response body at runtime, because that value is the
    gateway's public key rather than a build-time secret.
13. THE Build_Pipeline SHALL invoke, in every script it declares, only the Node runtime at
    version 24.16.0 or later, the npm client at version 11.13.0 or later, and, where a script
    invokes a Python interpreter, the `py -3` launcher, because the `python` and `python3` names
    on this workstation resolve to a non-functional stub.

### Requirement 3: Design System Capture and Token Implementation

**User Story:** As a designer, I want the visual language recorded once and implemented as
tokens, so that the interface stays coherent and no component invents its own colour.

#### Acceptance Criteria

1. THE Frontend SHALL treat `DESIGN.md` at the workspace root as the authoritative visual
   specification for every criterion in this requirement, SHALL modify no byte of that file, and
   SHALL create no second copy of it, because that file is authored by the requester and is the
   sole source of visual authority. `DESIGN.md` stands outside the file set enumerated in
   Requirement 25 criteria 1 and 3, and that standing extends only to the fact that the file must
   not be edited at all, never to a permission to edit it.
2. THE Frontend SHALL implement the light theme only and SHALL implement no dark-mode variant.
3. THE Token_Layer SHALL define exactly ten colour custom properties and no other colour custom
   property: the nine named palette tokens Ink Black `#17191c`, Paper White `#ffffff`, Mist Gray
   `#f2f2f3`, Fog White `#fafafb`, Slate Gray `#777b86`, Ash Gray `#979799`, Smoke Gray `#a3a6af`,
   Blush Peach `#fbe1d1`, and Sienna Brown `#5d2a1a`, together with one border token valued
   `#ececec` for the hairline and input border value `DESIGN.md` records in its Quick Color
   Reference and in the border of its Input and Composer component.
4. THE Token_Layer SHALL define exactly five surface levels, and THE Frontend SHALL paint every
   rendered background from one of them: Canvas `#ffffff`, Card Mist `#f2f2f3`, Section Fog
   `#fafafb`, Accent Blush `#fbe1d1`, and Elevated White `#ffffff`.
5. THE Token_Layer SHALL define exactly two font-family custom properties: a display property
   naming `Signifier` first, then at least two named serif families, then the generic keyword
   `serif` as its final entry; and a body property naming `Söhne` first, then at least two named
   sans-serif families that ship with the current Windows and macOS releases, then the generic
   keyword `sans-serif` as its final entry.
6. THE Token_Layer SHALL define exactly eight named type-scale tokens, and THE Frontend SHALL
   render every text run through one of them: `caption` at 15px with line height 1.5; `body` at
   17px with line height 1.35; `body-lg` at 20px with line height 1.35; `subheading` at 22px with
   line height 1.5; `heading-sm` at 26px with line height 1.18 and letter spacing -0.23px;
   `heading` at 44px with line height 1.3 and letter spacing -0.66px; `heading-lg` at 64px with
   line height 1.3 and letter spacing -0.96px; and `display` at 90px with line height 1.3 and
   letter spacing -2.25px.
7. THE Frontend SHALL render body copy through the `body` token at 17px and SHALL render no body
   copy at 16px.
8. THE Frontend SHALL render every button label, every navigation link, and every text link
   through the body font custom property at 16px, and SHALL apply 16px to no other text role,
   because `DESIGN.md` assigns 16px to those three component roles specifically rather than as a
   general body size.
9. THE Frontend SHALL render every text run set in the display font custom property at font weight
   400 at every size, and SHALL apply no font weight of 500 or above and none of 600 or above to
   any text run set in that property.
10. THE Token_Layer SHALL expose exactly the body font weights 400, 430, 450, 480, and 500, and THE
    Frontend SHALL establish typographic hierarchy by advancing through the half-step weights 430,
    450, and 480 before applying 500.
11. THE Token_Layer SHALL define spacing custom properties for exactly these fifteen values in
    pixels and no others: 4, 8, 12, 16, 20, 24, 28, 32, 40, 64, 80, 96, 124, 128, and 160, and THE
    Frontend SHALL resolve every margin, padding, and gap to one of those fifteen properties.
12. THE Token_Layer SHALL define the radius custom properties `DESIGN.md` documents and no others:
    24px for a card, 12px for an image, 16px for an input control, 9999px for a button, 16px for a
    small card, and 20px for an elevated card, where a small card is a card nested inside another
    card and an elevated card is a card carrying one of the elevation recipes of criterion 14.
13. THE Frontend SHALL apply a radius of 16px or greater to every rendered card and a radius of
    9999px to every rendered button.
14. THE Token_Layer SHALL define exactly three shadow custom properties named `--shadow-subtle`,
    `--shadow-subtle-2`, and `--shadow-subtle-3`, and SHALL compose from them exactly the three
    elevation recipes `DESIGN.md` documents: the Floating Product Artifact recipe, the Modal and
    Overlay Card recipe, and the Dropdown and Popover recipe.
15. THE Frontend SHALL apply the Floating Product Artifact recipe to every floating product
    artifact, the Modal and Overlay Card recipe to every modal and every overlay card, and the
    Dropdown and Popover recipe to every dropdown and every popover.
16. THE Frontend SHALL apply no shadow to a Neutral Card and no shadow to an Accent Peach Card,
    because `DESIGN.md` states that drop shadows are not applied to content cards.
17. THE Frontend SHALL declare no `box-shadow` value other than the three elevation recipes of
    criterion 14 and the focus indicator required by criterion 43.
18. THE Frontend SHALL render at most one Accent Peach Card per rendered page.
19. THE Frontend SHALL paint every Accent Peach Card on a Paper White or Card Mist surface, and
    SHALL paint no Accent Peach Card on a coloured surface and none on a dark surface.
20. THE Frontend SHALL apply Sienna Brown only as text on an Accent Blush surface, as a stroke on
    an Accent Blush surface, and as a chart line stroke, and SHALL render no body text in Sienna
    Brown on a white surface.
21. THE Frontend SHALL render every low-emphasis navigational link as body font text followed by a
    right-pointing arrow glyph that carries `aria-hidden="true"` and is excluded from the link's
    accessible name, and SHALL treat that glyph as part of the link label carrying the link's
    affordance.
22. THE Frontend SHALL apply a text underline to a link only while a pointer hovers that link or
    that link holds keyboard focus, and SHALL apply no underline to the arrow glyph of criterion 21
    while that link is at rest.
23. THE App_Shell SHALL constrain page content to a maximum width of 1200px, SHALL separate major
    page sections by 80px while the viewport width is 768px or greater and by 40px while the
    viewport width is below 768px, and SHALL apply a horizontal content inset of 24px while the
    viewport width is 768px or greater and 16px while the viewport width is below 768px.
24. THE Frontend SHALL render every primary action control as a filled pill with Ink Black
    background, Paper White text, a 9999px radius, and a minimum height and minimum width of 44px,
    and every secondary action control as a ghost pill with a transparent background, Ink Black
    text, a 1px Smoke Gray border, a 9999px radius, and a minimum height and minimum width of
    44px.
25. WHILE a primary or secondary action control is disabled, THE Frontend SHALL render it with a
    Mist Gray background, Ink Black text, and no border, and SHALL retain the 9999px radius and the
    44px minimum dimensions.
26. THE Frontend SHALL render every input control with a 16px radius and a 1px border in the border
    token defined by criterion 3.
27. THE Token_Layer SHALL declare the display font custom property with a serif fallback stack,
    naming `Signifier` first, then `GT Sectra`, `Tiempos Headline`, and `Source Serif 4`, then
    `ui-serif` and `Georgia`, then the generic keyword `serif`, and SHALL name no sans-serif family
    in that property, because `DESIGN.md` states two conflicting things — its CSS block sets
    `--font-signifier` to the sans-serif stack beginning `ui-sans-serif, system-ui`, while its
    Signifier Substitute line names those serif families and its Do rule states that a sans-serif is
    never substituted at these sizes — and a sans-serif fallback would destroy the editorial
    signature the document exists to protect.
28. THE Frontend SHALL treat criterion 27 as an explicit, justified deviation from the literal CSS
    of `DESIGN.md` rather than as conformance with it, and THE Limitations_Document SHALL record
    that deviation as Requirement 28 criterion 17 requires.
29. THE Frontend SHALL paint every avatar monogram background in Mist Gray or Blush Peach and SHALL
    paint no avatar monogram background in green and none in blue, because `DESIGN.md` states two
    conflicting things — its Avatar Bubble component specifies light green and light blue tinted
    backgrounds, while its own Don't rule admits no chromatic colour beyond the peach and brown pair
    — and this criterion resolves that conflict in favour of the Don't rule.
30. THE Frontend SHALL treat criterion 29 as an explicit, justified deviation from the Avatar Bubble
    component specification of `DESIGN.md`, and THE Limitations_Document SHALL record that deviation
    as Requirement 28 criterion 18 requires.
31. THE Frontend SHALL apply the `display` token at 90px only on the sign-in, registration,
    password-reset, and email-verification surfaces, and SHALL apply it on no authenticated surface,
    because `DESIGN.md` specifies 90px display type for a marketing site and MK00's authenticated
    surface is a data application.
32. THE Frontend SHALL render every authenticated page title through the `heading` token at 44px,
    and SHALL apply the `heading-lg` token at 64px only to an Overview surface heading.
33. THE Frontend SHALL present every data table, the invoice chart, and every Overview metric group
    as a floating product artifact on an Elevated White surface at a 20px radius carrying the
    Floating Product Artifact recipe of criterion 14, because those surfaces are the product
    artifacts of this application.
34. THE Frontend SHALL present every form and every detail field group in a Neutral Card on a Card
    Mist surface at a 24px radius carrying no shadow.
35. WHERE a page renders alternating section bands, THE Frontend SHALL paint those bands in Section
    Fog.
36. THE App_Shell SHALL render the top navigation region with no background colour, no border, and
    no shadow at every scroll position, per the Nav Link and Layout sections of `DESIGN.md`.
37. THE Frontend SHALL reproduce none of the marketing-specific patterns `DESIGN.md` records — the
    hero collage composition, the avatar cursor-pointer motif, and the "Ask anything…" AI composer —
    and SHALL present no navigation destination named Product, Resources, Customers, or Pricing,
    because no Backend capability in Backend Audit Findings section A corresponds to any of them.
38. THE Frontend SHALL present no AI composer, no prompt field, no assistant panel, and no
    free-text query surface, because `core/urls.py` registers no route accepting a prompt and no
    module under `core/services/` performs inference or text generation.
39. THE Frontend SHALL reference every colour, spacing, radius, and font value through a Tailwind
    theme key backed by a Token_Layer custom property, and SHALL contain, in every source file
    other than the Token_Layer stylesheet and the Tailwind theme configuration, no hexadecimal
    colour literal, no `rgb`, `rgba`, `hsl`, or `hsla` literal, and no arbitrary-value utility
    supplying a colour, spacing, radius, or font size.
40. THE Frontend SHALL contain no CSS gradient function, no `backdrop-filter` declaration, no
    `prefers-color-scheme` media query, no dark-theme variant selector, and no colour value outside
    the ten defined in criterion 3, except an alpha variant of one of those ten declared as a
    Token_Layer custom property.
41. THE Frontend SHALL ship no `Signifier` or `Söhne` font file, SHALL declare no `@font-face` rule
    naming either family, and SHALL issue no network request for either family, because both are
    commercially licensed and are not distributed with this Frontend.
42. WHEN neither `Signifier` nor `Söhne` is installed on the viewing device, THE Frontend SHALL
    render every text run from the first installed family named in the corresponding font custom
    property, SHALL present no period during which text is invisible, and SHALL apply no font
    substitution after first paint.
43. THE Token_Layer SHALL define one focus indicator custom property consisting of a 2px solid Ink
    Black outline at a 2px offset, and THE Frontend SHALL apply that property as the focus indicator
    required by Requirement 21 criterion 3 on every focusable control that receives keyboard focus.

### Requirement 4: Application Shell and Role-Derived Navigation

**User Story:** As a signed-in user, I want navigation that shows only the areas my role can
reach, so that the interface matches what I am permitted to do.

#### Acceptance Criteria

1. THE App_Shell SHALL present exactly one top navigation region, rendered with no background
   fill, no border, and no box shadow at every scroll position, and SHALL render no side column
   at any viewport width from 320px to 2560px.
2. THE Nav_Model SHALL declare one entry for each of exactly `owner`, `trainer`, and `member`,
   each entry listing its destinations in display order with a label, a target Frontend route,
   and the Backend method-and-path pairs from Backend Audit Findings section A that the
   destination's surface requires, and THE App_Shell SHALL render navigation destinations solely
   by looking up the `role` value of the `GET /api/me` response body in the Nav_Model, rendering
   zero destinations when that lookup yields no entry.
3. WHILE the signed-in Role is `owner`, THE App_Shell SHALL present exactly seven navigation
   destinations labelled Overview, Members, Trainers, Membership Plans, Invoices, Gym, and
   Profile, in that order, and no other destination.
4. WHILE the signed-in Role is `trainer`, THE App_Shell SHALL present exactly five navigation
   destinations labelled Overview, Members, Membership Plans, Gym, and Profile, in that order,
   and no other destination.
5. WHILE the signed-in Role is `member`, THE App_Shell SHALL present exactly six navigation
   destinations labelled Overview, My Membership, Membership Plans, Invoices, Gym, and Profile,
   in that order, and no other destination.
6. THE App_Shell SHALL present, in the top navigation region, the Gym `name` value, the `email`
   value, and the `role` value returned by `GET /api/me`, each rendered on a single line without
   wrapping, truncated with an ellipsis when it exceeds its available width, and carrying the
   complete untruncated value as that element's accessible name.
7. WHILE the viewport width is below 768px, THE App_Shell SHALL present the Nav_Model
   destinations solely through a single disclosure control that renders closed on first paint and
   carries an accessible name, `aria-expanded="false"`, and an `aria-controls` reference to the
   navigation panel it opens.
8. THE App_Shell SHALL present exactly one toast region, rendered as an ARIA live region with
   polite politeness that survives every route change, presenting at most three toasts at once,
   discarding the oldest when a fourth arrives, giving each toast a dismiss control with an
   accessible name, removing a confirmation toast 5 seconds after it appears, and retaining a
   toast that carries a mapped error message from Requirement 11 until it is dismissed.
9. THE App_Shell SHALL render a navigation destination only for a Frontend route that the
   Nav_Model declares for the signed-in Role and whose surface requires only method-and-path
   pairs listed in Backend Audit Findings section A.
10. WHEN the active Frontend route matches a Nav_Model destination declared for the signed-in
    Role, THE App_Shell SHALL mark exactly that one destination with `aria-current="page"`,
    distinguish it from every other destination by a difference that is not colour alone, and
    mark no destination when the active route matches none.
11. WHILE the viewport width is below 768px, WHEN a user activates the disclosure control, THE
    App_Shell SHALL open a panel occupying the full viewport height that lists the same
    destinations in the same order as criteria 3 through 5, set the disclosure control's
    `aria-expanded` to `true`, move focus to the first destination in the panel, and confine Tab
    and Shift+Tab traversal to the panel while it is open.
12. WHILE the navigation panel is open, WHEN a user presses the Escape key, activates a
    destination in the panel, or the viewport width reaches 768px or greater, THE App_Shell SHALL
    close the panel, set the disclosure control's `aria-expanded` to `false`, and move focus to
    the disclosure control, or to the first navigation destination in the top navigation region
    when the disclosure control is no longer rendered.

### Requirement 5: Authentication Against the Existing Contract

**User Story:** As a user, I want to sign in with the credentials the backend already accepts, so
that no second account system exists.

#### Acceptance Criteria

1. THE Frontend SHALL authenticate solely through `POST /api/auth/login`, `POST
   /api/auth/refresh`, `POST /api/auth/logout`, and `GET /api/me`, and SHALL implement no
   cookie-based session, no HTTP Basic credential, no third-party identity provider, and no other
   authentication mechanism.
2. THE Frontend SHALL submit login credentials as exactly the two fields `identifier` and
   `password`, SHALL remove leading and trailing whitespace from the `identifier` value before
   submitting, SHALL block submission while either field is empty after that removal, and SHALL
   apply no further client-side format constraint to `identifier`, because the Backend accepts
   either an email address or an E.164 phone number in that field.
3. WHEN a login request returns 200 or an owner-registration request returns 201, THE
   Session_Store SHALL record the access and refresh values from that response body — `access` and
   `refresh` for login, `tokens.access` and `tokens.refresh` for registration — and THE Frontend
   SHALL request `GET /api/me` and render no authenticated route until that request returns 200.
4. THE API_Client SHALL attach to every request to a route that Backend Audit Findings section A
   lists as requiring authentication exactly one `Authorization` header whose value is `Bearer `
   followed by the `access` value the Session_Store holds at the moment that request is issued.
5. THE API_Client SHALL attach no `Authorization` header to `POST /api/auth/register/owner`, `POST
   /api/auth/login`, `POST /api/auth/refresh`, `POST /api/auth/verify-email`, `POST
   /api/auth/password-reset`, or `POST /api/auth/password-reset/confirm`, and SHALL send a refresh
   token value only in the request body of `POST /api/auth/refresh` and `POST /api/auth/logout`.
6. WHEN a response to a request other than `POST /api/auth/refresh` carries status 401 with error
   code `TOKEN_EXPIRED`, the Session_Store holds a `refresh` value, and the API_Client has not
   already reissued that request under this criterion, THE API_Client SHALL request `POST
   /api/auth/refresh` once, SHALL replace both stored token values with the `access` and `refresh`
   values of the 200 refresh response before issuing any further request, and SHALL reissue the
   original request exactly once carrying the replaced `access` value.
7. WHILE a refresh request is in flight, THE API_Client SHALL suspend every other request that
   received a 401 response with error code `TOKEN_EXPIRED`, SHALL issue no second refresh request,
   SHALL wait at most 30 seconds for that refresh request to resolve, and, once the Session_Store
   holds the rotated pair, SHALL reissue each suspended request exactly once in the order it was
   suspended carrying the replaced `access` value.
8. IF a refresh request returns a non-2xx status, or returns 200 without both an `access` and a
   `refresh` value, or does not resolve within 30 seconds, THEN THE Frontend SHALL clear the
   Session_Store, SHALL discard every suspended request without reissuing it, SHALL navigate to the
   sign-in route exactly once however many requests were suspended, SHALL present the message "Your
   session has ended. Please sign in again.", and SHALL request no further refresh until a
   subsequent login returns 200.
9. WHEN a response to a request to a route that Backend Audit Findings section A lists as requiring
   authentication carries status 401 with error code `TOKEN_INVALID`, `TOKEN_CONSUMED`, or
   `NOT_AUTHENTICATED`, or carries status 401 with `TOKEN_EXPIRED` while the Session_Store holds no
   `refresh` value, or carries status 401 with `TOKEN_EXPIRED` for a request the API_Client has
   already reissued once under criterion 6, THE Frontend SHALL clear the Session_Store, navigate to
   the sign-in route, and present the message "Your session has ended. Please sign in again."
   without requesting `POST /api/auth/refresh`.
10. WHEN a user activates the sign-out control, THE Frontend SHALL request `POST /api/auth/logout`
    exactly once with the stored `refresh` value, SHALL omit that request when the Session_Store
    holds no `refresh` value, SHALL reissue it no further times, and SHALL clear the Session_Store
    and navigate to the sign-in route whether that request returns 204, returns any other status,
    or does not resolve within 30 seconds.
11. THE Frontend SHALL register an owner through `POST /api/auth/register/owner` sending `email`,
    `password`, `password_confirm`, `business_name`, and `contact_phone` as required inputs and
    `first_name`, `last_name`, `phone`, `gym_name`, `contact_email`, `timezone_name` defaulting to
    `Asia/Kolkata`, and `gstin` as optional inputs, SHALL block submission of any form carrying
    `password` and `password_confirm` while `password` is shorter than 10 characters or the two
    values differ, SHALL constrain each phone input to the pattern `^\+[1-9]\d{7,14}$` at no more
    than 16 characters, and SHALL treat the 201 response's `tokens.access` and `tokens.refresh`
    values as the authenticated session established by criterion 3.
12. THE Frontend SHALL present no self-service registration path that produces a `trainer` or a
    `member`, because `OwnerRegistrationSerializer` declares no `role` field and `register_owner`
    always assigns `owner`.
13. THE Frontend SHALL accept the email-verification token and the password-reset token as text
    entered or pasted into a single form field, SHALL read a `token` URL query parameter as that
    field's initial editable value without submitting the form automatically, SHALL remove leading
    and trailing whitespace from the entered value, SHALL block submission only while that value is
    empty after that removal, and SHALL leave the Session_Store unchanged for every non-2xx
    response from `POST /api/auth/verify-email`, `POST /api/auth/password-reset`, and `POST
    /api/auth/password-reset/confirm`, because the Backend emails a raw single-use code rather than
    a link and those three routes carry no `Authorization` header.
14. WHEN `POST /api/auth/password-reset` returns 202, THE Frontend SHALL present the `detail`
    string from the response body unchanged, and SHALL present an identical message, an identical
    layout, and an identical control state whether or not the submitted address is registered.
15. WHEN `POST /api/auth/password-reset/confirm` returns 200, THE Frontend SHALL clear the
    Session_Store, navigate to the sign-in route, and present the message "Your password has been
    changed. Please sign in with the new password.", because the Backend blacklists every refresh
    token for that user.
16. IF the `GET /api/me` request required by criterion 3 returns a non-2xx status or does not
    resolve within 30 seconds, THEN THE Frontend SHALL clear the Session_Store, SHALL render no
    authenticated route, SHALL navigate to the sign-in route, and SHALL present the mapped message
    for that failure from Requirement 11.
17. IF `POST /api/auth/login`, `POST /api/auth/register/owner`, `POST /api/auth/password-reset`, or
    `POST /api/auth/password-reset/confirm` returns status 429 with error code `RATE_LIMITED`, THEN
    THE Frontend SHALL reissue that request only on a further explicit user activation, SHALL
    disable the submitting control for the `details.retry_after_seconds` value, SHALL treat an
    absent value or a value outside the range 1 to 3600 seconds as 60 seconds, SHALL retain the
    entered `identifier`, `email`, and other non-password values, and SHALL discard every entered
    password value.
18. THE API_Client SHALL request `POST /api/auth/refresh` under no circumstance other than
    criterion 6, SHALL schedule no timer-driven, interval-driven, or pre-emptive refresh, SHALL
    hold at most one refresh request in flight at any moment, and SHALL send as the `refresh` field
    only the value the Session_Store holds when that request is issued and never a value a previous
    200 refresh response has replaced, because the Backend rotates and blacklists each refresh
    token on first use and a concurrent double refresh loses one of the two.

### Requirement 6: Role-Based Interface Gating

**User Story:** As an owner, I want to see controls my role can use and a clear explanation for
the ones it cannot, so that the interface is honest about my permissions.

#### Acceptance Criteria

1. THE Route_Guard SHALL decide route admission solely from the `role` value of the most recent
   successful `GET /api/me` response, SHALL admit a route only when that value appears in that
   route's admitted-role set as recorded in Backend Audit Findings section A, SHALL admit no
   authenticated route while the Session_Store holds no `GET /api/me` payload, and SHALL derive no
   admission decision from the `role` or `gym_id` claim of the access token, because
   `core/permissions.py` re-reads role and Gym from the database on every request.
2. WHEN a user navigates to a route the Route_Guard refuses, THE Frontend SHALL issue no Backend
   request for that route's data, SHALL navigate to the signed-in Role's Overview route replacing
   the refused entry in browser history, and SHALL present the message "That area is not available
   for your role."
3. THE Frontend SHALL render no action control in any state, disabled included, whose route
   excludes the signed-in Role as recorded in Backend Audit Findings section A or whose effect the
   signed-in Role's scope gate refuses unconditionally, including a `trainer` write to a
   `payment`, `invoice`, `creditnote`, or `saasplan` record refused by `TrainerScope`, so that a
   role refusal is expressed by omission while a state refusal is expressed by a disabled control
   whose explanation is associated as Requirement 20 criteria 2 and 3 require.
4. WHILE the signed-in Role is `trainer`, THE Frontend SHALL render no trainers surface, no
   trainer creation control, and no navigation destination to either, and SHALL issue no request to
   `/api/trainers`, because `TrainerListCreateView` declares `allowed_roles = {"owner"}`.
5. WHILE the signed-in Role is `trainer` or `member`, THE Frontend SHALL render every membership
   plan field as non-editable text and SHALL render no plan creation, plan edit, or plan submission
   control, because `MembershipPlanListCreateView` declares `write_roles = {"owner"}`.
6. WHILE the signed-in Role is `trainer` or `member`, THE Frontend SHALL render every gym field as
   non-editable text and SHALL render no gym edit or gym submission control, because
   `GymDetailView` declares `write_roles = {"owner"}`.
7. WHILE the signed-in Role is `member`, THE Frontend SHALL render editable form controls only on
   the surface backed by `PATCH /api/me`, and SHALL issue no POST or PATCH request to any path
   other than `PATCH /api/me`, `POST /api/invoices/{id}/pay`, and the authentication paths of
   Requirement 5, because `MemberSelfScope` refuses a member's unsafe methods on every view and no
   view declares `member_writable`.
8. WHILE `subscription_status` from `/api/me` holds any value other than `trialing` or `active`,
   THE Frontend SHALL render every write control outside the invoice payment surface as disabled
   with a visible explanation that names the reported state, names it "no subscription" when the
   value is null, states that the Backend refuses every create and update request until the
   subscription is `trialing` or `active`, and, for `past_due` and `cancelled`, names settling the
   outstanding invoice as the action that restores write access, because `SubscriptionWriteGate`
   answers 403 `FORBIDDEN` to every unsafe method in that state.
9. WHILE the signed-in Role is `owner` or `member` AND an invoice `status` is `open`, THE Frontend
   SHALL render the invoice payment control required by Requirement 16 criterion 6 as enabled
   whatever the `subscription_status` and `is_active_member` values are, because `InvoicePayView`
   declares `subscription_exempt = True` and is exempt from `ActiveMemberGate`.
10. WHILE the signed-in Role is `member` AND `is_active_member` from `/api/me` is exactly false AND
    criterion 8 does not apply, THE Frontend SHALL render every write control outside the invoice
    payment surface as disabled with the visible explanation "Your membership is not active. Settle
    the outstanding invoice to regain write access.", because `ActiveMemberGate` admits safe methods
    only in that state and is evaluated after `SubscriptionWriteGate`.
11. WHEN a user activates a control the Frontend renders as enabled, THE Frontend SHALL issue that
    control's Backend request without evaluating any further Frontend permission check, so that a
    Frontend gating error yields a Backend refusal rather than an unauthorised effect.
12. IF a Backend response carries status 403, THEN THE Frontend SHALL treat the refusal as
    authoritative, present the mapped message from Requirement 11 criterion 8, issue no automatic
    retry of that request, retain the values already entered in the originating form, and request
    `GET /api/me` once to resynchronise the gating state.
13. IF `GET /api/me` returns 403 with code `FORBIDDEN`, THEN THE Frontend SHALL admit no
    authenticated route, SHALL present the `error.message` value from the Error_Envelope, and SHALL
    render the sign-out control as the only enabled control, because
    `IsAuthenticatedWithProfile` refuses a caller holding no non-soft-deleted profile and a caller
    whose Gym has `is_active` false.
14. WHILE `subscription_status` from `/api/me` holds any value other than `trialing` or `active`
    AND the signed-in Role is `owner` or `trainer`, THE Frontend SHALL render the member creation
    control as disabled with a visible explanation stating that adding a member requires a
    `trialing` or `active` subscription, and SHALL present that explanation in place of the
    criterion 8 explanation for that control, because `RequiresSubscription` is declared only on
    `MemberListCreateView` and answers 402 `SUBSCRIPTION_REQUIRED` where every other unsafe method
    answers 403 `FORBIDDEN`.
15. IF `POST /api/members` returns 402 with code `SUBSCRIPTION_REQUIRED`, THEN THE Frontend SHALL
    present the message required by Requirement 11 criterion 10, SHALL retain the entered member
    creation values, and SHALL present no 403 message and no role-refusal message, so that a
    subscription-required outcome stays distinguishable from a role refusal.

### Requirement 7: Tenant Isolation and Existence Non-Disclosure

**User Story:** As a gym owner, I want the interface to leak nothing about other gyms' records,
so that the isolation the backend enforces is not undone by a message on screen.

#### Acceptance Criteria

1. THE Frontend SHALL include no Gym primary key and no Gym `slug` value in the path, the query
   string, or the body of any Backend request, and SHALL send no request body key named `gym`,
   `gym_id`, `gym_slug`, or `tenant`, because `core/urls.py` registers no gym-scoped path segment
   and `TenantScopedSerializerMixin.to_internal_value` strips a client-supplied `gym` key.
2. THE Frontend SHALL take every displayed and every stored tenant attribute, including the Gym
   `name` and the Gym `timezone`, solely from the `gym` object of the most recent `GET /api/me`
   response, and SHALL accept no tenant attribute from the browser location, from user input, or
   from browser storage written before the current session.
3. IF a request for a detail resource returns 404, THEN THE Frontend SHALL present a not-found
   surface whose visible text consists of the sentence "We could not find that record.", an
   optional fixed heading, and the label of at most one control that navigates to a route the
   signed-in Role may reach, and SHALL include no other text and no word denoting permission,
   ownership, role, tenancy, or another gym.
4. THE Frontend SHALL compose the not-found surface from fixed text alone, and SHALL include in it
   neither the requested identifier, nor the requested path, nor any value taken from the 404
   response body.
5. THE Frontend SHALL construct a detail route link only from an identifier present in a Backend
   response the current session already received, and SHALL discard every retained identifier at
   the same moment the Query_Layer discards its cached responses under criteria 7 and 8.
6. THE Frontend SHALL present no control that accepts a typed, pasted, or stepped record
   identifier for navigation to a detail route, and SHALL derive no identifier by arithmetic on,
   or by iteration over, an identifier it has received.
7. WHEN a `GET /api/me` response reports a `role` value or a Gym identity differing from the value
   held in the Session_Store, THE Query_Layer SHALL cancel every in-flight Backend request,
   discard every cached Backend response and every retained identifier, and complete that discard
   before any authenticated surface renders.
8. WHEN the Session_Store is cleared, THE Query_Layer SHALL cancel every in-flight Backend
   request, discard every cached Backend response and every retained identifier, and retain no
   Backend response value in browser storage.
9. IF a detail route is entered with an identifier the current session has not received in a
   Backend response, such as a reloaded or bookmarked location, THEN THE Frontend SHALL issue at
   most one Backend request for that identifier per navigation, SHALL issue no Backend request for
   any other identifier, and SHALL apply criteria 3 and 4 to a 404 response.
10. THE Frontend SHALL render the not-found surface so that its accessible text content and its
    element structure compare equal across a 404 caused by an identifier matching no record on the
    platform, a 404 caused by an identifier belonging to another Gym, and a 404 caused by an
    identifier belonging to another member of the signed-in user's own Gym, and SHALL apply the
    same browser location and the same toast content to all three.
11. IF a request returns 403, THEN THE Frontend SHALL present the mapped message required by
    Requirement 11 criterion 8, and SHALL present neither the not-found surface nor any statement
    that the record does not exist.

### Requirement 8: Pagination, and the Deliberate Absence of Search, Filter, and Sort

**User Story:** As an owner with many members, I want to page through the real list, and I want
the interface to be honest that it cannot search, so that I never trust an incomplete result.

#### Acceptance Criteria

1. THE Data_List SHALL request a Backend collection page with `page` as the only query parameter,
   whose value is either the integer 1 or the integer carried by the `next` or `previous` URL of a
   paginated response the current session already received, and SHALL send no `page_size`,
   `search`, `ordering`, or filter parameter, because `PageNumberPagination` is configured with no
   `page_size_query_param` and no filter backend is registered.
2. THE Data_List SHALL read `count`, `next`, `previous`, and `results` from the paginated response
   body, SHALL enable its next-page control only while `next` is non-null and its previous-page
   control only while `previous` is non-null, and SHALL present no page-number jump control and no
   page total computed from `count`.
3. THE Data_List SHALL present, in one visible summary, the `count` value labelled as the
   collection total and the number of entries in `results` labelled as the rows on the current
   page, and SHALL present at most 25 rows per page because the Backend serves 25 rows per page.
4. THE Frontend SHALL present no text input, select control, column header control, menu item, or
   URL parameter whose effect is to search, filter, sort, reorder, or change the page size of a
   Backend collection.
5. THE Data_List SHALL present the note "This list is ordered and paged by the server. Search and
   filtering are not available." as visible text on every page of every collection it renders,
   without requiring hover, focus, or a disclosure control to reveal it.
6. THE Frontend SHALL render the entries of a `results` array in the index order received, SHALL
   remove no entry, SHALL insert no entry, and SHALL apply no client-side predicate or comparator
   that changes which rows a Data_List presents or the order in which it presents them.
7. THE Data_List SHALL present each Backend collection in the order the response supplies and
   SHALL present no affordance suggesting that order can be changed, because ordering is fixed
   server-side: trainers by `pk`, members by `-join_date` then `pk`, membership plans by `price`,
   SaaS plans by `price`, and invoices by `-issue_date` then `-sequence_no`.
8. WHERE a Frontend view requires the complete contents of a collection rather than one page, THE
   Frontend SHALL request page 1 and then each subsequent page one at a time, deriving each page
   number from the previous response's `next` value, holding at most one page request of that
   traversal in flight, stopping when the most recent response's `next` value is null or when 40
   page requests have been issued, and SHALL present, while any page of that traversal is
   outstanding, the loading state of Requirement 12 criterion 1 together with the number of pages
   already received and the `count` value from the first page response.
9. IF a page request within a complete-collection traversal returns a non-2xx response, fails
   without a response, or does not resolve within 15 seconds, THEN THE Frontend SHALL issue no
   further page request for that traversal, discard every page already received for it, render no
   rows, chart, or aggregate from those pages, present the mapped message from Requirement 11, and
   present a retry control that restarts that traversal from page 1.
10. IF a complete-collection traversal reaches 40 page requests while the most recent response's
    `next` value is non-null, THEN THE Frontend SHALL issue no further page request for that
    traversal, SHALL render no chart and no aggregate from the pages received, SHALL present the
    unresolved identifier wherever a name resolution depended on that traversal, and SHALL present
    a visible message stating that the collection holds more than the 1,000 records the Frontend
    retrieves.
11. WHERE a complete-collection traversal targets `GET /api/invoices`, THE Frontend SHALL start
    that traversal at most once per entry to the surface requiring it, SHALL restart it only when
    the user activates a refresh control or a write issued from that surface invalidates it, and
    SHALL start no interval-triggered and no window-focus-triggered traversal, because
    `InvoiceListView.list` calls `ensure_period_invoice` on every request.

### Requirement 9: Money Rendering Without Precision Loss

**User Story:** As an owner reading an invoice, I want the amount on screen to equal the amount
the backend stored, so that no rounding artefact ever appears in a financial figure.

#### Acceptance Criteria

1. THE Money_Formatter SHALL accept a money value as the decimal string the Backend supplied, of
   at most 12 total digits with exactly 2 digits after the decimal point, and SHALL produce a
   display string carrying the same digits in the same order with the decimal point in the same
   position, by operating on that value as text and constructing no JavaScript `number` from it
   at any point.
2. THE Frontend SHALL perform no addition, subtraction, multiplication, division, rounding, or
   truncation on `price`, `taxable_value`, `cgst`, `sgst`, `igst`, `total_amount`, or `amount`,
   and SHALL present no total, subtotal, difference, average, or percentage derived from any of
   those fields.
3. THE Money_Formatter SHALL render a money value as the three-letter `currency` code taken from
   the same Backend response object, then one space, then the value's integer digits with a comma
   inserted between each group of three digits counted leftward from the decimal point, then a
   period, then the two fraction digits exactly as supplied, so that the string `"1500.00"` with
   `currency` `INR` renders as `INR 1,500.00`, and SHALL substitute no currency symbol and apply
   no default currency code.
4. THE Frontend SHALL render `cgst`, `sgst`, `igst`, or `hsn_sac` as the text "Not applicable"
   with no currency code when the Backend value is null, and SHALL render the value `"0.00"`
   through the Money_Formatter, so that a tax that does not apply and a tax of zero are visibly
   distinct.
5. THE Frontend SHALL pass `amount_minor` to the Payment_Gateway checkout handoff as the integer
   the Backend supplied, SHALL label it as a gateway order amount in minor units wherever it is
   displayed, SHALL render it through no Money_Formatter output, and SHALL divide, scale, or
   otherwise convert it to a major-unit amount at no point.
6. THE Frontend SHALL render `join_date`, `issue_date`, `due_date`, `start_date`, `end_date`, and
   `current_period_end` from the year, month, and day components of the supplied ten-character
   value with no timezone conversion and no offset shift, and SHALL render the text "Not set" when
   the value is null.
7. THE Frontend SHALL render `paid_at` as a date and a time of day converted to the Gym `timezone`
   value returned by `/api/me`, and SHALL display that `timezone` value adjacent to the rendered
   timestamp.
8. IF a money value or its accompanying `currency` code is absent, OR a money value is null on a
   field other than those named in criterion 4, OR a money value does not match a decimal string
   of at most 12 total digits with exactly 2 digits after the decimal point, THEN THE Frontend
   SHALL present the text "Unavailable" in place of that amount, SHALL render no partial digits,
   and SHALL present no text implying the value is zero.
9. THE Frontend SHALL hold every money input value as text from entry through submission, SHALL
   accept at most 10 digits before the decimal point and at most 2 digits after it, and SHALL
   place that value in the request body as the string the user entered, applying no numeric
   conversion and no reformatting.
10. THE Frontend SHALL render every displayed money value through the Money_Formatter, except the
    null tax fields covered by criterion 4, the minor-unit integer covered by criterion 5, and the
    placeholder covered by criterion 8.

### Requirement 10: Derived State Is Read, Never Recomputed

**User Story:** As a member, I want my membership status to match what the backend says, so that
the interface and the system never disagree.

#### Acceptance Criteria

1. THE Frontend SHALL present the signed-in user's member active state solely from the
   `is_active_member` field of `GET /api/me`, SHALL present any other member's active state solely
   from the `is_active` field of a `MemberProfileSerializer` body, and SHALL render either value as
   the visible text "Active" when the value is true and "Not active" when the value is false.
2. THE Frontend SHALL present the membership period end solely from the `current_period_end`
   field, rendered as the supplied `YYYY-MM-DD` calendar date with no timezone conversion, and
   SHALL present the visible text "No end date recorded" when that field is null.
3. THE Frontend SHALL present subscription state solely from the `subscription_status` field of
   `GET /api/me`, SHALL recognise exactly the values `trialing`, `active`, `past_due`,
   `cancelled`, and null, and SHALL render each non-null value as a distinct visible text label
   rather than through colour alone.
4. THE Frontend SHALL derive no active flag, no membership status, no expiry, no remaining-days
   figure, and no overdue figure from a browser clock reading, a browser date comparison, a
   timezone conversion, or arithmetic over `join_date`, `current_period_end`, `issue_date`, or
   `due_date`, SHALL present no optimistically predicted Derived_State value following a write,
   and SHALL present each Derived_State value only as received in a Backend response body, because
   the Backend computes every such value per request in the Gym's `timezone`, stores none of them,
   and derives `past_due` from that calendar rather than from a scheduled job.
5. WHILE `is_active_member` from `GET /api/me` is null, THE Frontend SHALL present no membership
   active state and no membership period end for the signed-in user on any surface, because the
   Backend returns null for the `owner` and `trainer` Roles, and SHALL continue to present the
   `is_active` value of each member record that Role may read.
6. WHILE `subscription_status` from `GET /api/me` is null, THE Frontend SHALL present the visible
   text "No subscription" as the subscription state and SHALL present, adjacent to it, the
   explanation that member creation is unavailable until a subscription exists, because
   `RequiresSubscription` answers 402 `SUBSCRIPTION_REQUIRED` in that state.
7. THE Frontend SHALL present `email_verified` from `GET /api/me` as the visible text "Verified"
   when the value is true and "Not verified" when the value is false, SHALL present the visible
   explanation that verification is completed by entering the token from the registration email,
   and SHALL present no resend or reissue control for email verification, because the Backend
   registers no resend route.
8. THE Query_Layer SHALL mark every Derived_State value stale 60 seconds after the Backend
   response that supplied it was received, and SHALL continue presenting the last received value
   until a newer response for that read resolves.
9. WHILE a presented Derived_State value is marked stale, WHEN the surface presenting that value
   becomes active or the browser window regains focus, THE Frontend SHALL reissue the Backend read
   that supplied that value and SHALL replace the presented value with the value carried by that
   response, because the Backend recomputes Derived_State from the Gym's calendar on every
   request.
10. IF the `subscription_status` value in a `GET /api/me` response falls outside the set
    `trialing`, `active`, `past_due`, `cancelled`, and null, THEN THE Frontend SHALL present no
    subscription state label, SHALL present a message indicating the reported subscription state
    is unrecognised, and SHALL present every other field of that response unchanged.

### Requirement 11: Exhaustive Error Envelope Mapping

**User Story:** As a user, I want a clear sentence when something fails, so that I know what
happened and what to do next, and never see a stack trace.

#### Acceptance Criteria

1. THE Error_Mapper SHALL derive every user-facing failure message solely from the `error.code`
   string, the `error.message` string, and the optional `error.details` object of a non-2xx
   response body, and SHALL treat `error.details` and each of its keys as absent when omitted,
   because the Backend omits `details` entirely when empty.
2. THE Error_Mapper SHALL define exactly one mapping entry for each of the twenty-two codes
   listed in Backend Audit Findings section G — `INVALID_CREDENTIALS`, `TOKEN_EXPIRED`,
   `TOKEN_INVALID`, `TOKEN_CONSUMED`, `AUTH_UNAVAILABLE`, `NOT_AUTHENTICATED`, `FORBIDDEN`,
   `NOT_FOUND`, `VALIDATION_ERROR`, `SEAT_LIMIT_REACHED`, `PLAN_DOWNGRADE_BLOCKED`,
   `SUBSCRIPTION_REQUIRED`, `INVOICE_ALREADY_PAID`, `INVOICE_IMMUTABLE`, `CURRENCY_MISMATCH`,
   `GATEWAY_ERROR`, `CARD_DATA_REJECTED`, `SIGNATURE_INVALID`, `RATE_LIMITED`,
   `METHOD_NOT_ALLOWED`, `CONFLICT`, `SERVER_ERROR` — SHALL return for each entry other than
   `SIGNATURE_INVALID` a non-empty message of 1 to 200 characters, and SHALL assign each entry
   exactly one classification from the set `user_actionable`, `session_ended`, `frontend_defect`,
   `unexpected`, and `unreachable`.
3. IF a non-2xx response body is not a JSON object carrying an `error` object with a non-empty
   string `code` and a string `message`, OR the `code` value is outside the twenty-two-code
   catalogue, THEN THE Error_Mapper SHALL present the message "Something went wrong. Please try
   again." and SHALL classify the failure as `unexpected`.
4. IF a request receives no response within 30 seconds or fails before any response is received,
   THEN THE Frontend SHALL present the message "We could not reach the server. Check your
   connection and try again.", SHALL present a retry control that reissues that request, and SHALL
   retain every value already entered in the submitting form.
5. IF a response carries status 400 with code `VALIDATION_ERROR` AND `details.field` is present
   AND a rendered form control's name equals the `details.field` value, THEN THE Frontend SHALL
   attach the `error.message` value to that control, SHALL set `aria-invalid` on that control, and
   SHALL move focus to that control.
6. IF a response carries status 400 with code `VALIDATION_ERROR` AND `details.field` is absent OR
   no rendered form control's name equals the `details.field` value, THEN THE Frontend SHALL
   present the `error.message` value at form level and SHALL retain every value already entered in
   that form.
7. IF a response carries status 401 with code `TOKEN_EXPIRED`, `TOKEN_INVALID`, or
   `NOT_AUTHENTICATED`, THEN THE Frontend SHALL apply Requirement 5 criteria 6 through 9, SHALL
   classify the failure as `session_ended`, and SHALL present no form-level validation message.
8. IF a response carries status 403 with code `FORBIDDEN`, THEN THE Frontend SHALL present the
   `error.message` value, SHALL present the mapping entry's message from criterion 2 when
   `error.message` is empty, SHALL leave the Session_Store unchanged, and SHALL issue no automatic
   retry of that request, because `SubscriptionWriteGate`, `ActiveMemberGate`, `RoleAllowed`,
   `TrainerScope`, and `MemberSelfScope` each supply a distinct and actionable message.
9. IF a response carries status 404 with code `NOT_FOUND`, THEN THE Frontend SHALL apply
   Requirement 7 criteria 3 and 4, SHALL present its own fixed message rather than the
   `error.message` value, and SHALL present no statement about permissions, ownership, roles, or
   another tenant.
10. IF a response carries status 402 with code `SUBSCRIPTION_REQUIRED`, THEN THE Frontend SHALL
    present the message "This gym has no trialing or active subscription, so members cannot be
    added.", SHALL present a link to the invoice surface, and SHALL retain every value already
    entered in the member creation form.
11. IF a response carries status 405 with code `METHOD_NOT_ALLOWED`, THEN THE Frontend SHALL
    classify the failure as `frontend_defect`, SHALL present the message "That action is not
    available here.", and SHALL present no retry control.
12. IF a response carries status 409 with code `SEAT_LIMIT_REACHED`, THEN THE Frontend SHALL
    present a message containing the `details.seat_count` and `details.limit` integer values, and
    SHALL present the mapping entry's message from criterion 2 without figures when either key is
    absent.
13. IF a response carries status 409 with code `PLAN_DOWNGRADE_BLOCKED`, THEN THE Frontend SHALL
    present a message containing the `details.seat_count` and `details.limit` integer values, and
    SHALL present the mapping entry's message from criterion 2 without figures when either key is
    absent.
14. IF a response carries status 409 with code `INVOICE_ALREADY_PAID`, THEN THE Frontend SHALL
    present the message "This invoice has already been paid.", SHALL request that invoice again
    through `GET /api/invoices/{id}` so the displayed `status` matches the server, and SHALL
    present no further payment control for that invoice.
15. IF a response carries status 409 with code `INVOICE_IMMUTABLE` or `CONFLICT`, THEN THE Frontend
    SHALL present the `error.message` value, and SHALL present the mapping entry's message from
    criterion 2 when `error.message` is empty.
16. IF a response carries status 429 with code `RATE_LIMITED`, THEN THE Frontend SHALL disable the
    submitting control for the duration given by `details.retry_after_seconds`, SHALL use 60
    seconds when that key is absent, SHALL clamp the duration to the range 1 to 300 seconds
    inclusive, SHALL present the remaining whole seconds of that duration, and SHALL re-enable the
    control when the duration elapses.
17. IF a response carries status 500 with code `AUTH_UNAVAILABLE`, THEN THE Frontend SHALL present
    the message "Sign-in is temporarily unavailable. Please try again in a moment.", SHALL retain
    the entered `identifier` value, SHALL discard the entered `password` value, and SHALL leave the
    Session_Store unchanged.
18. IF a response carries status 500 with code `SERVER_ERROR`, THEN THE Frontend SHALL present the
    message "Something went wrong on the server. Please try again." and SHALL reissue the failed
    request only when the user activates a retry control, so that no unsafe method is repeated
    automatically.
19. IF a response carries status 502 with code `GATEWAY_ERROR`, THEN THE Frontend SHALL present the
    message "The payment gateway could not be reached. No payment was recorded.", SHALL leave the
    displayed invoice `status` unchanged, and SHALL present a retry control that reissues the
    payment initiation request.
20. IF a response carries code `CARD_DATA_REJECTED`, THEN THE Frontend SHALL classify the failure
    as `frontend_defect`, SHALL present the unexpected-failure message from criterion 3, and SHALL
    attach the message to no form control, because the Frontend SHALL send no card data field to
    the Backend under any circumstance.
21. THE Frontend SHALL present no stack trace, no exception class name, no HTTP method, no request
    URL, no raw response body, and no verbatim rendering of the `error.details` object in any
    user-facing surface.
22. THE Error_Mapper SHALL classify code `SIGNATURE_INVALID` as `unreachable`, and THE Frontend
    SHALL present no message for that code, because it is reachable only through the
    Payment_Gateway webhook route, which the Frontend never requests.
23. IF a response carries code `INVALID_CREDENTIALS`, THEN THE Frontend SHALL present the message
    "That identifier and password do not match." at form level, SHALL present no indication of
    whether the submitted identifier is registered, SHALL retain the entered `identifier` value,
    SHALL discard the entered `password` value, and SHALL leave the Session_Store unchanged.
24. IF a response carries code `TOKEN_CONSUMED` for a request other than `POST /api/auth/refresh`,
    THEN THE Frontend SHALL present a message indicating that the submitted code has already been
    used and that a new code must be requested, SHALL present a control that navigates to the
    password reset request surface when the consumed value was a password-reset token, and SHALL
    present no resend control when the consumed value was an email-verification token, because no
    resend route exists and Requirement 5 criterion 8 governs a consumed refresh token.
25. IF a response carries code `CURRENCY_MISMATCH`, THEN THE Frontend SHALL present the
    `error.message` value, SHALL leave every displayed field of the affected record unchanged,
    SHALL retain every value already entered in the submitting form, and SHALL present no automatic
    retry of that request.

### Requirement 12: Loading, Empty, and Error States on Every Data Surface

**User Story:** As a user on a slow connection, I want to see the shape of what is loading and a
composed message when there is nothing, so that the interface never looks broken.

#### Acceptance Criteria

1. WHILE a Backend read for a surface has not settled AND the Query_Layer holds no previously
   resolved response for that read, THE Frontend SHALL present that surface's skeleton within 100
   milliseconds of the request being issued, with 25 row placeholders for a collection read
   because `PAGE_SIZE` is 25, one placeholder per presented field for a single-object read, the
   same column count as that surface's resolved content, and each placeholder within 4 CSS pixels
   of the height and the width of the element it stands in for.
2. WHERE Backend Audit Findings section A lists a create route for a collection that admits the
   signed-in Role, WHEN a Backend read for that collection settles with a 2xx status and a `count`
   of 0, THE Frontend SHALL present an empty state containing one heading, exactly one explanatory
   sentence, and that collection's create action, rendered disabled with the explanation required
   by Requirement 20 criterion 2 while Requirement 6 criterion 8 or Requirement 6 criterion 10
   disables writes for the current session, and rendered enabled otherwise.
3. IF a Backend read settles with a non-2xx status other than 404, or does not settle within 30
   seconds of the request being issued, THEN THE Frontend SHALL present an error state containing
   the mapped message from Requirement 11 and a retry control, SHALL present no row placeholder,
   no partial content, and no empty state for that read, SHALL discard every page already received
   for a multi-page read performed under Requirement 8 criterion 8, and SHALL reissue that read
   with the same `page` value only when the retry control is activated, because Requirement 11
   criterion 9 routes a 404 to Requirement 7 criteria 3 and 4 instead.
4. THE Frontend SHALL present a loading state, an empty state, and an error state, each as defined
   by criteria 1 through 3 and 8 through 10, for the members surface, the trainers surface, the
   membership plans surface, the invoices surface, the invoice detail surface, the member detail
   surface, the My Membership surface, the gym surface, the profile surface, and each Overview
   surface.
5. THE Frontend SHALL present no skeleton placeholder for a field name absent from that surface's
   serializer field set as recorded in Backend Audit Findings sections C and E, no skeleton
   placeholder for a value Backend Audit Findings section K records as unobtainable, and no
   skeleton on a surface for which the Query_Layer holds a previously resolved response, and SHALL
   instead present that resolved content with a pending indication while a refetch for that
   surface is in flight.
6. WHILE a write request issued from a Frontend form is in flight, THE Frontend SHALL render that
   form's submitting control disabled with a pending indication, SHALL issue no further request
   from that form, SHALL perform no automatic retry of that write, and SHALL re-enable that
   control within 100 milliseconds of the request settling unless the Frontend navigates away from
   that form.
7. WHEN a write request settles with a 2xx status, THE Frontend SHALL invalidate exactly the
   Query_Layer entries listed below for that write and SHALL present one confirmation toast that
   remains visible for 5 seconds or until dismissed:
   - `POST /api/members`: the `/api/members` collection entry for every cached page.
   - `PATCH /api/members/{id}`: the `/api/members/{id}` entry for that identifier and the
     `/api/members` collection entry for every cached page.
   - `POST /api/trainers`: the `/api/trainers` collection entry for every cached page.
   - `POST /api/membership-plans`: the `/api/membership-plans` collection entry for every cached
     page.
   - `PATCH /api/membership-plans/{id}`: the `/api/membership-plans/{id}` entry for that
     identifier and the `/api/membership-plans` collection entry for every cached page.
   - `PATCH /api/me`: the `/api/me` entry.
   - `PATCH /api/gym`: the `/api/gym` entry and the `/api/me` entry, because `/api/me` carries the
     `gym` object.
   - `POST /api/invoices/{id}/pay`: the `/api/invoices/{id}` entry for that identifier and the
     `/api/invoices` collection entry for every cached page.
8. WHERE Backend Audit Findings section A lists no create route for a collection that admits the
   signed-in Role, WHEN a Backend read for that collection settles with a 2xx status and a `count`
   of 0, THE Frontend SHALL present an empty state containing one heading and exactly one
   explanatory sentence naming the absent Backend capability, and SHALL present no create control.
9. IF a Backend read for the invoice detail surface, the member detail surface, the My Membership
   surface, the gym surface, or the profile surface settles with a 2xx body in which every field
   that surface presents other than `id`, `email`, and `role` is null or an empty string, THEN THE
   Frontend SHALL present that surface's empty state containing one heading and exactly one
   sentence naming the values the Backend did not supply, and SHALL present no error state for
   that read.
10. THE Frontend SHALL render exactly one of the loading state, the empty state, the error state,
    and the resolved content for each surface region fed by a single Backend read at any moment,
    selecting the error state when criterion 3 applies to that read, the empty state when
    criterion 2, criterion 8, or criterion 9 applies to that read, the loading state when
    criterion 1 applies to that read, and the resolved content otherwise, and SHALL apply this
    selection independently per region on a surface composing more than one Backend read, such as
    each Overview surface.

### Requirement 13: Members Surface

**User Story:** As an owner, I want to add members and maintain their assignment and plan, so that my roster in the system matches my gym.

#### Acceptance Criteria

1. THE Frontend SHALL present the members surface to the `owner` and `trainer` Roles only, SHALL
   populate it from `GET /api/members` requesting page 1 on first render, SHALL request any further
   page only through the page controls of Requirement 8, and SHALL render at most one Backend page
   of rows at a time.
2. THE Frontend SHALL present, for each member row, the `email`, `full_name`, `join_date`, `goal`,
   `is_active`, and `current_period_end` fields returned by `MemberProfileSerializer`, SHALL
   render `is_active` as the text "Active" when true and "Not active" when false, SHALL render
   `current_period_end` as the text "No period end" when null, and SHALL render `goal` as the text
   "Not set" when the returned value is empty.
3. THE Frontend SHALL resolve the `plan` identifier to that plan's `name` from a `GET
   /api/membership-plans` collection retrieved page by page until `next` is null as described in
   Requirement 8 criterion 8, SHALL present the `plan` identifier itself when that collection
   contains no plan with that identifier or when the collection request fails, and SHALL present
   the text "No plan" when `plan` is null.
4. WHILE the signed-in Role is `owner`, THE Frontend SHALL resolve the `trainer` identifier to
   that trainer's `full_name` from a `GET /api/trainers` collection retrieved page by page until
   `next` is null, SHALL present the `trainer` identifier itself when that collection contains no
   trainer with that identifier or when the collection request fails, and SHALL present the text
   "No trainer assigned" when `trainer` is null.
5. WHILE the signed-in Role is `trainer`, THE Frontend SHALL present the `trainer` field of every
   member row as the text "Assigned to you" and SHALL issue no `GET /api/trainers` request, because
   that route returns 403 for a trainer and `TrainerScope` admits a trainer only to members whose
   `trainer` foreign key is that trainer.
6. THE Frontend SHALL create a member through `POST /api/members` with `email` and `join_date` as
   required inputs and `first_name`, `last_name`, `phone`, `plan`, `trainer`, `goal`, and
   `photo_url` as optional inputs, and SHALL omit from the request body every optional input the
   user left empty rather than sending an empty value.
7. THE Frontend SHALL validate, before issuing a member creation or a member update request,
   `email` as an email address, `phone` against the pattern `^\+[1-9]\d{7,14}$` at 16 characters
   or fewer, `join_date` as a calendar date submitted in `YYYY-MM-DD` form, `goal` as one of
   `strength`, `aesthetics`, `cut`, `bulk`, or unset, and `photo_url` as an absolute URL, and SHALL
   issue no request while any of those checks fails.
8. WHILE the signed-in Role is `trainer`, THE Frontend SHALL omit the `trainer` input from the
   member creation form and SHALL send no `trainer` key in the creation request body, because
   `MemberListCreateView.create` overrides that value with the requesting trainer's own profile.
9. WHEN a member creation request returns 201, THE Frontend SHALL present the message "Member
   created. The member has no sign-in credentials yet and must use the password reset flow to set
   a password." in a region that remains visible until the user dismisses it, and SHALL invalidate
   every cached `GET /api/members` page so the collection is read from the Backend again, because
   `create_member_atomically` sends no invitation email and discards the generated password.
10. THE Frontend SHALL update a member through `PATCH /api/members/{id}` with `plan`, `trainer`,
    `join_date`, `goal`, and `photo_url` as the only editable fields, SHALL request that route
    only with an identifier taken from a `GET /api/members` response the current session already
    received, and SHALL send only the fields whose values the user changed.
11. THE Frontend SHALL present `photo_url` as a URL text input and SHALL present no file selection
    control, because the field is a `URLField` and no upload route exists.
12. THE Frontend SHALL present the member detail surface to the `owner` and `trainer` Roles only,
    SHALL request `GET /api/members/{id}` only with an identifier taken from a `GET /api/members`
    response the current session already received, and SHALL apply Requirement 7 criteria 3 and 4
    when that request returns 404.
13. THE Frontend SHALL present the My Membership surface to the `member` Role populated from `GET
    /api/me` and from `GET /api/members/{member_profile_id}`, and SHALL take that path identifier
    solely from the `member_profile_id` field of the `GET /api/me` response the current session
    already received, because `MemberSelfScope.has_object_permission` compares
    `_owning_member_id(obj)` to `ctx.profile.pk` and `_owning_member_id` returns `obj.pk` for a
    `MemberProfile`, so a member is admitted to their own member record.
14. THE Frontend SHALL present, on the My Membership surface, the `plan`, `trainer`, `join_date`,
    `goal`, and `photo_url` values from the `GET /api/members/{member_profile_id}` response, SHALL
    resolve the `plan` identifier to a plan name through `GET /api/membership-plans` as
    Requirement 13 criterion 4 requires, and SHALL apply Requirement 13 criterion 5 to the
    `trainer` identifier, because `GET /api/trainers` returns 403 for a `member` Role and no
    trainer name is resolvable.
15. THE Frontend SHALL render every control on the My Membership surface as read-only, SHALL
    present no member edit form and no member update control to the `member` Role, and SHALL issue
    no `PATCH /api/members/{id}` request while the signed-in Role is `member`, because
    `MemberSelfScope.has_permission` refuses a member's unsafe methods unless the view declares
    `member_writable` and no view declares it.
16. IF the `member_profile_id` field of a `GET /api/me` response is absent or null while the
    signed-in Role is `member`, THEN THE Frontend SHALL issue no `GET /api/members/{id}` request,
    SHALL present the My Membership surface from `GET /api/me` alone, and SHALL present a visible
    note stating that the assigned plan, assigned trainer, join date, goal, and photo URL are not
    retrievable.
17. THE Frontend SHALL present no member deletion, deactivation, or archive control, because no
    route accepts DELETE and `MemberProfile` exposes no writable status field.
18. THE Frontend SHALL present, on the members surface, a note that remains visible while that
    surface is displayed stating that starting or renewing a paid membership period is not
    available through the API and that a member created here therefore carries `is_active` false
    and `current_period_end` null.
19. WHILE the signed-in Role is `trainer`, THE Frontend SHALL omit the `trainer` control from the
    member edit form and SHALL send no `trainer` key in the update request body, because `GET
    /api/trainers` returns 403 for a trainer and no trainer identifier is therefore selectable.
20. IF a `POST /api/members` request returns a non-2xx status, THEN THE Frontend SHALL keep the
    creation form open with every entered value retained, SHALL present the mapped message from
    Requirement 11 attached to the control named by `details.field` when that key is present and
    at form level otherwise, and SHALL add no member row to the rendered collection.
21. IF a `PATCH /api/members/{id}` request returns a non-2xx status, THEN THE Frontend SHALL
    retain every entered value in the edit form, SHALL present the mapped message from Requirement
    11, and SHALL continue to present the field values from the most recent successful read of
    that member.

### Requirement 14: Trainers Surface

**User Story:** As an owner, I want to add trainers and see who is on staff, so that I can assign
members to them.

#### Acceptance Criteria

1. WHILE the signed-in Role is `owner`, THE Frontend SHALL present the trainers surface populated
   from `GET /api/trainers` requested with `page` as its only query parameter, and THE Frontend
   SHALL present the trainers surface to no other Role, because `TrainerListCreateView` declares
   `allowed_roles = {"owner"}`.
2. THE Frontend SHALL present, for each trainer record, the `email`, `full_name`,
   `specialization`, and `status` fields returned by `TrainerProfileSerializer`, SHALL recognise
   exactly the `status` values `active` and `inactive`, and SHALL present `status` as a text label
   rather than through colour alone.
3. THE Frontend SHALL create a trainer through `POST /api/trainers` sending only the field names
   `email`, `first_name`, `last_name`, `phone`, and `specialization`, with `email` as the required
   input and the remaining four as optional inputs, and SHALL omit from the request body each
   optional field whose control is empty.
4. WHEN a trainer creation request returns 201, THE Frontend SHALL present the message "Trainer
   created. An email with a temporary password has been sent." because `invite_trainer` calls
   `send_invite_email` with a generated password, SHALL present no password value, because the 201
   `TrainerProfileSerializer` body carries no password field, and SHALL re-request the trainers
   collection page currently presented so the displayed roster matches the Backend.
5. THE Frontend SHALL present no trainer edit control, no trainer detail route, and no control
   that navigates from a trainer record to a detail surface, because `core/urls.py` registers no
   `trainers/{id}` path.
6. THE Frontend SHALL present no trainer deletion, deactivation, or archive control, and SHALL
   render `specialization` and `status` as read-only values, because no route accepts DELETE and
   no route accepts a PATCH to `TrainerProfile.specialization` or `TrainerProfile.status`.
7. THE Frontend SHALL present, on the trainers surface at every viewport width and without
   requiring hover, keyboard focus, or activation of any control, the visible note that a
   trainer's `specialization` and `status` cannot be changed after creation because the API
   exposes no trainer update route.
8. IF a trainer record's `full_name` or `specialization` value is an empty string or null, THEN
   THE Frontend SHALL present the text "Not provided" in that field's place, because
   `first_name`, `last_name`, and `specialization` are optional at creation.
9. THE Frontend SHALL validate `email` as an email address and `phone` against the pattern
   `^\+[1-9]\d{7,14}$` at a maximum of 16 characters before submitting a trainer creation
   request, and SHALL issue no request while either control holds a value failing that
   validation.
10. IF a trainer creation request returns 400 with code `VALIDATION_ERROR`, THEN THE Frontend
    SHALL attach `error.message` to the control whose name equals `details.field` when that key is
    present, SHALL present the message at form level when that key is absent, SHALL retain every
    value already entered in the form, and SHALL issue no further creation request until the owner
    resubmits, because `email` is unique case-insensitively and `phone` is unique platform-wide.

### Requirement 15: Membership Plans Surface

**User Story:** As an owner, I want to define the packages my gym sells, so that members can be
assigned to a plan.

#### Acceptance Criteria

1. THE Frontend SHALL present the membership plans surface to the `owner`, `trainer`, and
   `member` Roles, SHALL populate it from `GET /api/membership-plans` through the Data_List
   behaviour of Requirement 8, and SHALL present the returned plans in the order the response
   supplies, because ordering is fixed server-side by `price`.
2. THE Frontend SHALL present, for each plan, the `name` value, the `price` value rendered by the
   Money_Formatter using the `currency` value carried by that same plan object, the
   `duration_days` value, and a text label stating whether `includes_trainer` is true and whether
   `includes_diet` is true, from the fields returned by `MembershipPlanSerializer`.
3. WHILE the signed-in Role is `owner`, WHEN a user submits the plan creation form, THE Frontend
   SHALL request `POST /api/membership-plans` with `name`, `price`, and `duration_days` as
   required inputs and `currency`, `includes_trainer`, and `includes_diet` as optional inputs,
   SHALL send no field name outside those six, and SHALL omit each optional input the user leaves
   unset, because the Backend applies `INR`, false, and false as defaults.
4. WHILE the signed-in Role is `owner`, WHEN a user submits the plan edit form, THE Frontend SHALL
   request `PATCH /api/membership-plans/{id}` with `name`, `price`, `currency`, `duration_days`,
   `includes_trainer`, and `includes_diet` as the only field names it may send.
5. THE Frontend SHALL constrain the `currency` input to a selection from exactly `INR`, `USD`,
   `EUR`, `GBP`, `AED`, `SGD`, `AUD`, `CAD`, and SHALL preselect `INR` on the plan creation form.
6. THE Frontend SHALL constrain the `duration_days` input to whole numbers from 1 to 3650
   inclusive, and SHALL present both bounds as visible text associated with that input.
7. THE Frontend SHALL present the `price` input as a text control accepting only values matching
   `^\d{1,10}(\.\d{1,2})?$`, giving a minimum of `0.00` and a maximum of `9999999999.99`, SHALL
   submit the entered characters as a string, and SHALL convert the value to no JavaScript
   `number` at any point, because `price` is a decimal of at most 12 digits with 2 decimal places
   and Requirement 9 forbids numeric conversion.
8. WHEN a plan creation or update request returns 400 with `details.field` equal to `name`, THE
   Frontend SHALL attach the `error.message` value to the name control, SHALL retain every entered
   value, and SHALL present no plan as created or updated, because plan names are unique per gym
   without regard to letter case.
9. THE Frontend SHALL present no plan deletion, archive, or deactivation control, because no route
   accepts DELETE and `MembershipPlanSerializer` exposes no status field.
10. THE Frontend SHALL present no `max_members_allowed` input and no seat-limit value on the
    membership plan surface, because that field belongs to `SaasPlan` and not to
    `MembershipPlan`.
11. THE Frontend SHALL present, on the membership plans surface, the visible note that a plan can
    be created and edited but that no member can be enrolled on it or billed for it through the
    API, because no route creates a Membership.
12. IF a value entered in the plan creation form or the plan edit form violates criterion 5,
    criterion 6, or criterion 7, or `name` is empty once leading and trailing whitespace is
    removed, THEN THE Frontend SHALL present a message on the offending control, SHALL issue no
    Backend request, and SHALL retain every entered value.
13. WHILE the signed-in Role is `owner`, WHEN a user opens the edit form for a plan, THE Frontend
    SHALL request `GET /api/membership-plans/{id}` with an identifier taken from a `GET
    /api/membership-plans` response the current session already received, and SHALL populate the
    `price` control with the response's decimal string unchanged.

### Requirement 16: Invoices and Payment Initiation

**User Story:** As an owner or member, I want to see what I owe and start a payment, so that I can
settle an invoice.

#### Acceptance Criteria

1. THE Frontend SHALL present the invoices surface to all three Roles and SHALL populate it from
   `GET /api/invoices` using only the `page` query parameter, sending no payer, gym, status, or
   date parameter, because the Backend scopes the collection to the caller — an `owner` receives
   the whole Gym's invoices and every other Role receives only invoices whose `payer_user` is
   that user — and honours no other query parameter.
2. THE Frontend SHALL present, for each invoice, the `number`, `financial_year`, `sequence_no`,
   `taxable_value`, `cgst`, `sgst`, `igst`, `hsn_sac`, `total_amount`, `currency`, `status`,
   `issue_date`, and `due_date` fields returned by `InvoiceSerializer`, SHALL render
   `taxable_value`, `cgst`, `sgst`, `igst`, and `total_amount` through the Money_Formatter from
   the unmodified Backend decimal string, and SHALL render `cgst`, `sgst`, `igst`, or `hsn_sac` as
   "Not applicable" when the Backend value is null.
3. THE Frontend SHALL label an invoice whose `saas_subscription` field is non-null as a
   subscription invoice, an invoice whose `membership` field is non-null as a membership invoice,
   and an invoice whose both fields are null with no subject label, and SHALL present neither
   identifier value and no further detail about either subject, because neither identifier is
   resolvable through any route.
4. THE Frontend SHALL render the `status` value as a text label for exactly the values `open`,
   `settled`, `void`, and `refunded`, SHALL render any other received value as its literal text
   with no status styling, and SHALL convey status through text rather than through colour alone.
5. THE Frontend SHALL present the invoice detail surface from `GET /api/invoices/{id}` using only
   an identifier taken from a `GET /api/invoices` response the current session already received,
   and SHALL present no control that accepts a typed invoice identifier.
6. WHILE the signed-in Role is `owner` or `member` AND the invoice `status` is `open`, THE
   Frontend SHALL present an enabled payment control that issues exactly one `POST
   /api/invoices/{id}/pay` request per activation and SHALL hold that control disabled from
   activation until that request resolves, so that one activation creates at most one gateway
   order.
7. WHILE the invoice `status` is any value other than `open`, THE Frontend SHALL present the
   payment control as disabled and SHALL present, as visible text adjacent to that control and in
   that control's accessible description, an explanation that only an invoice whose status is
   `open` can be paid.
8. WHILE the signed-in Role is `trainer`, THE Frontend SHALL omit the payment control from the
   rendered output and SHALL issue no `POST /api/invoices/{id}/pay` request, because
   `InvoicePayView` declares `allowed_roles = {"owner", "member"}`.
9. THE Frontend SHALL send, as the body of `POST /api/invoices/{id}/pay`, a JSON object
   containing zero keys, and SHALL include in no request body to any Backend route, at any
   nesting depth, a key naming a card number, an expiry value, a security code, or a cardholder
   name, because the Backend scans the body at every nesting depth and answers 400
   `CARD_DATA_REJECTED`.
10. THE Frontend SHALL collect no card number, no expiry value, no security code, and no
    cardholder name in any form control, and SHALL retain no such value in the Session_Store or
    the Query_Layer cache.
11. WHEN a payment request returns 201, THE Frontend SHALL present the `order_ref` value, the
    `currency` value, and the payable amount rendered from the invoice `total_amount` decimal
    string through the Money_Formatter, SHALL pass `key_id`, `order_ref`, and `amount_minor` to
    the Payment_Gateway's client-side checkout, and SHALL present `amount_minor` in no
    human-readable amount.
12. WHEN a payment request returns 201, THE Frontend SHALL present the visible note that the
    invoice `status` changes only when the Payment_Gateway notifies the Backend through its
    webhook, SHALL offer a control that reissues `GET /api/invoices/{id}` when activated, and
    SHALL issue no automatic or repeated `GET /api/invoices/{id}` request in the absence of a user
    activation.
13. THE Frontend SHALL present no receipt surface, SHALL issue no request to
    `/api/payments/{id}/receipt`, and SHALL present the `receipt` value of the pay-order response
    neither as a receipt document nor as a link, because `order_response` returns no Payment
    identifier and no route lists Payments, so the identifier that route requires is
    unobtainable.
14. WHILE the signed-in Role is `owner`, THE Frontend SHALL present, on the invoices surface, the
    visible note that requesting the invoice list may cause the Backend to issue the upcoming
    subscription invoice, because `InvoiceListView.list` calls `ensure_period_invoice`.
15. IF a payment request returns 201 with `order_ref` or `key_id` absent or empty, THEN THE
    Frontend SHALL present a message indicating that the payment could not be started, SHALL
    perform no Payment_Gateway checkout handoff, SHALL leave the displayed invoice `status`
    unchanged, and SHALL re-enable the payment control.
16. IF the Payment_Gateway client-side checkout fails to initialise or closes without completing
    after a handoff, THEN THE Frontend SHALL present a message indicating that no payment has been
    recorded, SHALL keep the `order_ref` value visible, and SHALL offer the control that reissues
    `GET /api/invoices/{id}`.

### Requirement 17: Gym Surface

**User Story:** As an owner, I want to maintain my gym's contact details and tax identifier, so
that invoices carry correct information.

#### Acceptance Criteria

1. THE Frontend SHALL present the gym surface to the `owner`, `trainer`, and `member` Roles and
   SHALL populate it from `GET /api/gym`.
2. THE Frontend SHALL present, each with a visible field label, exactly the `id`, `name`, `slug`,
   `contact_email`, `contact_phone`, `timezone`, `gstin`, and `is_active` fields returned by
   `GymSerializer`, and SHALL present no gym creation date and no field outside that set, because
   `created_at` is never serialised.
3. WHILE the signed-in Role is `owner`, THE Frontend SHALL update the gym through `PATCH
   /api/gym` with `name`, `contact_email`, `contact_phone`, `timezone`, and `gstin` as the only
   keys in the request body, and SHALL include no `id`, `slug`, or `is_active` key.
4. THE Frontend SHALL present `id`, `slug`, and `is_active` as read-only values with no editable
   control for any Role.
5. THE Frontend SHALL present, adjacent to the `slug` value and without requiring a hover or a
   click to reveal it, a visible explanation stating that `slug` cannot change because it forms
   part of every issued invoice number.
6. THE Frontend SHALL validate `name` as at least 1 character after trimming leading and trailing
   whitespace, `contact_email` as an email address or an empty value, `contact_phone` as a
   non-empty value of at most 16 characters matching the pattern `^\+[1-9]\d{7,14}$`, `gstin` as
   either an empty value or exactly 15 characters matching the pattern
   `^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$`, and `timezone` as one of the
   offered selections, before issuing `PATCH /api/gym`.
7. THE Frontend SHALL constrain the `timezone` input to a single selection from the IANA timezone
   names the browser runtime reports, SHALL initialise that selection to the `timezone` value
   from the most recent `GET /api/gym` response, SHALL include that value among the offered
   selections even when the browser runtime does not report it, and SHALL accept no free-text
   timezone entry.
8. THE Frontend SHALL present, adjacent to the `gstin` input and without requiring a hover or a
   click to reveal it, a visible explanation stating that setting a GSTIN causes the Backend to
   compute GST on every invoice issued after the change, that clearing a GSTIN leaves `cgst`,
   `sgst`, `igst`, and `hsn_sac` null meaning tax not applicable, that null is distinct from the
   value `"0.00"`, and that invoices already issued are not recomputed by either change.
9. THE Frontend SHALL present no subscription plan, seat limit, or seat usage figure on the gym
   surface, because no route reports which SaasPlan the gym holds.
10. THE Frontend SHALL present, adjacent to the `timezone` input and without requiring a hover or
    a click to reveal it, a visible explanation stating that the Backend evaluates every
    membership and billing date in the gym's timezone, that changing this value can change the
    `is_active`, `current_period_end`, `is_active_member`, and `subscription_status` values the
    Backend reports with no other action taken, and that the Frontend neither recomputes nor
    overrides those values.
11. WHILE the signed-in Role is `owner`, WHEN the owner submits the gym form with a `gstin` value
    or a `timezone` value that differs from the corresponding value in the most recent `GET
    /api/gym` response, THE Frontend SHALL present a confirmation dialog naming each changed
    field with its outgoing value, its incoming value, and the consequence stated in criterion 8
    for `gstin` and in criterion 10 for `timezone`, SHALL issue `PATCH /api/gym` only after the
    owner activates that dialog's confirm control, and SHALL retain every entered value when that
    dialog is dismissed without confirmation.
12. IF `PATCH /api/gym` returns 400 with code `VALIDATION_ERROR`, THEN THE Frontend SHALL attach
    the `error.message` value to the control whose name equals `details.field`, including the
    case where `details.field` is `contact_phone` because phone numbers are unique across the
    platform and the case where `details.field` is `timezone` because the browser runtime may
    offer a name the Backend does not accept, SHALL retain every entered value, and SHALL issue
    no further request until the owner resubmits.

### Requirement 18: Profile Surface

**User Story:** As any signed-in user, I want to correct my own name and phone number, so that my
details are right.

#### Acceptance Criteria

1. THE Frontend SHALL present the profile surface to the `owner`, `trainer`, and `member` Roles,
   and SHALL populate it from one `GET /api/me` request per entry to that surface.
2. THE Frontend SHALL present the `id`, `email`, `first_name`, `last_name`, `phone`, `role`,
   `email_verified`, `gym`, `subscription_status`, `is_active_member`, and `current_period_end`
   fields returned by `MeSerializer`, SHALL present the `gym` value as its `name` field, SHALL
   present the text "Not provided" for a `first_name`, `last_name`, or `phone` value that is null
   or an empty string, and SHALL present `subscription_status`, `is_active_member`, and
   `current_period_end` as Requirement 10 specifies.
3. WHEN a user submits the profile form, THE Frontend SHALL issue exactly one `PATCH /api/me`
   request whose body contains only `first_name`, `last_name`, and `phone`, and SHALL send an
   empty string for each of those three inputs the user cleared.
4. THE Frontend SHALL render `id`, `email`, `role`, `email_verified`, `gym`,
   `subscription_status`, `is_active_member`, and `current_period_end` as read-only values with no
   editing control and no submit path, because `MeUpdateSerializer` accepts only `first_name`,
   `last_name`, and `phone`.
5. IF a user submits the profile form while the `phone` input holds a non-empty value that
   exceeds 16 characters or does not match the pattern `^\+[1-9]\d{7,14}$`, THEN THE Frontend
   SHALL present a message at the `phone` control stating that the number must be in
   international format beginning with a plus sign, SHALL retain every entered value, and SHALL
   issue no `PATCH /api/me` request.
6. WHEN a `PATCH /api/me` response carries status 400 with code `VALIDATION_ERROR` AND
   `details.field` equal to `phone`, THE Frontend SHALL attach the `error.message` value to the
   phone control, SHALL retain every entered value, and SHALL leave the cached `/api/me` payload
   unchanged, because phone numbers are unique across the platform.
7. WHEN a `PATCH /api/me` response carries status 200, THE Frontend SHALL replace the `/api/me`
   payload held by the Session_Store and the corresponding Query_Layer cache entry with the
   response body, and SHALL re-derive the Nav_Model rendering and every Route_Guard decision from
   the replaced payload.
8. THE Frontend SHALL present a password change control that navigates to the password reset
   request surface, and SHALL present adjacent to that control the visible explanation that no
   authenticated password change exists, that the Backend emails a reset code, and that
   completing the reset ends every existing session and requires signing in again.
9. THE Frontend SHALL treat the `id` field of `GET /api/me` as a `User` identifier for display
   only, and SHALL include that value in no request path, query string, or body, because
   `MeSerializer.id` is not a `MemberProfile` identifier and no detail route accepts a `User`
   identifier.
10. THE Frontend SHALL treat `member_profile_id` as the only field of a `GET /api/me` response
    permitted to appear in a request path, SHALL use that value only as the `{id}` segment of `GET
    /api/members/{id}`, and SHALL include it in no other path, no query string, and no request
    body.
11. WHILE `email_verified` from `GET /api/me` is false, THE Frontend SHALL present an unverified
    text label, SHALL present a link to the email-verification surface where a code can be
    entered, and SHALL present the explanation that the verification code was emailed at
    registration and cannot be resent, because no resend route exists.
12. IF a `PATCH /api/me` response carries status 403, THEN THE Frontend SHALL present the
    `error.message` value at form level, SHALL retain every entered value, SHALL leave the cached
    `/api/me` payload unchanged, and SHALL issue no retry.

### Requirement 19: Overview Surfaces

**User Story:** As a signed-in user, I want a first screen that tells me the real state of my
account, so that I can act without hunting.

#### Acceptance Criteria

1. THE Frontend SHALL present, on each Role's Overview surface, only values that are either a
   scalar field of the `GET /api/me` response body or the `count` field of a first-page paginated
   collection response that Role is admitted to read, and SHALL present no value produced by
   summing, differencing, averaging, or otherwise combining two or more such values, because no
   Backend route supplies an aggregate.
2. WHILE the signed-in Role is `owner`, THE Frontend SHALL present exactly five Overview metrics,
   each with a visible text label: the `count` from `GET /api/members`, the `count` from `GET
   /api/trainers`, the `count` from `GET /api/membership-plans`, the `count` from `GET
   /api/invoices`, and the `subscription_status` value from `GET /api/me`.
3. WHILE the signed-in Role is `trainer`, THE Frontend SHALL present exactly two Overview
   metrics: the `count` from `GET /api/members` labelled as the number of members assigned to the
   signed-in trainer, and the `count` from `GET /api/membership-plans`; and SHALL present no
   gym-wide member total, because `TrainerScope` restricts the member collection to members whose
   `trainer` foreign key is the signed-in trainer.
4. WHILE the signed-in Role is `member`, THE Frontend SHALL present the `is_active_member`,
   `current_period_end`, and `email_verified` values from `GET /api/me` and the `count` from `GET
   /api/invoices` labelled as invoices payable by the signed-in member, because
   `PayerScopedInvoiceQuerysetMixin` restricts a non-owner's invoice collection to invoices whose
   `payer_user` is that user.
5. THE Frontend SHALL present, on every Overview surface, no revenue total, no outstanding
   balance total, no paid-versus-unpaid split, no attendance figure, no growth percentage, no
   period-over-period comparison, no trend arrow, and no sparkline, because no Backend route
   supplies an aggregate or a time series.
6. WHERE an Overview metric derives from a collection `count`, THE Frontend SHALL request that
   collection with `page` set to 1, SHALL take the metric value from the `count` field of that
   single response, SHALL issue no request for page 2 or any later page, SHALL issue at most one
   automatic request per collection per Overview surface mount, and SHALL issue no further request
   for that collection in response to a timer, a window focus change, or a viewport visibility
   change.
7. THE Frontend SHALL present no seat limit, no seat capacity, and no seat utilisation figure on
   any Overview surface, because no Backend route reports which SaasPlan the Gym holds.
8. WHILE the signed-in Role is `owner`, THE Frontend SHALL present, adjacent to the invoice count
   metric, the visible note that loading this surface reads the invoice list and may cause the
   Backend to issue the upcoming subscription invoice, because `InvoiceListView.list` calls
   `ensure_period_invoice`.
9. IF a request for an Overview count returns a non-2xx status or fails without a response, THEN
   THE Frontend SHALL present the mapped message from Requirement 11 in place of that metric's
   value, SHALL render no numeral and no zero for that metric, SHALL present a retry control that
   reissues only that collection's page-1 request, and SHALL continue to present every other
   Overview metric that resolved.
10. THE Frontend SHALL present an Overview metric whose `count` is zero as the numeral 0 with its
    text label, and SHALL present a null `GET /api/me` scalar as described in Requirement 10
    criteria 5 and 6 rather than as a numeral or a blank value, so that an unavailable metric and
    a genuinely empty collection are distinguishable on screen.

### Requirement 20: Prohibition of Dead Interface Elements

**User Story:** As a user, I want every control to do something or tell me why it cannot, so that
the interface never lies to me.

#### Acceptance Criteria

1. THE Frontend SHALL render each interactive element — every rendered element that is focusable
   or that carries an ARIA role of `button`, `link`, `tab`, `menuitem`, `checkbox`, `radio`,
   `switch`, `combobox`, or `textbox` — so that at least one of the following four behaviours is
   observable, and SHALL render no interactive element for which none of the four is observable:
   it issues a request to a method-and-path pair enumerated in Backend Audit Findings section A,
   it changes the Frontend route to a route the Route_Guard admits for the signed-in Role, it
   changes local view state observable in the rendered output within 1000 milliseconds of
   activation without issuing a Backend request, or it renders in the disabled state defined by
   criteria 2, 3, and 9.
2. WHILE an interactive element renders in a disabled state, THE Frontend SHALL present a
   non-empty explanation of at most 200 characters within the same container element as that
   element, visible without hover, focus, or activation, stating both the condition that refuses
   the action and the state change that would make the element operable, except for an element
   disabled solely while a write request it submits is in flight, for which the pending indication
   required by Requirement 12 criterion 6 SHALL serve as that explanation.
3. WHILE an interactive element renders in a disabled state, THE Frontend SHALL render that
   element with `aria-disabled="true"`, SHALL keep it focusable in document order, and SHALL
   associate the explanation required by criterion 2 with that element through an
   `aria-describedby` attribute naming the element that carries the explanation.
4. WHEN a user activates a control whose only observable behaviour is to reveal further controls,
   THE Frontend SHALL reveal, within at most two such activations, at least one control that
   issues a Backend request or changes the Frontend route.
5. THE Frontend SHALL render no tab, no menu item, and no navigational link whose panel content
   or destination requires a method-and-path pair absent from Backend Audit Findings section A.
6. THE Frontend SHALL register no route path that resolves to a surface presenting neither at
   least one value obtained from a Backend response listed in Backend Audit Findings section A
   nor at least one explanation of unavailability required by another requirement of this
   document, so that no placeholder route, no "coming soon" surface, and no under-construction
   state exists.
7. WHILE the signed-in Role is absent from the admitted-role set of the route a control would
   invoke, as recorded in Backend Audit Findings section A, THE Frontend SHALL omit that control
   from the rendered output and SHALL render in its place no disabled element, no explanation, and
   no tooltip, consistent with Requirement 6 criterion 3.
8. WHILE the signed-in Role is present in the admitted-role set of the route a control would
   invoke AND a Backend gate or the current state of the record refuses that action, as required
   by Requirement 6 criterion 8, Requirement 6 criterion 10, or Requirement 16 criterion 7, THE
   Frontend SHALL render that control in the disabled state defined by criteria 2, 3, and 9 rather
   than omitting it.
9. IF a user activates an interactive element rendered in a disabled state, THEN THE Frontend
   SHALL issue no Backend request, SHALL change no Frontend route, and SHALL change no view state
   other than moving focus to that element.

### Requirement 21: Accessibility

**User Story:** As a keyboard and screen reader user, I want to operate every part of the
interface, so that I can do my job without a mouse.

#### Acceptance Criteria

1. THE Frontend SHALL render navigation within a `nav` element carrying an accessible name, page
   content within exactly one `main` element per page, and each Data_List within a `table` element
   that carries a `caption` naming the collection and a `th` cell with `scope="col"` for every
   column header.
2. THE Frontend SHALL make every interactive control reachable by Tab and Shift+Tab in the order
   the control appears in the document and operable by the Enter key for links and by the Enter or
   Space key for buttons, SHALL declare no `tabindex` value greater than 0, SHALL create no focus
   sequence outside an open dialog from which Tab and Shift+Tab cannot move focus onward, and SHALL
   keep every control rendered in the disabled state under Requirement 20 reachable by Tab, marked
   `aria-disabled="true"`, carrying the `aria-describedby` association Requirement 20 criterion 3
   requires, and taking no action when activated.
3. THE Frontend SHALL render the focus indicator defined by Requirement 3 on every focusable
   control that receives keyboard focus, SHALL keep that indicator at a contrast ratio of at least
   3 to 1 against the surface adjacent to it, and SHALL leave no focusable control without a
   visible focus indicator.
4. THE Frontend SHALL render body text, navigation text, metadata text, and form control text at a
   contrast ratio of at least 4.5 to 1, and text at 24px or larger at a contrast ratio of at least
   3 to 1, measured against the Token_Layer surface colour painted immediately behind that text,
   which is Paper White `#ffffff`, Mist Gray `#f2f2f3`, Fog White `#fafafb`, or, on the single
   accent card Requirement 3 criterion 18 permits, Blush Peach `#fbe1d1` behind Sienna Brown
   `#5d2a1a` text.
5. WHEN a dialog opens, THE Frontend SHALL move focus to the first focusable element inside that
   dialog, or to the dialog container when the dialog contains none, SHALL confine Tab and
   Shift+Tab traversal to that dialog, SHALL make every control outside that dialog unreachable by
   Tab and Shift+Tab while it is open, SHALL close that dialog on the Escape key without submitting
   its form, and SHALL return focus to the control that opened it, or to the `main` element when
   that control is no longer present in the document.
6. THE Frontend SHALL render each dialog with `role="dialog"`, `aria-modal="true"`, and an
   accessible name supplied by an `aria-labelledby` reference to that dialog's visible heading.
7. THE Frontend SHALL implement each tab set with `role="tablist"`, `role="tab"`, and
   `role="tabpanel"`, SHALL give each tab an `aria-controls` reference to its panel and each panel
   an `aria-labelledby` reference to its tab, SHALL carry `tabindex="0"` and `aria-selected="true"`
   on exactly one tab and `tabindex="-1"` and `aria-selected="false"` on every other tab, and SHALL
   move focus and selection to the previous or next tab on the Left and Right arrow keys, wrapping
   from the last tab to the first and from the first tab to the last.
8. THE Frontend SHALL associate every form control with a visible `label` element whose `for`
   attribute equals that control's `id`, SHALL use placeholder text as no control's only label, and
   SHALL mark every control the Backend requires with `aria-required="true"` and a visible textual
   indication that it is required.
9. WHEN a form submission fails Frontend validation or returns a Backend `VALIDATION_ERROR` mapped
   under Requirement 11 criteria 5 and 6, THE Frontend SHALL set `aria-invalid="true"` on each
   offending control, associate that control's message through `aria-describedby`, render that
   message as text rather than as colour or an icon alone, move focus to the first offending
   control in document order, and retain every value the user entered.
10. WHEN a toast appears, THE Frontend SHALL announce it through the App_Shell ARIA live region
    that is present in the document before the toast is inserted, using a polite announcement for a
    confirmation and an assertive announcement for a failure, SHALL keep it visible for at least 5
    seconds, SHALL keep a failure toast visible until a user dismisses it, and SHALL provide a
    keyboard-operable dismiss control on every toast.
11. THE Frontend SHALL give every icon-only control an accessible name stating the action that
    control performs, and SHALL mark every decorative icon `aria-hidden="true"` so it contributes
    no text to the accessible name of its container.
12. THE Frontend SHALL render, as the first focusable element in document order on every page, a
    skip link that is visible while it holds focus and moves focus to the `main` element when
    activated.
13. THE Frontend SHALL pair every status value it renders, including invoice `status`, member
    `is_active`, `subscription_status`, `email_verified`, and trainer `status`, with a text label in
    the same container as the colour that carries it, and SHALL convey no state through colour,
    position, or shape alone.
14. IF a pairing of Slate Gray `#777b86`, Ash Gray `#979799`, or Smoke Gray `#a3a6af` with Paper
    White `#ffffff`, Mist Gray `#f2f2f3`, or Fog White `#fafafb` measures below 4.5 to 1, THEN THE
    Frontend SHALL use that pairing for no body text, navigation text, metadata text, or form
    control text, and SHALL restrict that colour on that surface to non-text use or to text at 24px
    or larger that measures at least 3 to 1 against it.
15. WHILE the viewport width is below 768px, THE Frontend SHALL render each Data_List as the
    stacked list of records Requirement 23 criterion 4 requires in place of the `table` element
    criterion 1 requires, rendering each record as one list item within a list element, giving that
    list the accessible name criterion 1 requires of the `caption`, associating each field value
    with its visible field label programmatically, and producing no horizontally scrolling `table`.
16. THE Build_Pipeline SHALL run an automated accessibility check over every surface listed in
    Requirement 12 criterion 4 that reports zero violations of criteria 1, 3, 4, 6, 7, 8, 11, 12,
    14, and 15, and THE Limitations_Document SHALL record that criteria 2, 5, 9, 10, and 13 are
    verified by scripted interaction tests instead, and that neither check establishes full WCAG
    conformance, which requires manual assistive-technology testing and expert accessibility
    review.

### Requirement 22: Data Visualisation

**User Story:** As an owner, I want any chart on screen to be built from complete real data, so
that I never make a decision from a partial picture.

#### Acceptance Criteria

1. THE Frontend SHALL render the chart only from an invoice collection whose every page has been
   fetched as described in Requirement 8 criterion 8, SHALL request that page sequence at most
   once per visit to the invoices surface, and SHALL perform no automatic refetch of that
   sequence on window focus, on reconnect, or on a timed interval, because
   `InvoiceListView.list` calls `ensure_period_invoice` on every request.
2. WHILE any page of the chart's invoice collection remains unfetched, THE Frontend SHALL present
   the loading state from Requirement 12 criterion 1, SHALL present the number of invoices
   fetched so far together with an indication that further pages remain outstanding, and SHALL
   render no chart, no axis, and no partial series.
3. WHILE the signed-in Role is `owner`, THE Frontend SHALL render at most one chart on the
   invoices surface, plotting each fetched invoice's `total_amount` against its `issue_date` as
   one series per `status` value from exactly the set `open`, `settled`, `void`, and `refunded`.
4. THE Frontend SHALL present the chart's underlying figures in a `table` element adjacent to the
   chart carrying a `caption`, with one row per plotted invoice in the order the Backend
   responses supplied and columns for `number`, `issue_date`, `status`, `currency`, and
   `total_amount`, so that the data is available without reading the graphic.
5. THE Frontend SHALL produce every money figure rendered inside the chart card, including every
   axis tick label, every data label, every tooltip value, and every `total_amount` table cell,
   from the Money_Formatter output for the unmodified Backend decimal string.
6. IF the invoice collection `count` is zero, THEN THE Frontend SHALL present the empty state from
   Requirement 12 criterion 2 and SHALL render no chart and no adjacent table.
7. IF any page request in the chart's page sequence returns a non-2xx status or fails without a
   response, THEN THE Frontend SHALL discard every page already fetched for that sequence, SHALL
   render no chart and no adjacent table, and SHALL present the error state from Requirement 12
   criterion 3 with a retry control that restarts the sequence at page 1.
8. WHERE the chart described in criterion 3 is built, THE Frontend SHALL convert each invoice
   `total_amount` decimal string to a JavaScript number solely inside a single chart geometry
   module, and SHALL pass each converted number only to the charting library's plotting
   coordinate inputs for the invoice that supplied it.
9. THE Frontend SHALL render no converted number as text in any element, and SHALL derive no
   total, subtotal, average, difference, or percentage from a converted number, so that
   Requirement 9 criteria 1 and 2 hold for every figure a user reads.
10. THE Frontend SHALL render no chart of members, trainers, membership plans, attendance,
    workouts, body metrics, seat usage, or revenue growth, no second chart of any subject, and no
    chart on any Overview surface or for any Role other than `owner`, because no Backend route
    supplies an aggregate or a time series (Backend Audit Findings gap G6).
11. THE Frontend SHALL render the chart as a floating product artifact on an Elevated White surface
    as Requirement 3 criteria 14, 15, and 33 require, with its series reveal governed by
    Requirement 24 criteria 4 and 9.
12. THE Frontend SHALL draw the `open` series stroke in Sienna Brown and the `settled`, `void`,
    and `refunded` series strokes in Ink Black, Slate Gray, and Smoke Gray respectively, each
    referenced through a Token_Layer custom property, and SHALL label each series with its
    `status` text in a legend so that no series is distinguished by colour alone.

### Requirement 23: Responsive Layout

**User Story:** As a user on a phone, I want the whole interface usable in one column, so that I
can work away from a desk.

#### Acceptance Criteria

1. WHILE the viewport width is 1024px or greater, THE Frontend SHALL present multi-column page
   layouts of at most three columns inside a content region capped at the 1200px maximum content
   width stated in Requirement 3, centred horizontally within the viewport, with 24px of
   horizontal padding on each side of that region, a 24px gutter between adjacent columns, and no
   column narrower than 280px.
2. WHILE the viewport width is from 768px to 1023px inclusive, THE Frontend SHALL reduce each
   multi-column layout to at most two columns of no less than 280px each, in the source order of
   the wider layout, with 24px of horizontal page padding on each side and a 24px gutter between
   the two columns.
3. WHILE the viewport width is below 768px, THE Frontend SHALL present every page layout as a
   single column in the source order of the wider layout, with 16px of horizontal page padding on
   each side, and SHALL apply the below-768px section spacing value and the below-768px display
   type size stated in Requirement 3.
4. WHILE the viewport width is below 768px, THE Frontend SHALL present each Backend collection as
   a vertically stacked list of one group per record, SHALL render each field's visible label
   beside that field's value within its group, SHALL present every field that collection presents
   at 768px or greater, and SHALL present no horizontally scrolling table.
5. THE Frontend SHALL produce no horizontal document scrollbar at any viewport width from 320px to
   2560px, whether that width is present at first render or reached by resizing across the 768px
   or 1024px threshold without a document reload, including while a dialog, a navigation panel, a
   dropdown, or a toast is open, and SHALL clip, truncate, or abbreviate no Backend value in order
   to satisfy this.
6. WHILE the viewport width is below 768px, THE Frontend SHALL render every interactive control
   with a touch target of at least 44 by 44 CSS pixels, matching the minimum control dimension
   stated in Requirement 3, including icon-only controls, pagination controls, links inside a
   stacked record group, and the navigation disclosure control, and SHALL separate adjacent touch
   targets by at least 8px.
7. WHILE the viewport width is below 768px, THE Frontend SHALL present navigation solely as the
   single disclosure control and full-height panel specified in Requirement 4 criterion 7, and
   SHALL render that panel no wider than the viewport width less 16px on each side.
8. WHILE the viewport width is below 768px, THE Frontend SHALL preserve the accessible structure
   Requirement 21 criterion 1 requires for a collection by presenting that collection's caption
   text as the accessible name of the stacked list and by programmatically associating each
   rendered field value with its visible field label, so that the record structure remains
   determinable without a table presentation.
9. IF a rendered value contains no space character and its rendered width exceeds the horizontal
   space available in its container (including an invoice `number`, an `email`, a `gstin`, a
   `timezone` name, a `photo_url`, and the Gym `name` presented in the top navigation region),
   THEN THE Frontend SHALL wrap that value onto additional lines inside that container, and SHALL
   neither widen that container beyond the space available to it nor clip, truncate, or abbreviate
   the value.
10. THE Frontend SHALL render each money value, each date value, each timestamp value, and each
    numeric count on a single line with no internal line break at every viewport width from 320px
    to 2560px, so that no wrapping can misstate a figure the Backend supplied.

### Requirement 24: Motion

**User Story:** As a user, I want the interface to feel calm and considered, so that motion helps
rather than distracts.

#### Acceptance Criteria

1. WHEN a route becomes active, THE Motion_Layer SHALL animate that route's page content from
   opacity 0 and a vertical offset of 8 pixels below its final position to opacity 1 and its
   final position over 240 milliseconds, SHALL animate that content as one element rather than
   animating its descendants individually except for the card group stagger stated in criterion
   2, and SHALL run this animation once per route activation.
2. WHEN a group of two or more cards enters a surface, THE Motion_Layer SHALL delay the first
   card's entrance by 0 milliseconds and each following card's entrance by a further 40
   milliseconds, SHALL delay the eighth card and every card after it by 280 milliseconds, SHALL
   apply to each card the same opacity and 8-pixel offset animation over 240 milliseconds stated
   in criterion 1, and SHALL complete every card entrance on that surface within 520 milliseconds
   of the first card's entrance beginning.
3. WHEN a whole-number metric taken from the `count` field of a Backend paginated response or
   from an integer scalar field of a Backend response body first renders after mount, THE
   Motion_Layer SHALL animate the displayed digits from 0 to that whole number over 800
   milliseconds, SHALL display exactly the Backend value when the animation completes, SHALL
   render that metric's label at full opacity from first paint, and SHALL run the count-up once
   per mount and not on a refetch that returns the same value.
4. WHEN a chart first renders after mount, THE Motion_Layer SHALL reveal its series from opacity
   0 to opacity 1 over 600 milliseconds, SHALL render the chart's axis labels and the adjacent
   `table` element required by Requirement 22 criterion 4 at full opacity from first paint, and
   SHALL run the reveal once per mount.
5. WHEN the active tab changes, THE Motion_Layer SHALL translate the tab indicator from the
   previously active tab's position to the newly active tab's position over 200 milliseconds,
   SHALL present the newly active tabpanel's content at full opacity from the first frame of that
   translation, and SHALL animate no other element of that tab set.
6. WHEN a dialog opens, THE Motion_Layer SHALL animate it from opacity 0 and scale 0.98 to
   opacity 1 and scale 1.0 over 180 milliseconds.
7. WHEN a dropdown or menu opens, THE Motion_Layer SHALL animate it from opacity 0 and a vertical
   offset of 4 pixels from its final position to opacity 1 and its final position over 140
   milliseconds.
8. WHEN a toast appears, THE Motion_Layer SHALL animate it from opacity 0 and an offset of 8
   pixels from its final position to opacity 1 and its final position over 200 milliseconds.
9. WHILE the `prefers-reduced-motion` media query reports `reduce`, THE Motion_Layer SHALL apply
   no translation, no scaling, and no count-up, SHALL set every transition duration and every
   animation duration to 0 milliseconds, and SHALL render each element at the same final
   position, the same final opacity, the same final scale, and the same final displayed value
   that element reaches when the corresponding animation completes while the media query reports
   `no-preference`.
10. THE Motion_Layer SHALL animate only opacity, two-dimensional translation, and uniform scale,
    SHALL animate no element continuously, including every loading skeleton required by
    Requirement 12 criterion 1, and SHALL restrict every animation it declares to a single
    iteration, a duration of no more than 800 milliseconds, an exit duration no greater than that
    element's entrance duration, and an easing curve that renders no intermediate value outside
    the range between that animation's start value and its end value.
11. THE Motion_Layer SHALL apply no count-up and no interpolated intermediate value to `price`,
    `taxable_value`, `cgst`, `sgst`, `igst`, `total_amount`, `amount`, `amount_minor`, any other
    Backend decimal string, any Backend date or timestamp, or any Derived_State value, and SHALL
    render each of those values exactly as the Backend supplied it from first paint.
12. THE Motion_Layer SHALL mount every animated element in the DOM and in the accessibility tree
    before that element's animation begins, SHALL leave every animated control operable by
    pointer and by keyboard for the whole of that animation, and SHALL gate no Backend request,
    no focus move or focus return required by Requirement 21, and no ARIA live-region
    announcement required by Requirement 21 criterion 10 on an animation completing.
13. WHEN the `prefers-reduced-motion` media query value changes during a session, THE
    Motion_Layer SHALL apply the changed value to every animation started after that change
    without requiring a page reload.

### Requirement 25: Backend Immutability and Gap Handling

**User Story:** As the backend maintainer, I want the frontend built against the API as it
stands, so that a UI convenience never weakens a verified backend invariant.

#### Acceptance Criteria

1. THE Frontend SHALL leave every version-controlled file under `core/` — including
   `core/tests/`, `core/services/`, `core/views/`, and `core/management/` — every
   version-controlled file under `gymapp/`, and every version-controlled file under `tools/`
   byte-for-byte identical to its content at the start of this specification's implementation,
   with `core/serializers.py` as the single exception permitted by criterion 2.
2. THE Frontend SHALL confine every Backend modification to `core/serializers.py`, SHALL confine
   every modification within that file to the addition of one `member_profile_id` field to
   `MeSerializer` returning the caller's `MemberProfile` primary key for the `member` role and null
   for the `owner` and `trainer` roles, and SHALL add, remove, rename, and alter no other field, no
   other serializer, and no other statement in that file.
3. THE Frontend SHALL leave `requirements.txt`, `pytest.ini`, `manage.py`, and `.env.example`
   byte-for-byte identical to their content at the start of this specification's implementation,
   and SHALL leave every version-controlled file under `core/` other than `core/serializers.py`,
   every version-controlled file under `gymapp/`, and every version-controlled file under `tools/`
   byte-for-byte identical, so that the addition permitted by criterion 2 is the only Backend diff
   in the delivered work.
4. WHERE a Frontend requirement cannot be met through the routes enumerated in Backend Audit
   Findings section A, THE Limitations_Document SHALL record one entry naming the blocked
   requirement number and criterion number, the specific missing Backend capability, the section
   K gap identifier where one applies, and the Frontend behaviour delivered instead.
5. THE Frontend SHALL resolve each of the twelve gaps `G1` through `G12` in Backend Audit Findings
   section K either by a Frontend-side accommodation or, where criterion 6 applies, by omitting the
   affected surface, SHALL make no Backend change for any of those twelve, and THE
   Limitations_Document SHALL record for each of those twelve exactly one disposition value of
   `accommodated` or `surface omitted`.
6. WHERE no Frontend accommodation exists for a gap, THE Frontend SHALL present no route, no
   navigation destination, no page, no tab, no control, and no placeholder surface for the
   affected capability, SHALL issue no request that the missing capability would require, and THE
   Limitations_Document SHALL record the omitted surface together with the gap identifier that
   caused the omission.
7. IF a Frontend requirement appears to require a Backend change other than the addition permitted
   by criterion 2, THEN THE Frontend SHALL modify no path named in criteria 1 and 3, SHALL record a
   Backend-change proposal in the Limitations_Document, SHALL request explicit written approval from
   the requester, and SHALL treat any approval state other than `approved in writing` as a refusal
   of that change.
8. THE Limitations_Document SHALL record each Backend-change proposal with the blocked
   requirement number and criterion number, the smallest sufficient change stated as the specific
   Backend module and behaviour it would alter, every build-time conformance guard and property
   test the change would affect drawn from the set `check_api_surface.py`,
   `check_tenant_scoping.py`, and properties 01, 02, 03, 17, 18, 35, and 38, and an approval
   state of exactly one of `pending approval`, `approved in writing`, or `declined`.
9. IF a candidate Backend change would alter `core/management/commands/check_api_surface.py`,
   `core/management/commands/check_tenant_scoping.py`, or any behaviour asserted by property 01,
   02, 03, 17, 18, 35, or 38, THEN THE Frontend SHALL classify that change as not minimal, SHALL
   record the invariant it would weaken alongside the proposal, and SHALL not present that change
   as a small or safe change.
10. THE Limitations_Document SHALL record the proposal that adds `member_profile_id` to
    `MeSerializer` in approval state exactly `approved in writing`, and THE Frontend SHALL deliver
    the resolved `G13` behaviour required by Requirement 13 criteria 13 through 16.
11. WHEN the `member_profile_id` addition permitted by criterion 2 has been applied, THE Frontend
    SHALL run the complete Backend test suite through the project's configured runner, SHALL record
    the invoking command, the resolved test count, and the pass or fail outcome in the
    Limitations_Document, and SHALL treat a passing full suite as a precondition of presenting the
    change as complete.
12. IF any Backend test that passed before the `member_profile_id` addition fails after it, THEN
    THE Frontend SHALL revert `core/serializers.py` to its pre-change content, SHALL amend no test
    file, no assertion, and no fixture to accommodate the change, and SHALL record the failing test
    identifier and the reversion in the Limitations_Document.

### Requirement 26: Quality Gates

**User Story:** As a developer, I want the deliverable to pass its own checks, so that shipping
is a decision and not a gamble.

#### Acceptance Criteria

1. THE Build_Pipeline SHALL declare Node 24.16.0 and npm 11.13.0 as the verified engine versions
   for every script it provides, and SHALL provide a type-check script that starts no file
   watcher and exits with status 0 only when the TypeScript compiler reports zero errors, and
   with a non-zero status otherwise.
2. THE Build_Pipeline SHALL provide a lint script that starts no file watcher and exits with
   status 0 only when the linter reports zero errors and zero warnings, and with a non-zero
   status otherwise.
3. THE Build_Pipeline SHALL provide a test script that executes every test file exactly once in a
   single pass, starts no file watcher, issues no interactive prompt, terminates without further
   input, and exits with status 0 only when every test passes.
4. THE Build_Pipeline SHALL provide a production build script that exits with status 0 only when
   the bundle is emitted with zero errors, and that emits a separately loaded chunk for each
   top-level route required by Requirement 2 criterion 8.
5. THE Frontend SHALL include unit tests for the Error_Mapper asserting that each of the
   twenty-two Backend error codes in Backend Audit Findings section G returns a non-empty
   user-facing message of at most 200 characters containing no stack trace, no HTTP method, and
   no request URL; that a response body outside the Error_Envelope shape returns the
   unexpected-failure message; that a request completing with no response returns the
   unreachable-server message; and that the mapper defines no code outside those twenty-two.
6. THE Frontend SHALL include unit tests for the Money_Formatter asserting that for the Backend
   decimal strings `"0.00"`, `"0.01"`, `"1500.00"`, and the twelve-digit maximum
   `"9999999999.99"` the output preserves every input digit and the input decimal position, that
   no JavaScript `number` is produced at any step, that a null `cgst`, `sgst`, `igst`, or
   `hsn_sac` renders as "Not applicable", and that the rendered currency equals the `currency`
   value supplied in the same response object.
7. THE Frontend SHALL include unit tests for the Nav_Model asserting that the `owner` destination
   set equals the seven destinations of Requirement 4 criterion 3, the `trainer` set equals the
   five destinations of criterion 4, and the `member` set equals the six destinations of criterion
   5, and that for every destination in each set that Role appears in the admitted-role set
   recorded in Backend Audit Findings section A for the route that destination reads.
8. THE Frontend SHALL include a test that enumerates every request the API_Client can construct
   and asserts that each method-and-path pair appears among the twenty-six role-reachable pairs of
   Backend Audit Findings section A, that no enumerated request uses the DELETE method, that no
   enumerated request carries a query parameter other than `page` so that no search, filter,
   ordering, or `page_size` parameter is constructible, and that no enumerated request body
   carries a card-data key at any nesting depth, the invoice payment body being an empty JSON
   object.
9. THE Frontend SHALL include a test that scans every TypeScript and TSX source file shipped in
   the production bundle, asserts zero occurrences of a hexadecimal colour literal, and names each
   offending file when the assertion fails.
10. THE Frontend SHALL include tests for the token-refresh sequence asserting that one request
    receiving 401 `TOKEN_EXPIRED` triggers exactly one `POST /api/auth/refresh`, replaces both
    stored tokens with the rotated pair, and retries the original request exactly once; that a
    refresh returning a non-2xx status clears the Session_Store, navigates to the sign-in route,
    and issues no second refresh; and that five concurrent requests each receiving 401
    `TOKEN_EXPIRED` trigger exactly one `POST /api/auth/refresh` and exactly one retry of each of
    the five requests.
11. THE Frontend SHALL include a test that, with `prefers-reduced-motion` reporting `reduce`,
    asserts that every transition and animation duration resolves to 0 milliseconds, that no
    rendered element carries a transform, and that every numeric metric renders its final value
    with no count-up.
12. THE Frontend SHALL include a test that renders every top-level route under each of the three
    Roles and asserts that every rendered button, tab, link, form control, and menu item either
    issues a Backend request, changes the Frontend route, changes local view state, or carries a
    disabled state with an explanation associated through `aria-describedby`.
13. THE Frontend SHALL include an automated accessibility test that renders every top-level route
    under each of the three Roles and asserts zero violations of landmark structure, table
    captions, a visible label associated with every form control, accessible names on icon-only
    controls, dialog `role` and `aria-modal` attributes, tab-set roles, the skip link as the first
    focusable control, and text contrast of at least 4.5 to 1 for body text and 3 to 1 for text at
    24px or larger, and THE Limitations_Document SHALL record that a passing automated check does
    not establish full WCAG conformance, which additionally requires manual testing with assistive
    technologies and expert accessibility review.

### Requirement 27: End-to-End Verification Against the Running Backend

**User Story:** As the requester, I want the finished frontend demonstrated against the real
backend, so that I know it works rather than compiles.

#### Acceptance Criteria

1. THE verification SHALL create a Python virtual environment from `requirements.txt` using the
   `py -3` interpreter, SHALL apply every outstanding database migration before issuing the first
   request, SHALL serve the Backend at `http://localhost:8000` and the Frontend development
   server at `http://localhost:3000`, SHALL start each of those two servers as a background
   process that does not block the invoking shell, SHALL separate multiple commands in a single
   shell invocation with `;` rather than `&&`, and SHALL configure the Backend to write outbound
   email to a destination readable on the workstation, because the bare `python` command on this
   workstation resolves to a non-functional stub, the Backend's default `CORS_ALLOWED_ORIGINS`
   admits only port 3000, the workstation shell is PowerShell, and criteria 13 and 14 require the
   emailed credentials to be observable.
2. THE verification SHALL register an owner through `POST /api/auth/register/owner` from the
   Frontend registration surface, SHALL confirm that request returns 201, and SHALL confirm the
   resulting session renders the owner Overview surface without a further sign-in.
3. THE verification SHALL sign in through the Frontend sign-in surface with the registered
   owner's email address as `identifier`, SHALL confirm that request returns 200, and SHALL
   confirm `GET /api/me` returns 200 with `role` equal to `owner` and with the Gym `name` equal to
   the Gym name submitted at registration.
4. THE verification SHALL confirm, for the `owner` session, that each Overview metric rendered
   for members, trainers, membership plans, and invoices equals the `count` value of page 1 of the
   corresponding `GET` response, that the rendered subscription state equals the
   `subscription_status` value from `GET /api/me`, and SHALL record the observed status of each of
   those five reads.
5. THE verification SHALL confirm `subscription_status` from `GET /api/me` is `trialing` or
   `active` before creating a member, SHALL create one membership plan, one trainer, and one
   member from the Frontend, SHALL confirm each of `POST /api/membership-plans`, `POST
   /api/trainers`, and `POST /api/members` returns 201, SHALL confirm each created record appears
   in the `results` array of the corresponding `GET` list response, and SHALL confirm the created
   member's `is_active` value is false, because no route creates a Membership.
6. THE verification SHALL update the member created in criterion 5 through `PATCH
   /api/members/{id}` and the Gym through `PATCH /api/gym` from the Frontend, SHALL confirm each
   request returns 200, and SHALL confirm each subsequent detail `GET` response carries the
   submitted value for every changed field.
7. THE verification SHALL confirm, using the sessions established by criteria 13 and 14, that the
   `trainer` session presents no navigation destination to the trainers surface and the `member`
   session presents no navigation destination to the members surface, that direct navigation to
   each refused route renders that Role's Overview surface with the message required by
   Requirement 6 criterion 2, and that the refused session issues no request to the route behind
   that surface.
8. THE verification SHALL register a second owner through `POST /api/auth/register/owner`, SHALL
   create one membership plan in that second Gym, and SHALL then confirm from the first Gym's
   `owner` session that navigating directly to the membership plan detail route with the second
   Gym's plan identifier returns 404 and renders the same message text and the same element
   structure as navigating to that route with an identifier that matches no record on the
   platform.
9. THE verification SHALL reduce the Backend's environment-configurable access-token lifetime to
   60 seconds without modifying any file under `core/` or `gymapp/`, SHALL wait until the stored
   access token has expired, SHALL then issue three concurrent Frontend reads, and SHALL confirm
   that exactly one `POST /api/auth/refresh` request is observed, that it returns 200, and that
   each of the three original requests is retried once and returns 200.
10. THE verification SHALL activate the Frontend sign-out control, SHALL confirm `POST
    /api/auth/logout` is observed with status 204, SHALL confirm the Session_Store afterwards
    holds no access token and no refresh token, and SHALL confirm that navigating to an
    authenticated route afterwards renders the sign-in surface and issues no request carrying an
    `Authorization` header.
11. THE verification SHALL obtain an invoice whose `status` is `open` from `GET /api/invoices` as
    the `owner` Role, SHALL confirm `POST /api/invoices/{id}/pay` returns 201 carrying `order_ref`,
    `amount_minor`, `currency`, and `key_id`, SHALL confirm the Frontend presents the `order_ref`
    value, SHALL confirm the invoice `status` remains `open` on a subsequent `GET
    /api/invoices/{id}`, and SHALL record invoice settlement as not verified because `status`
    changes only when the Payment_Gateway calls the Backend webhook.
12. THE verification SHALL record, for each of criteria 2 through 11 and 13 through 14, the
    request method and path exercised, the observed HTTP status code taken from the request the
    Frontend issued rather than inferred from the rendered surface, the observed Frontend
    behaviour, and a pass or fail outcome.
13. THE verification SHALL establish a `trainer` session by signing in with the email address and
    the temporary password recorded in the Backend's email output for the trainer created in
    criterion 5, and SHALL confirm that sign-in returns 200 and that `GET /api/me` reports `role`
    equal to `trainer`, because `invite_trainer` calls `send_invite_email` with a generated
    password.
14. THE verification SHALL establish a `member` session by submitting `POST
    /api/auth/password-reset` for the member created in criterion 5, submitting `POST
    /api/auth/password-reset/confirm` from the Frontend with the token read from the Backend's
    email output, and then signing in, and SHALL confirm the observed statuses are 202, 200, and
    200 with `role` equal to `member`, because `create_member_atomically` sends no invitation
    email and discards the generated password.
15. IF an outcome required by criteria 2 through 11 or criteria 13 through 14 cannot be observed
    because a dependency outside this repository is unavailable, THEN THE verification SHALL
    record that criterion as not verified, SHALL name the unavailable dependency, and SHALL claim
    no pass outcome for it.

### Requirement 28: Documented Limitations

**User Story:** As the requester, I want an honest list of what the frontend cannot do, so that I
can decide what to change in the backend next.

#### Acceptance Criteria

1. THE Frontend SHALL create `frontend/LIMITATIONS.md` containing exactly one entry for each item
   named in criteria 2 through 18 of this requirement, each entry naming the missing Backend
   capability as an absent route, an absent method on an existing route, an absent serializer
   field, or an unrouted service call; the affected Frontend surface by the name that surface
   carries in Requirements 13 through 22; and the Frontend behaviour delivered in its place; and
   each entry other than the resolved entry required by criterion 10 and the two deviation entries
   required by criteria 17 and 18 SHALL state the limitation as a present absence, naming no
   delivery date, no planned Backend change, and no workaround the Frontend does not implement.
2. THE Limitations_Document SHALL record all thirteen gaps in Backend Audit Findings section K as
   thirteen separately titled entries keyed `G1` through `G13`, merging none and omitting none,
   SHALL mark the `G13` entry with the disposition `resolved by approved backend change` and each
   of the twelve remaining entries with a disposition of `accommodated` or `surface omitted` as
   Requirement 25 criterion 5 requires, and SHALL state in the `G9` and `G11` entries that a
   Backend foreign key arrives as a bare integer with no resolving route — the `trainer`
   identifier on a member record read by a `trainer` session, and the `membership` and
   `saas_subscription` identifiers on every invoice —
   and that the delivered behaviour is therefore the fixed text required by Requirement 13
   criterion 5 and the subject-less invoice type label required by Requirement 16 criterion 3,
   never a resolved name.
3. THE Limitations_Document SHALL record that no Backend collection accepts a search term, a
   filter, or an ordering parameter because `REST_FRAMEWORK` registers no filter backend and no
   view declares `search_fields`, `filterset`, or `ordering_fields`, SHALL name every Data_List as
   the affected surface, and SHALL state that the delivered behaviour is server-supplied order,
   page-only navigation, and the visible note required by Requirement 8 criterion 5.
4. THE Limitations_Document SHALL record that no page size control exists because the configured
   pagination class sets no `page_size_query_param`, SHALL state that every collection page
   returns at most 25 rows and that `page` is the only query parameter any list route honours,
   SHALL name every Data_List as the affected surface, and SHALL state that the delivered
   behaviour is page controls rendered from the `next` and `previous` fields.
5. THE Limitations_Document SHALL record that no entity can be deleted, deactivated, or archived
   because no route accepts DELETE, and that a trainer record cannot be changed at all after
   creation because `core/urls.py` registers no `trainers/{id}` path, leaving `specialization` and
   `status` settable only in the creation payload, SHALL name the members, member detail,
   trainers, membership plans, gym, and profile surfaces as affected, and SHALL state that the
   delivered behaviour is the absence of any delete, deactivate, archive, or trainer edit control
   together with the visible note required by Requirement 14 criterion 7.
6. THE Limitations_Document SHALL record that no membership period can be started or renewed
   because `core/urls.py` routes nothing to `MembershipSerializer` and `create_membership` is
   reachable only from Python, SHALL state the consequence that a member created through `POST
   /api/members` holds no Membership, receives no membership invoice, and therefore reports
   `is_active` as false and `current_period_end` as null with no Frontend action able to change
   either value, and SHALL name the members surface, the member detail surface, and the My
   Membership surface as affected.
7. THE Limitations_Document SHALL record that no receipt surface exists because no route lists or
   retrieves a Payment and `order_response` returns `order_ref` without the Payment identifier
   that `GET /api/payments/{id}/receipt` requires, SHALL name the invoice detail surface as
   affected, and SHALL state that the delivered behaviour is payment initiation followed by the
   invoice re-request control required by Requirement 16 criterion 12.
8. THE Limitations_Document SHALL record that no seat limit and no seat usage figure is
   displayable because no route reports which SaasPlan the Gym holds and `/api/me` reports only a
   `subscription_status` string, SHALL name the gym surface and every Overview surface as
   affected, and SHALL state that the delivered behaviour is the omission of both figures and
   reliance on the `SEAT_LIMIT_REACHED` error details at the moment a creation attempt fails.
9. THE Limitations_Document SHALL record that a member created through `POST /api/members`
   receives no invitation email and holds no usable password because `create_member_atomically`
   sends no email and discards the generated temporary password, SHALL name the member creation
   surface as affected, SHALL state that the delivered behaviour is the message required by
   Requirement 13 criterion 9 directing the owner to the password reset flow, and SHALL state
   that `invite_trainer` does send a temporary password so the two creation flows differ.
10. THE Limitations_Document SHALL record the one approved Backend change as a resolved entry
    rather than a limitation, and that entry SHALL state that a `member_profile_id` field was added
    to `MeSerializer` in `core/serializers.py`; that the addition was required because
    `MeSerializer.id` is the `User` identifier, no response previously supplied a member their
    `MemberProfile` identifier, and identifier guessing is forbidden by Requirement 7 criterion 6,
    leaving `GET /api/members/{id}` unreachable for the `member` Role; that the field is additive
    and nullable and returns a non-null value for the `member` role only, matching the existing
    behaviour of `is_active_member` and `current_period_end`; that the My Membership surface is the
    affected surface and is now populated from `GET /api/members/{member_profile_id}` in addition to
    `GET /api/me`; that no permission class, queryset filter, view, or route changed, because
    `MemberSelfScope.has_object_permission` already admitted a member to their own `MemberProfile`;
    and that the complete Backend test suite was run after the change and passed, recorded as
    Requirement 25 criterion 11 requires.
11. THE Limitations_Document SHALL record that the display typeface `Signifier` and the body
    typeface `Söhne` are commercially licensed and are not shipped with the Frontend, SHALL name
    the exact fallback stack values declared in the Token_Layer for each of the two font custom
    properties, SHALL name every surface rendering display or body text as affected, and SHALL
    state that the delivered behaviour is rendering through the named fallback stack whenever the
    licensed face is unavailable.
12. THE Limitations_Document SHALL record every Frontend surface omitted under Requirement 25
    criterion 6 as one entry per omitted surface, naming the requirement criterion that surface
    would have satisfied, the Backend capability whose absence forced the omission, and the
    absence of any replacement surface, and SHALL carry that section with an explicit empty-list
    statement when no surface is omitted.
13. THE Limitations_Document SHALL record that no aggregate, statistics, or reporting route
    exists, so no revenue total, no outstanding balance total, no attendance figure, no growth
    percentage, and no period-over-period comparison is displayable, SHALL name every Overview
    surface and the invoices surface as affected, and SHALL state that the delivered behaviour is
    metrics limited to the `count` field of paginated list responses, the scalar fields of
    `/api/me`, and the single chart permitted by Requirement 22 criterion 3.
14. THE Limitations_Document SHALL record that no email-verification resend route and no
    authenticated password-change route exist, SHALL name the profile surface and the
    email-verification surface as affected, and SHALL state that the delivered behaviour is
    `email_verified` presented as a factual state with no resend control per Requirement 10
    criterion 7, and a password change control that navigates to the password reset request
    surface per Requirement 18 criterion 8.
15. THE Limitations_Document SHALL record that the accessibility criteria of Requirement 21 are
    verified by automated checks and keyboard traversal only, SHALL state that this establishes no
    claim of full WCAG conformance because conformance additionally requires manual testing with
    assistive technologies and expert accessibility review, and SHALL name every Frontend surface
    as affected.
16. THE Limitations_Document SHALL record that no conversational, assistant, prompt, or composer
    surface exists in the Frontend, SHALL state that `core/urls.py` registers no route accepting a
    free-text prompt and that no module under `core/services/` performs inference or text
    generation, SHALL state that the "Ask anything…" AI composer `DESIGN.md` specifies is therefore
    not reproduced, and SHALL state that the delivered behaviour is the absence of any such control
    rather than a disabled or placeholder one.
17. THE Limitations_Document SHALL record, as a deviation from `DESIGN.md` rather than as a Backend
    limitation, that the display font custom property declares a serif fallback stack while the CSS
    block of `DESIGN.md` sets `--font-signifier` to a sans-serif stack, SHALL state that `DESIGN.md`
    contradicts itself because its Signifier Substitute line names serif families and its Do rule
    states that a sans-serif is never substituted at these sizes, SHALL state that the conflict was
    resolved in favour of the serif stack because a sans-serif fallback would destroy the editorial
    signature the document exists to protect, SHALL name the exact stack declared, and SHALL name
    every surface rendering display text as affected.
18. THE Limitations_Document SHALL record, as a deviation from `DESIGN.md` rather than as a Backend
    limitation, that avatar monogram backgrounds are painted in Mist Gray or Blush Peach only, SHALL
    state that the Avatar Bubble component of `DESIGN.md` specifies light green and light blue tints
    while its own Don't rule admits no chromatic colour beyond the peach and brown pair, SHALL state
    that the conflict was resolved in favour of the Don't rule, and SHALL name every surface
    rendering an avatar monogram as affected.

---

## Correctness Properties

These are the invariants the design phase must make testable. Each names the requirement
criteria it enforces.

1. **No surface without a backing endpoint.** For any path the API_Client can construct, that
   path and method appear in the route inventory of Backend Audit Findings section A.
   *Enforces 1.1, 1.4, 26.8.*
2. **No client-side simulation of server capability.** For any Backend collection and any
   sequence of user interactions, the set of records rendered equals the `results` array of a
   Backend response in the order that response supplied, with no subset and no reordering.
   *Enforces 8.4, 8.6, 8.7.*
3. **Tenant isolation is respected by construction.** For any request the Frontend issues, the
   request carries no gym identifier in its path, query string, or body. *Enforces 7.1, 7.2.*
4. **Existence non-disclosure survives in the interface.** For any detail route, the rendered
   output for a 404 caused by another tenant's identifier is identical to the rendered output for
   a 404 caused by an identifier matching no record. *Enforces 7.3, 7.4, 27.8.*
5. **Role-gated controls match real permissions.** For any Role and any rendered action control,
   that Role appears in the admitted-role set of the route that control invokes. *Enforces 6.1,
   6.3, 26.7.*
6. **Money survives rendering.** For any Backend decimal string, the Money_Formatter output
   contains the same digits and the same decimal position as the input, and no intermediate
   JavaScript `number` is produced. *Enforces 9.1, 9.2, 26.6.*
7. **Error mapping is total.** For any of the twenty-two Backend error codes, the Error_Mapper
   returns a non-empty message, and for any response body outside the Error_Envelope shape it
   returns the unexpected-failure message. *Enforces 11.2, 11.3, 26.5.*
8. **Derived state is never recomputed.** For any member record, the active state rendered equals
   the Backend `is_active` value, independent of the browser clock and the browser timezone.
   *Enforces 10.1, 10.4.*
9. **Refresh is single-flight.** For any number of concurrent requests that each receive
   `TOKEN_EXPIRED`, exactly one `POST /api/auth/refresh` request is issued. *Enforces 5.7,
   26.10.*
10. **No dead control.** For any rendered interactive element, that element either issues a
    Backend request, changes the route, changes local view state, or carries a disabled state
    with an associated visible explanation. *Enforces 20.1, 20.2, 20.3.*
11. **Reduced motion is honoured.** While `prefers-reduced-motion` reports `reduce`, no rendered
    element carries a non-zero transition duration, a transform, or a count-up animation.
    *Enforces 24.9.*
12. **Tokens are the only source of visual values.** For any component file, that file contains
    no hexadecimal colour literal. *Enforces 3.39, 26.9.*
