# MK00 frontend — limitations

What this frontend cannot do, and why. Every entry names the missing backend
capability, the surface it affects, and what ships instead. Nothing here is a
placeholder for work in progress; these are the current boundaries of the API.

Verified against the running backend on the date of implementation. See
"Verification" at the end.

---

## 1. No search, filter, or sort on any collection

**Missing capability.** `REST_FRAMEWORK` in `gymapp/settings.py` registers no
`DEFAULT_FILTER_BACKENDS`. No view declares `search_fields`, `filterset_fields`, or
`ordering_fields`, and a repository-wide search for `query_params` and `request.GET`
across `core/` returns zero matches. The only query parameter any list route honours
is `page`.

**Affected.** Every list: members, trainers, membership plans, invoices.

**Delivered instead.** Server-supplied order, page-only navigation, and a visible
note on each list stating that search and filtering are not available. `buildUrl` in
`src/api/client.ts` throws if any parameter other than `page` is supplied, and a test
asserts it, so a non-functional search box cannot be added later by accident.

**Server-fixed ordering:** trainers by `pk`; members by `-join_date`, then `pk`;
membership plans by `price`; SaaS plans by `price`; invoices by `-issue_date`, then
`-sequence_no`.

## 2. No page-size control

**Missing capability.** The configured pagination class sets no
`page_size_query_param`. `PAGE_SIZE` is 25.

**Affected.** Every list.

**Delivered instead.** 25 rows per page, with previous/next controls driven by the
`next` and `previous` fields of the response rather than a computed page count.

## 3. Nothing can be deleted, deactivated, or archived

**Missing capability.** No route accepts DELETE. Verified live: `DELETE
/api/members/{id}` on an existing member returns **405 Method Not Allowed**.

**Affected.** Members, member detail, trainers, membership plans, gym, profile.

**Delivered instead.** No delete, deactivate, or archive control exists anywhere. A
test asserts the API layer can construct no DELETE request. Note that member and
trainer "active" state is derived server-side, not a writable field, so there is no
soft-delete path either.

## 4. No membership can be started or renewed

**Missing capability.** `MembershipSerializer` exists in `core/serializers.py`, but
`core/urls.py` routes nothing to it, and `create_membership` is reachable only from
Python.

**Consequence.** A member created through `POST /api/members` holds no Membership,
so no membership invoice is raised, so `is_active` is **false** and
`current_period_end` is **null** — permanently, as far as any UI action is concerned.
Confirmed live: a member created through the API returns `is_active=False`.

**Affected.** Members, member detail, My Membership.

**Delivered instead.** A standing note on the members list and on My Membership
stating that starting or renewing a paid period is not available through the API, and
that a member created here will therefore show as not active. The UI never claims a
member is active when the backend says otherwise.

## 5. No receipt

**Missing capability.** No route lists or retrieves a `Payment`. The pay-order
response returns `{order_ref, amount_minor, currency, key_id, receipt}` and no
Payment `id`, which is the identifier `GET /api/payments/{id}/receipt` requires. The
route therefore cannot be reached from any screen.

**Affected.** Invoice detail.

**Delivered instead.** Payment initiation shows the gateway order reference and a
control that re-reads the invoice. The `receipt` string in the pay response is not
presented as a receipt document or a link, because it is the gateway's receipt
reference, not a document. A note states plainly that no receipt is available.

## 6. Payment cannot be confirmed from the frontend

**Missing capability.** Not missing so much as by design: `POST
/api/invoices/{id}/pay` creates a gateway order. The invoice `status` changes only
when the gateway calls the backend's webhook, which is HMAC-authenticated and not a
frontend surface.

**Affected.** Invoice detail.

**Delivered instead.** After a successful order the UI states that the invoice
remains in its current status until the gateway notifies the backend, and offers a
re-read. There is no fake success screen. **Settlement is not verified** in this
work, because it requires the real gateway.

## 7. No trainer can be edited after creation

**Missing capability.** `core/urls.py` registers no `trainers/{id}` path at all — no
detail route, no PATCH, no DELETE. `TrainerProfileSerializer` exposes `specialization`
and `status` as writable, but nothing routes a write to them.

**Affected.** Trainers.

**Delivered instead.** List and create only. No edit control, no trainer detail
route, and a visible note saying specialization and status cannot be changed after
creation. Unlike member creation, `invite_trainer` does call `send_invite_email` with
a generated temporary password, so a new trainer can sign in.

## 8. No seat limit or seat usage figure

**Missing capability.** No route reports which `SaasPlan` a gym holds. `/api/me`
returns only a `subscription_status` string. `SaasPlan.max_members_allowed` is
serialised by `/api/saas-plans`, but nothing links a gym to its plan.

**Affected.** Gym, every Overview.

**Delivered instead.** Both figures omitted. A seat limit surfaces only as a
`SEAT_LIMIT_REACHED` error at the moment a member creation is refused, and the error
mapper renders the `seat_count` and `limit` the backend supplies in that error.

## 9. A created member cannot sign in

**Missing capability.** `create_member_atomically` sends no email. The
`MEMBER_INVITE` constant in `core/services/email.py` is never used, and the generated
temporary password is discarded.

**Affected.** Member creation.

**Delivered instead.** On a successful creation the UI states that the member has no
credentials yet and must use the password reset flow, and that message stays until
dismissed rather than disappearing with a toast. The password reset request surface
repeats the point.

## 10. No aggregate, statistics, or reporting endpoint

**Missing capability.** There is no route that returns a total, an average, a
time series, or any grouped figure.

**Affected.** Every Overview, and the invoices surface.

**Delivered instead.** Overview metrics are limited to the `count` field of page 1 of
a list the role may read, plus scalar fields of `/api/me`. There is **no** revenue
total, outstanding balance, attendance figure, growth percentage, trend arrow,
sparkline, or period-over-period comparison anywhere, because no data exists to
compute one from. The single chart (invoice amount against issue date, one line per
status, owner only) is built by fetching every invoice page, and renders nothing
until all pages are in — a chart drawn from page 1 of 4 looks authoritative and is
wrong.

## 11. Foreign keys arrive as bare integers with no way to resolve some of them

**Missing capability.** Serializers emit primary keys with no nested representation
and no name.

- `MemberProfileSerializer.plan` and `.trainer` are integers. Plan names are
  resolvable because `/api/membership-plans` is readable by all three roles, so the
  UI walks that collection and maps ids to names. **Trainer** names are resolvable
  only by an owner, because `GET /api/trainers` returns 403 for a trainer and a
  member.
- `InvoiceSerializer.membership` and `.saas_subscription` are integers with no
  resolving route at all.

**Affected.** Members, member detail, My Membership, invoices.

**Delivered instead.** Plan names resolved where possible, with the raw id shown as a
fallback rather than a blank. For a trainer viewing their own members the trainer
field reads "Assigned to you", which is accurate — `TrainerScope` admits a trainer
only to members assigned to them. On My Membership the trainer id is shown as-is with
a note explaining why. An invoice is labelled a subscription invoice or a membership
invoice, with no further detail about the subject.

## 12. Member photo is a URL, not an upload

**Missing capability.** `photo_url` is a `URLField` and no upload endpoint exists.

**Affected.** Member creation, member detail.

**Delivered instead.** A URL text input, with no file picker.

## 13. No email-verification resend, and no authenticated password change

**Missing capability.** Neither route exists.

**Affected.** Profile, email verification.

**Delivered instead.** `email_verified` is presented as a factual state with no
resend control and a note that the code cannot be resent. The password change control
navigates to the password reset flow, and says up front that completing it ends every
session for the account — because the backend blacklists every refresh token on
reset.

## 14. `/api/me` returns the User id, not the MemberProfile id

**Status: resolved by the one approved backend change.**

**What changed.** A `member_profile_id` field was added to `MeSerializer` in
`core/serializers.py`. It returns the caller's `MemberProfile` primary key for the
`member` role and `null` for `owner` and `trainer`, following the existing pattern of
`is_active_member` and `current_period_end`.

**Why it was required.** `MeSerializer.id` is the `User` id. No response anywhere gave
a member their own `MemberProfile` id, so `GET /api/members/{id}` was unreachable for
the `member` role, and guessing identifiers is not an acceptable alternative. The
permission layer already admitted the request:
`MemberSelfScope.has_object_permission` compares `_owning_member_id(obj)` to
`ctx.profile.pk`, and `_owning_member_id` returns `obj.pk` for a `MemberProfile`. Only
the identifier was missing.

**Blast radius.** Additive and nullable. No route, queryset, permission class, or view
changed. It adds no route, so `check_api_surface` is unaffected; it adds no queryset,
so `check_tenant_scoping` is unaffected. No test asserted an exact key set for
`/api/me` — the only exact-key-set assertion in the suite is on the pay-order response
in `test_property_22_order_creation.py`.

**Verified.** The full backend suite was run after the change:
`348 passed, 3 skipped, 4 deselected`. Live, `/api/me` returns
`id, email, first_name, last_name, phone, role, email_verified, gym,
subscription_status, is_active_member, current_period_end, member_profile_id`, with
`member_profile_id` null for an owner.

**Affected surface, now working.** My Membership is populated from `GET /api/me` plus
`GET /api/members/{member_profile_id}`, so a member can see their assigned plan,
trainer, join date, goal, and photo. It stays read-only: `MemberSelfScope` refuses a
member's unsafe methods on every view, and no view declares `member_writable`.

## 15. Vite's default port would break CORS

**Missing capability.** Not a backend gap. The backend's `CORS_ALLOWED_ORIGINS`
defaults to `http://localhost:3000` and `http://127.0.0.1:3000`,
`CORS_ALLOW_ALL_ORIGINS` is false, and `CORS_ALLOW_CREDENTIALS` is false. Vite
defaults to 5173.

**Delivered instead.** The dev server is pinned to port 3000 with `strictPort: true`,
so it fails loudly rather than silently starting on an origin the backend refuses.
Confirmed live: the backend returns `Access-Control-Allow-Origin:
http://localhost:3000`.

---

## Design-system deviations

`genesis-DESIGN.md` is the visual authority. Four of its components could not be
implemented as written, and the reason in each case is that the backend has no
counterpart. These are deviations from the design document, not backend limitations.

### D1. No global search bar

Genesis specifies a global search triggered by ⌘K, "rendered as a rounded-xl bar with
magnifying glass icon and keyboard shortcut badge". No backend endpoint accepts a
search term (see limitation 1), so the control is not rendered. A search box that
does nothing is worse than none.

### D2. Light theme only

Genesis's Do-list says to "provide sufficient contrast in both light and dark modes —
test both", but the document defines **no dark values**: there is no dark surface,
background, text, or border token anywhere in it. Implementing dark mode would mean
inventing a palette the design system does not specify. The light theme is
implemented in full; dark mode is not, and the gap is in the source document rather
than a decision taken here.

### D3. Destructive button variant unused

Genesis defines a destructive variant (red text, red border). No route accepts DELETE
(limitation 3), so the variant is neither rendered nor reachable and is not
implemented.

### D4. Product-specific components not transferable

Genesis's kit preview cards (200px image area, author avatar, download stats), its
interactive dot grid, and its checkbox-toggles for preferences belong to Genesis's own
product — a design-file sharing community. MK00 has no upload, no author, no download
count, and no preferences endpoint. The generic Card, Chip, and Input specs are used
instead.

### D5. Avatar tint

Genesis's Avatar Bubble specifies "background tinted (light green for JB, light blue
for AF)", which its own Don't-list forbids: "use indigo only for interactive elements
— never for decoration", and the palette admits no other chromatic colour. Avatar
monograms use the neutral chip surface. The cursor-pointer motif attached to avatars
signals live multi-user presence, which has no backend support, so it is not drawn.

### D6. `Secondary` colour token declared but unused

Genesis reserves `#20970B` "exclusively for the DESIGN.md brand highlight on the
homepage". MK00 has no such element. The token is declared in `tokens.css` for
fidelity and applied nowhere.

---

## Accessibility scope

Semantic landmarks, table captions and column scopes, labelled controls, accessible
dialog and drawer focus traps, Escape-to-close, focus return, a skip link, an ARIA
live region for toasts, `aria-disabled` with `aria-describedby` on every disabled
control, keyboard-operable navigation, and `prefers-reduced-motion` are all
implemented.

This does **not** amount to a claim of WCAG conformance. Conformance additionally
requires manual testing with real assistive technologies and expert review, neither of
which was performed here. Contrast ratios were chosen against the Genesis palette but
not instrumented.

---

## Environment notes

Two things were needed to make the stack run, neither of which is a code change.

1. **`.env` at the repo root.** Created from `.env.example`, which was left
   unmodified. `DJANGO_DEBUG=True` selects the console email backend, which is how the
   trainer temporary password and the password-reset code become observable. The file
   is gitignored and contains placeholder secrets only.

2. **The `SaasPlan` catalogue was empty.** This matters more than it sounds.
   `start_trial` in `core/services/subscriptions.py` falls back to the cheapest active
   `SaasPlan`, and its own docstring notes that "absence of a seeded catalogue is not a
   registration failure: the Gym is created without a subscription and simply cannot
   add members until one is attached". With no plans seeded, a freshly registered gym
   gets `subscription_status: null`, and then **every write is refused** — 403 from
   `SubscriptionWriteGate` on plans, gym, and trainers, and 402
   `SUBSCRIPTION_REQUIRED` on member creation. Three plans (Starter, Growth, Scale)
   were inserted as data. No backend code was touched. A deployment checklist should
   include seeding this catalogue.

---

## Verification performed

**Backend test suite, after the `member_profile_id` change:**
`348 passed, 3 skipped, 4 deselected`.

**Frontend gates:** TypeScript strict with zero errors; ESLint with zero errors and
zero warnings; 39 unit tests passing; production build emitting a separate chunk per
route.

**Live end-to-end against the running backend, 21 of 22 checks matching the expected
HTTP status.** Owner registration (201), login (200), `/api/me` (200, with
`member_profile_id` present), the four Overview counts (200), gym read (200),
membership plan create (201), trainer create (201), member create (201, `is_active`
false as expected), member update (200), gym update (200), a second gym registered and
its member id requested from the first gym's owner session (404, **byte-identical to a
nonexistent id**), password reset request (202), logout (204), and `DELETE` on a real
member (405).

**The one mismatch was my own expectation, not a defect:** presenting a blacklisted
refresh token returns **400**, not 401. The client treats any non-OK refresh response
as the end of the session, so behaviour is correct; only the test's expected value was
wrong.

**Not verified, and why:**

- **Invoice settlement.** Requires the real Razorpay gateway to call the webhook.
- **A trainer and a member session end to end.** Both are creatable and both receive
  or can obtain credentials (trainer by invite email, member by password reset), but
  driving those sign-ins was not completed in this pass. Role gating is covered by
  unit tests against the navigation model and the route inventory.
- **Token refresh against the live server.** Covered by unit tests, including the
  single-flight case where five concurrent 401s consume exactly one refresh token —
  which matters because the backend rotates and blacklists refresh tokens, so a double
  refresh destroys the session.
- **Browser console and rendered layout.** No browser was driven. The production build
  succeeds and every module transforms without error, but visual QA against
  `genesis-DESIGN.md` and a console check remain outstanding.
