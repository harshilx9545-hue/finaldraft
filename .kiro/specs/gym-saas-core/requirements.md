# Requirements Document

## Introduction

This specification covers Phase 1 of the gymapp platform: the monetizable core. Phase 1 converts the
existing single-scope Django project into a multi-tenant SaaS product that can accept money, by
delivering four capability areas and nothing else:

1. **Multi-tenancy** — introduce a `Gym` tenant entity and scope every currently-global domain model to it.
2. **Deployment-safe configuration** — move secrets and environment-specific values out of source, and
   make production hardening explicit.
3. **Authentication and role-based authorization** — email-primary identity, JWT tokens, and enforced
   owner/trainer/member permissions. The project currently has zero authorization logic.
4. **Payments and monetization** — Razorpay-backed billing for both the platform-to-gym SaaS
   subscription and the member-to-gym membership fee, with idempotent webhooks and GST-capable invoices.

### Decisions fixed for this phase

| Decision | Value |
| --- | --- |
| Monetization model | Dual: Gym_Owner pays the Platform a SaaS subscription, AND Member pays the Gym a membership fee through the Platform |
| Plan modelling | Two distinct models: `SaasPlan` (tier, seat limit) and `MembershipPlan` (price, duration). The current conflated `Plan` model is split. |
| Tenancy | True multi-tenant: one deployment serves many independent Gyms |
| Payment gateway | Razorpay, India, INR, UPI required |
| Tax | GST fields present on every Invoice; GST computation activates per-Gym when a verified GSTIN is present |
| Database | Rebuilt from scratch. No production data to preserve. `db.sqlite3` and `core/migrations/0001_initial.py` are discarded and a single clean baseline migration is generated. |
| Login identifier | Email is the canonical `USERNAME_FIELD`; phone is a unique alternate login credential |
| Token strategy | JWT access + refresh tokens |

### Baseline defects this phase corrects

Verified against the current codebase: `core/models.py` (16 models), `gymapp/settings.py`, `core/apps.py`,
`core/migrations/0001_initial.py`, `requirements.txt`. `core/views.py` and `core/tests.py` are empty and
no REST framework is installed.

- No `Gym` entity exists. `Plan`, `Equipment`, `MemberProfile`, `TrainerProfile` and `StrengthStandard`
  are globally scoped, so one Gym's data would be visible to every other Gym.
- `SECRET_KEY` is hardcoded with a `django-insecure-` prefix, `DEBUG = True`, `ALLOWED_HOSTS = []`.
- `MAILERS` is not a Django setting. Email is silently non-functional.
- `User.role` has no default and is not `blank=True`, so `createsuperuser` produces a user whose role
  matches none of `ROLE_CHOICES`.
- `Payment` has no gateway reference, no idempotency key, no currency, and only `paid`/`due` states.
- Nothing computes membership expiry, so memberships never expire.
- `requirements.txt` pins `Django>=5.0,<6.0` while `settings.py` documents Django 6.1.

## Glossary

- **Platform**: The hosted multi-tenant application, operated by the Platform_Operator, that serves all Gyms from one deployment.
- **Platform_Operator**: The business operating the Platform, and the recipient of SaaS subscription revenue.
- **Gym**: The tenant entity. Every tenant-scoped record belongs to exactly one Gym.
- **Gym_Owner**: A User with role `owner`, associated with exactly one Gym through an OwnerProfile.
- **Trainer**: A User with role `trainer`, associated with exactly one Gym through a TrainerProfile.
- **Member**: A User with role `member`, associated with exactly one Gym through a MemberProfile.
- **Tenant_Scope**: The mechanism that restricts every database query issued on behalf of a request to records belonging to the requesting User's Gym.
- **SaasPlan**: A Platform-defined subscription tier purchased by a Gym_Owner. Carries a recurring price, a billing interval, and `max_members_allowed`.
- **SaasSubscription**: The record binding one Gym to one SaasPlan for a billing period.
- **MembershipPlan**: A Gym-defined membership package sold to Members. Carries a price, `duration_days`, and the `includes_trainer` and `includes_diet` flags. Replaces the membership-facing half of the current `Plan` model.
- **Membership**: The record binding one Member to one MembershipPlan for a dated period, with a computed end date.
- **Invoice**: An immutable financial document stating an amount payable by a Payer, with tax fields.
- **Payment**: A record of a settlement attempt against an Invoice, carrying a gateway reference, an idempotency key, a currency, and a lifecycle status.
- **Payer**: The party owing an Invoice. A Gym_Owner for SaaS Invoices, a Member for membership Invoices.
- **Payment_Gateway**: Razorpay, the external provider that processes card, UPI, and netbanking transactions.
- **Gateway_Adapter**: The Platform component that constructs Payment_Gateway orders and interprets Payment_Gateway responses.
- **Webhook_Handler**: The Platform endpoint that receives asynchronous Payment_Gateway event notifications.
- **Idempotency_Key**: A value unique per logical financial operation, used to guarantee that repeated processing produces exactly one Payment record.
- **Auth_Service**: The Platform component that authenticates credentials and issues, refreshes, and revokes JWTs.
- **Authorization_Layer**: The Platform component that evaluates a request against the requesting User's role and Gym before the request reaches data.
- **Config_Loader**: The Platform component that reads configuration values from environment variables at startup.
- **GSTIN**: The Indian Goods and Services Tax Identification Number recorded against a Gym or against the Platform_Operator.
- **Audit_Record**: An append-only entry recording who changed which financial record, when, and what the previous and new values were.
- **Soft_Delete**: Marking a record inactive by setting a deletion timestamp, so that the row is retained and excluded from default queries.
- **API**: The HTTP interface exposed by the Platform.

## Requirements

### Requirement 1: Gym Tenant Entity

**User Story:** As a Platform_Operator, I want each gym represented as a first-class tenant record, so that data belonging to different gyms can be separated and billed independently.

#### Acceptance Criteria

1. THE Platform SHALL provide a Gym model with a name of at most 200 characters, matching the existing `OwnerProfile.business_name` limit, a slug of at most 60 characters restricted to lowercase ASCII letters, digits, and hyphens and unique across the Platform, a contact email, a contact phone in E.164 format of at most 15 characters, a timezone restricted to a valid IANA time zone identifier, a nullable GSTIN, a created timestamp that is immutable after creation, and an active flag that defaults to true.
2. WHEN an owner registration request passes field validation, THE Platform SHALL create exactly one Gym record, one User record, and one OwnerProfile record linked to that Gym in one atomic operation.
3. THE Platform SHALL relate every OwnerProfile, TrainerProfile, and MemberProfile to exactly one Gym through a non-nullable foreign key.
4. IF a request to create or update a Gym supplies a slug that matches the slug of an existing Gym when compared without regard to letter case, THEN THE Platform SHALL reject the request with a validation error naming the slug field, and SHALL leave every stored Gym record unchanged.
5. WHILE a Gym has its active flag set to false, THE Auth_Service SHALL authenticate Users of that Gym and SHALL issue access and refresh tokens to those Users.
6. WHEN a Gym record's name is updated, THE Platform SHALL leave the `business_name` value on that Gym's OwnerProfile unchanged.
7. WHILE a Gym has its active flag set to false, THE Authorization_Layer SHALL deny every tenant-scoped API request from Users of that Gym with HTTP 403.
8. IF any part of the Gym, User, and OwnerProfile creation described in criterion 2 fails, THEN THE Platform SHALL persist no Gym, User, or OwnerProfile record from that attempt.
9. WHEN THE Platform derives a Gym slug from the submitted `business_name`, THE Platform SHALL transliterate that value to ASCII, convert it to lowercase, collapse every run of characters that are neither ASCII letters nor digits into a single hyphen, strip leading and trailing hyphens, and truncate the result to 60 characters.
10. WHERE the transliterated `business_name` yields an empty value, THE Platform SHALL use the literal value `gym` as the slug derivation base.
11. IF a derived slug matches the slug of an existing Gym when compared without regard to letter case, THEN THE Platform SHALL append a hyphen and an integer suffix beginning at 2 and ascending by 1, truncating the derivation base so that each candidate is at most 60 characters, for at most 50 suffix attempts.
12. IF no unused slug is found within 50 suffix attempts, THEN THE Platform SHALL reject the registration request with a validation error naming the slug field and SHALL persist no Gym, User, or OwnerProfile record from that attempt.
13. THE Platform SHALL resolve every read of a Gym's name from the Gym record rather than from `OwnerProfile.business_name`.

### Requirement 2: Tenant Scoping of Domain Models

**User Story:** As a Gym_Owner, I want my gym's plans, equipment, trainers, and members to be invisible to other gyms, so that my business data stays private.

#### Acceptance Criteria

1. THE Platform SHALL add a non-nullable Gym foreign key to MembershipPlan, Equipment, MemberProfile, and TrainerProfile.
2. THE Platform SHALL scope StrengthStandard records with a nullable Gym foreign key, WHERE a null value denotes a Platform-provided reference standard readable by every Gym.
3. WHEN a Gym_Owner or Trainer creates a tenant-scoped record, THE Platform SHALL set the Gym foreign key from the authenticated User's Gym and SHALL ignore any Gym identifier present in the request body.
4. THE Platform SHALL enforce uniqueness of MembershipPlan name per Gym rather than across the Platform.
5. THE Platform SHALL enforce uniqueness of StrengthStandard on the combination of Gym, exercise name, and gender.
6. IF a request assigns a MemberProfile a Trainer whose TrainerProfile belongs to a different Gym, THEN THE Platform SHALL reject the assignment with a validation error naming the trainer field.
7. IF a request assigns a MemberProfile a MembershipPlan that belongs to a different Gym, THEN THE Platform SHALL reject the assignment with a validation error naming the plan field.

### Requirement 3: Tenant Isolation at the API Boundary

**User Story:** As a Gym_Owner, I want the system to structurally prevent cross-gym access, so that a bug in one endpoint cannot leak my data.

#### Acceptance Criteria

1. THE Tenant_Scope SHALL filter every queryset serving an authenticated API request against a tenant-scoped model, defined as any model that carries a Gym foreign key, to records whose Gym equals the requesting User's Gym together with StrengthStandard records whose Gym foreign key is null as permitted by criterion 2.2, and SHALL apply that filter independent of the requesting User's `is_staff` and `is_superuser` values.
2. WHEN an authenticated User requests a tenant-scoped record belonging to a different Gym by identifier, THE API SHALL respond with HTTP 404 and SHALL exclude any attribute of the requested record from the response body.
3. WHEN an authenticated User submits a create, update, partial update, or delete request targeting a tenant-scoped record belonging to a different Gym, THE API SHALL respond with HTTP 404 and SHALL leave every stored record unchanged.
4. WHEN a User authenticated as a member of one Gym requests a tenant-scoped API endpoint, THE API SHALL return only records whose Gym is that User's Gym, including records nested inside a returned representation and records contributing to any aggregate count in the response body, and SHALL leave every record belonging to every other Gym unchanged.
5. WHEN an authenticated User names a tenant-scoped record identifier belonging to a different Gym, THE API SHALL respond with the same HTTP status code and the same response body structure that THE API returns for an identifier matching no record on the Platform, so that record existence is not disclosed.
6. IF an authenticated User holds no OwnerProfile, TrainerProfile, or MemberProfile that has not been soft-deleted, THEN THE API SHALL respond with HTTP 403 for every tenant-scoped endpoint and SHALL issue no query against any tenant-scoped model.
7. THE Platform SHALL treat as non-tenant-scoped exactly the endpoints for token issue, token refresh, logout, password-reset request, password-reset confirmation, email verification, owner registration, the SaasPlan catalogue, and the Payment_Gateway webhook, SHALL serve no tenant-scoped record from those endpoints, and SHALL treat every endpoint absent from that list as tenant-scoped.
8. THE Platform SHALL enforce the filtering stated in criterion 1 for every tenant-scoped endpoint through one shared tenant-filtering component.
9. WHEN a deployment is prepared, THE Platform SHALL execute an automated conformance check over every registered endpoint, and SHALL fail the deployment IF one or more tenant-scoped endpoints serve requests without the shared tenant-filtering component named in criterion 8.
10. WHERE a User's `is_staff` or `is_superuser` value is true, THE Platform SHALL permit access to records of a Gym other than that User's Gym only through the administrative interface, and WHEN such access occurs, THE Platform SHALL write an Audit_Record naming the acting User, the record identifier, the record's Gym, the operation, and the timestamp.

### Requirement 4: Separation of SaaS Plans from Membership Plans

**User Story:** As a Platform_Operator, I want subscription tiers and gym membership packages modelled separately, so that platform pricing and gym pricing evolve independently.

#### Acceptance Criteria

1. THE Platform SHALL provide a SaasPlan model, owned by the Platform_Operator and not scoped to any Gym, with a name, a price, a currency, a billing interval in months, and `max_members_allowed`.
2. THE Platform SHALL provide a MembershipPlan model, scoped to one Gym, with a name, a price, a currency, `duration_days`, `includes_trainer`, and `includes_diet`.
3. THE Platform SHALL remove `max_members_allowed` from the membership-facing model, so that seat limits are expressed only on SaasPlan.
4. THE Platform SHALL require `duration_days` on MembershipPlan to be greater than or equal to 1.
5. THE Platform SHALL require the price on SaasPlan and on MembershipPlan to be greater than or equal to 0.
6. WHERE a MembershipPlan price equals 0, WHEN a Member is assigned that MembershipPlan, THE Platform SHALL create the Membership record and SHALL generate no Invoice.
7. WHERE a MembershipPlan price is greater than 0, WHEN a Member is assigned that MembershipPlan, THE Platform SHALL create the Membership record and SHALL generate an Invoice for the plan price.

### Requirement 5: Seat Limit Enforcement

**User Story:** As a Platform_Operator, I want the member cap on each subscription tier enforced, so that gyms cannot exceed the capacity they paid for.

#### Acceptance Criteria

1. WHEN a Gym_Owner or Trainer requests creation of a MemberProfile, THE Platform SHALL evaluate that Gym's Seat_Count, defined as the number of MemberProfile rows belonging to the Gym that are not soft-deleted, and SHALL perform the seat evaluation and the row creation as one atomic operation, so that for N concurrent creation requests against a Gym with K remaining seats exactly min(N, K) requests create a record and the remainder are rejected under criterion 2.
2. IF a Gym's Seat_Count is equal to or greater than the non-null `max_members_allowed` value of that Gym's current SaasPlan, THEN THE Platform SHALL reject creation of a MemberProfile with HTTP 409 and a message stating the current Seat_Count and the limit, and SHALL leave the Gym's MemberProfile rows and User records unchanged.
3. WHERE the Gym's current SaasPlan has a null `max_members_allowed`, THE Platform SHALL treat the seat limit as unlimited and SHALL perform no seat evaluation; otherwise THE Platform SHALL treat `max_members_allowed` as an integer from 1 to 100000 inclusive.
4. FOR ALL Gyms at all times, the Seat_Count of a Gym SHALL be less than or equal to the non-null `max_members_allowed` value of that Gym's current SaasPlan, and SHALL be unbounded WHERE that value is null.
5. IF a Gym_Owner requests a SaasPlan whose `max_members_allowed` is strictly lower than that Gym's current Seat_Count, THEN THE Platform SHALL reject the change with HTTP 409 and a message stating the current Seat_Count and the requested limit, and SHALL leave the Gym's SaasSubscription unchanged.
6. WHERE a requested SaasPlan's `max_members_allowed` is null, or is equal to or greater than the Gym's current Seat_Count, THE Platform SHALL accept the plan change.
7. IF a Gym has no SaasSubscription in status `trialing` or `active`, THEN THE Platform SHALL reject creation of new MemberProfile records with HTTP 402 and SHALL create no MemberProfile row.
8. WHILE a Gym has no SaasSubscription in status `trialing` or `active`, THE Platform SHALL continue to permit updates to existing MemberProfile records and SHALL apply no seat evaluation to those updates, so that only operations that increase Seat_Count are gated.
9. WHEN Invoice settlement or a Membership date change causes an existing Member of a Gym to become active under 20.5, THE Platform SHALL complete that transition without a seat evaluation, because the transition does not change Seat_Count.
10. IF restoring a soft-deleted MemberProfile would raise the Gym's Seat_Count above the non-null `max_members_allowed` value of that Gym's current SaasPlan, THEN THE Platform SHALL reject the restore with HTTP 409 and a message stating the current Seat_Count and the limit, and SHALL leave the record soft-deleted.

### Requirement 6: Environment-Based Configuration

**User Story:** As an operator deploying the Platform, I want every environment-specific value supplied by the environment, so that the same source tree runs safely in development and production.

#### Acceptance Criteria

1. THE Config_Loader SHALL read `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, the database connection, the email connection, and the Payment_Gateway credentials from environment variables at startup.
2. THE Platform SHALL contain no `SECRET_KEY` value in tracked source files.
3. IF the `SECRET_KEY` environment variable is absent at startup, THEN THE Config_Loader SHALL raise a startup error naming `SECRET_KEY` and SHALL prevent the process from serving requests.
4. IF the `DEBUG` environment variable is absent, THEN THE Config_Loader SHALL set `DEBUG` to false.
5. WHILE `DEBUG` is false, IF `ALLOWED_HOSTS` resolves to an empty list, THEN THE Config_Loader SHALL raise a startup error naming `ALLOWED_HOSTS`.
6. WHILE `DEBUG` is false, IF `ALLOWED_HOSTS` contains the wildcard value `*` or an entry that is not a valid hostname or IP address, THEN THE Config_Loader SHALL raise a startup error naming the offending entry.
7. WHILE `DEBUG` is false, IF the resolved `SECRET_KEY` value begins with `django-insecure-`, THEN THE Config_Loader SHALL raise a startup error stating that a development key is in use.
8. THE Config_Loader SHALL complete every configuration validation check before the Platform accepts any request, so that a violated security requirement prevents startup rather than degrading a single component.
9. THE Platform SHALL define `STATIC_ROOT`, `MEDIA_ROOT`, and `MEDIA_URL`.
10. THE Platform SHALL define a logging configuration that writes records at level `INFO` and above to standard output, and that routes records from the payments and authentication components to a named logger.
11. THE Platform SHALL provide a `.env.example` file listing every environment variable name the Config_Loader reads, with placeholder values and no real secrets.
12. THE Platform SHALL support SQLite for local development and PostgreSQL for production, selected by the database environment variable.
13. THE Platform SHALL pin `requirements.txt` to the Django major version that the deployed code targets, so that the declared dependency range and the project's target version agree.

### Requirement 7: Production Security Hardening

**User Story:** As an operator, I want production-only security settings applied automatically, so that a deployment cannot accidentally serve traffic without transport and cookie protection.

#### Acceptance Criteria

1. WHILE `DEBUG` is false, THE Platform SHALL set `SECURE_SSL_REDIRECT` to true, `SESSION_COOKIE_SECURE` to true, `CSRF_COOKIE_SECURE` to true, and `SECURE_HSTS_SECONDS` to a value of at least 31536000.
2. WHILE `DEBUG` is false, THE Platform SHALL set `SECURE_PROXY_SSL_HEADER` so that a terminating proxy's forwarded protocol header is honoured.
3. THE Platform SHALL set `SECURE_CONTENT_TYPE_NOSNIFF` to true and `X_FRAME_OPTIONS` to `DENY`.
4. WHEN a deployment is prepared, THE Platform SHALL execute `manage.py check --deploy` against the production configuration, and SHALL fail the deployment IF the command reports one or more issues of severity `WARNING` or higher.
5. THE CoreConfig application configuration SHALL declare `default_auto_field` as `django.db.models.BigAutoField`.

### Requirement 8: Functional Email Delivery Configuration

**User Story:** As a Member, I want to receive verification and password-reset email, so that I can complete account setup and recover access.

#### Acceptance Criteria

1. THE Platform SHALL remove the `MAILERS` setting, which Django does not recognise and therefore silently ignores.
2. THE Config_Loader SHALL read `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, and `DEFAULT_FROM_EMAIL` from environment variables.
3. WHILE `DEBUG` is true, IF the `EMAIL_BACKEND` environment variable is absent, THEN THE Config_Loader SHALL select the console email backend.
4. WHILE `DEBUG` is false, IF the `EMAIL_BACKEND` environment variable is absent, THEN THE Config_Loader SHALL raise a startup error naming `EMAIL_BACKEND`, and SHALL select no fallback backend.
5. WHILE `DEBUG` is false, WHERE the selected `EMAIL_BACKEND` is the SMTP backend, IF `EMAIL_HOST`, `EMAIL_PORT`, or `DEFAULT_FROM_EMAIL` is absent, THEN THE Config_Loader SHALL raise a startup error naming every absent variable.
6. WHERE an email is not required to complete the originating operation, IF sending that email raises a transport error, THEN THE Platform SHALL log the error with the recipient address and the message type, and SHALL return the originating API request as successful.

### Requirement 9: Clean Migration Baseline

**User Story:** As a developer, I want one clean migration set that already includes tenancy and the final identity model, so that I do not carry backfill code for data that never existed.

#### Acceptance Criteria

1. THE Platform SHALL delete `core/migrations/0001_initial.py` and the local `db.sqlite3` file, and SHALL generate a single replacement baseline migration.
2. IF deletion of `core/migrations/0001_initial.py` does not succeed, THEN THE Platform SHALL generate no baseline migration, so that migration replacement is applied as one indivisible step.
3. THE baseline migration SHALL declare every Gym foreign key on MembershipPlan, Equipment, MemberProfile, and TrainerProfile as non-nullable without a data backfill step.
4. THE baseline migration SHALL declare the User model with email as the login identifier.
5. WHEN `manage.py migrate` runs against an empty database, THE Platform SHALL apply all migrations and SHALL report zero errors.
6. WHEN `manage.py makemigrations --check --dry-run` runs after migration, THE Platform SHALL report that no model changes are pending.

### Requirement 10: Identity and Credentials

**User Story:** As a Member, I want to sign in with my email address or my phone number, so that I can access my account with whichever identifier I remember.

#### Acceptance Criteria

1. THE Platform SHALL set the User model's `USERNAME_FIELD` to email and SHALL enforce uniqueness of email across the Platform.
2. THE Platform SHALL require a non-empty email value on every User record.
3. THE Platform SHALL store phone in E.164 format and SHALL enforce uniqueness of phone across the Platform WHERE a phone value is present.
4. WHEN a login request supplies an email and a correct password, THE Auth_Service SHALL authenticate the matching User.
5. WHEN a login request supplies a phone in E.164 format and a correct password, THE Auth_Service SHALL authenticate the User holding that phone value.
6. IF a login request supplies an identifier that matches no User, or supplies a password that does not match the identified User, THEN THE Auth_Service SHALL respond with HTTP 401 and one identical generic message for both conditions, so that account existence is not disclosed.
7. IF a login request supplies a phone identifier that is not valid E.164 format, THEN THE Auth_Service SHALL reject the request with HTTP 401 without comparing the identifier against stored phone values.
8. IF the Auth_Service is unavailable or raises an internal error during a login attempt, THEN THE API SHALL respond with HTTP 500 and a machine-readable code distinct from the code returned for rejected credentials.
9. THE Platform SHALL remove `username` from the login path, and SHALL accept a registration request that supplies no username value.
10. IF a registration request supplies a phone value that is not valid E.164, THEN THE Platform SHALL reject the request with a validation error naming the phone field.

### Requirement 11: Registration and Role Assignment

**User Story:** As a Platform_Operator, I want roles assigned by the system rather than claimed by the registrant, so that a member cannot register as an owner.

#### Acceptance Criteria

1. THE User model SHALL declare `role` with a default value of `member` and SHALL restrict stored values to `owner`, `trainer`, and `member`.
2. WHEN a User record is created through `createsuperuser`, THE Platform SHALL assign a role value that is a member of the role choices.
3. WHEN an unauthenticated registration request arrives at the owner signup endpoint, THE Platform SHALL create a User with role `owner`, a Gym, and an OwnerProfile, and SHALL ignore any role value present in the request body.
4. WHEN a Gym_Owner invites a Trainer or a Member, THE Platform SHALL create the User with the role stated by the Gym_Owner and SHALL set the new User's Gym to the inviting Gym_Owner's Gym.
5. THE Platform SHALL reject self-service registration for the `trainer` and `member` roles, so that Trainer and Member accounts originate only from a Gym_Owner invitation.
6. FOR ALL registration and profile-update requests, the role stored on a User SHALL equal the role determined by the Platform from the endpoint used and from the inviting Gym_Owner's instruction, independent of every client-supplied field.

### Requirement 12: Role and Profile Consistency

**User Story:** As a developer, I want a user's role and profile records to be structurally consistent, so that authorization decisions based on role are never contradicted by the data.

#### Acceptance Criteria

1. THE Platform SHALL permit each User to hold at most one profile record across OwnerProfile, TrainerProfile, and MemberProfile, as a deliberate product decision, and SHALL require a person acting in two roles, such as a Gym_Owner who also trains Members, to be represented by one User account per role, each with its own email identifier.
2. IF a request would create a profile whose type does not correspond to the User's `role`, THEN THE Platform SHALL reject the request with a validation error naming the User's `role` and the requested profile type, and SHALL create no profile record.
3. IF a request would create a profile for a User that already holds a profile of any type that has not been soft-deleted, THEN THE Platform SHALL reject the request with a validation error naming the existing profile type, and SHALL leave the existing profile record unchanged.
4. FOR ALL User records whose `is_staff` and `is_superuser` are both false, the User SHALL hold exactly one profile that has not been soft-deleted, whose type corresponds to `role` as OwnerProfile for `owner`, TrainerProfile for `trainer`, and MemberProfile for `member`, and THE Platform SHALL create the User record and its corresponding profile in one atomic operation, so that no committed state contains such a User without a matching profile.
5. IF a request changes a User's `role` while a profile of the previous role's type exists and has not been soft-deleted, THEN THE Platform SHALL reject the request with a validation error naming the current `role` and the existing profile type, and SHALL leave both the `role` value and the profile record unchanged.
6. IF a request would create an OwnerProfile, TrainerProfile, or MemberProfile for a User whose `is_staff` or `is_superuser` is true, THEN THE Platform SHALL reject the request with a validation error stating that a Platform_Operator staff account holds no tenant profile, and SHALL create no profile record.
7. WHEN a Gym_Owner or a Platform_Operator staff account requests a change to a User's `role` and that User holds no profile of the previous role's type that has not been soft-deleted, THE Platform SHALL update `role` and create the profile corresponding to the new `role` in one atomic operation.

### Requirement 13: JWT Token Lifecycle

**User Story:** As a Member using a future installable app, I want token-based sessions, so that the app can stay signed in without cookies.

#### Acceptance Criteria

1. WHEN the Auth_Service authenticates a login request, THE Auth_Service SHALL issue a signed access token and a signed refresh token.
2. THE Auth_Service SHALL include the User identifier, the role, and the Gym identifier as claims in each access token.
3. THE Auth_Service SHALL set the access token lifetime to a value of at most 60 minutes and the refresh token lifetime to a value of at most 30 days, both read from environment variables.
4. WHEN a request presents an expired access token, THE API SHALL respond with HTTP 401 and a machine-readable code that distinguishes expiry from an invalid signature.
5. WHEN a refresh request presents a valid, unrevoked refresh token, THE Auth_Service SHALL issue a new access token and SHALL invalidate the presented refresh token.
6. WHEN a logout request presents a refresh token, THE Auth_Service SHALL revoke that refresh token, and any subsequent refresh request presenting the same token SHALL receive HTTP 401.
7. FOR ALL issued access tokens, decoding a token SHALL yield exactly the User identifier, role, and Gym identifier that were encoded, so that encode followed by decode is an identity on those claims.
8. THE Authorization_Layer SHALL derive the requesting User's role and Gym from the database record identified by the token, and SHALL treat token claims as untrusted for authorization decisions.

### Requirement 14: Password Reset and Email Verification

**User Story:** As a Member, I want to verify my address and reset a forgotten password, so that I can maintain access to my own account.

#### Acceptance Criteria

1. WHEN a User account is created, THE Platform SHALL send a verification message containing a single-use token to the User's email address.
2. WHEN a valid, unexpired verification token is presented, THE Platform SHALL mark the User's email as verified.
3. THE Platform SHALL expire verification tokens 72 hours after issue and password-reset tokens 60 minutes after issue.
4. WHEN a password-reset request supplies an email address, THE Platform SHALL respond with HTTP 202 whether or not a matching User exists, so that account existence is not disclosed.
5. WHEN a valid, unexpired reset token and a new password are presented, THE Platform SHALL set the new password and SHALL revoke every outstanding refresh token for that User.
6. IF an expired or already-consumed token is presented to the reset-confirmation endpoint, THEN THE Platform SHALL respond with HTTP 400 and a message stating that the token is no longer valid.
7. THE Platform SHALL apply the HTTP 202 uniform response only to the reset-request endpoint, and SHALL apply explicit HTTP 400 token errors only to the reset-confirmation endpoint, so that account existence is concealed at request time while token validity is reported at confirmation time.
8. THE Platform SHALL apply the configured password validators to every password set through registration, reset, or change.

### Requirement 15: Role-Based Authorization

**User Story:** As a Member, I want other members unable to read my payments and measurements, so that my personal and financial data stays private.

#### Acceptance Criteria

1. THE Authorization_Layer SHALL evaluate every API request against the requesting User's role and Gym before any record is read or written.
2. WHERE the requesting User's role is `member`, THE Authorization_Layer SHALL permit read and write access to Member-scoped records whose Member is the requesting User, and SHALL deny with HTTP 403 every create, update, partial update, or delete request from that User targeting a record that is not Member-scoped.
3. WHERE the requesting User's role is `trainer`, THE Authorization_Layer SHALL permit read access to records of Members assigned to that Trainer, and SHALL respond with HTTP 404 to a request for a record of a Member in the same Gym who is not assigned to that Trainer.
4. WHERE the requesting User's role is `owner`, THE Authorization_Layer SHALL permit read access to records belonging to that Gym_Owner's Gym, and SHALL permit write access to those records except where a declared immutability rule applies, including the settled-Invoice rule of 19.7.
5. THE Authorization_Layer SHALL deny every unauthenticated request to a tenant-scoped endpoint with HTTP 401.
6. THE Authorization_Layer SHALL default to denial for every endpoint that carries no explicit permission declaration, responding with HTTP 401 to an unauthenticated request and HTTP 403 to an authenticated request, and SHALL leave every stored record unchanged for each such denied request.
7. FOR ALL requests and all request bodies, the set of records a User can read or modify SHALL be a subset of the set permitted by that User's stored role, regardless of any field supplied in the request.
8. WHEN a Member requests a Payment or Invoice record whose Member is a different Member, THE API SHALL respond with HTTP 404 and SHALL exclude every attribute of that record from the response body.
9. WHERE the requesting User's role is `member`, THE Authorization_Layer SHALL permit read access to the MembershipPlan records of that Member's own Gym and to the SaasPlan catalogue.
10. WHERE the requesting User's role is `trainer`, THE Authorization_Layer SHALL permit write access only for creating a MemberProfile within that Trainer's own Gym and for updating records of Members assigned to that Trainer, and SHALL deny every other write request, including write requests targeting Payment and Invoice records, with HTTP 403.
11. WHERE the API exposes a Member-scoped record type other than Payment and Invoice, including BodyMetric and WorkoutLog, THE Authorization_Layer SHALL respond with HTTP 404 to a request from a Member for a record of that type whose Member is a different Member.

### Requirement 16: Payment Record Integrity

**User Story:** As a Gym_Owner, I want payment records that match what the gateway actually did, so that my revenue figures are trustworthy.

#### Acceptance Criteria

1. THE Payment model SHALL carry an Invoice foreign key, an amount, a currency code, a status, a gateway name, a gateway payment reference, a gateway order reference, an Idempotency_Key, a nullable paid timestamp, a created timestamp, and a Gym foreign key.
2. THE Payment model SHALL restrict status values to `pending`, `succeeded`, `failed`, `refunded`, and `cancelled`, replacing the current `paid` and `due` pair.
3. THE Payment model SHALL enforce uniqueness of the Idempotency_Key across the Platform.
4. THE Payment model SHALL enforce uniqueness of the gateway payment reference across the Platform WHERE that reference is present.
5. THE Payment model SHALL declare amount with at least 12 total digits and 2 decimal places, and SHALL require the amount to be greater than or equal to 0.01.
6. IF a request supplies a Payment amount less than or equal to 0, THEN THE Platform SHALL reject the request with a validation error naming the amount field.
7. THE Payment model SHALL replace the `auto_now_add` behaviour on the date field with an explicit, settable timestamp, so that historical Payments can be recorded with their true date.
8. THE Payment model SHALL default the currency code to `INR` and SHALL restrict values to ISO 4217 three-letter codes.
9. WHEN a Payment transitions to `succeeded`, THE Platform SHALL set the paid timestamp, and THE Platform SHALL reject any subsequent transition of that Payment to `pending`.

### Requirement 17: Payment Order Creation and Money Representation

**User Story:** As a Member, I want to pay my gym fee by UPI or card, so that I can renew my membership without handling cash.

#### Acceptance Criteria

1. WHEN an authenticated Payer requests payment of an open Invoice, THE Gateway_Adapter SHALL create a Payment_Gateway order for the Invoice amount and SHALL return the order reference and the public gateway key to the client.
2. THE Gateway_Adapter SHALL create a Payment record with status `pending` and a generated Idempotency_Key at the moment the Payment_Gateway order is created.
3. THE Gateway_Adapter SHALL convert amounts to the Payment_Gateway's minor-unit integer representation, expressed in paise for INR.
4. FOR ALL amounts expressed with exactly 2 decimal places, converting an amount to minor units and back SHALL yield the original amount, so that the conversion is a round trip.
5. IF an Invoice already has a Payment with status `succeeded`, THEN THE Platform SHALL reject a new order creation request for that Invoice with HTTP 409.
6. IF the Payment_Gateway returns an error or is unreachable during order creation, THEN THE Platform SHALL respond with HTTP 502, SHALL log the gateway error, and SHALL leave no Payment record in status `pending` for the failed attempt.
7. THE Platform SHALL support the payment methods UPI, card, and netbanking, and SHALL record the method reported by the Payment_Gateway on the Payment record.
8. THE Gateway_Adapter SHALL reject an order creation request WHERE the Invoice currency differs from the Payment_Gateway account currency.

### Requirement 18: Webhook Handling and Idempotency

**User Story:** As a Gym_Owner, I want a retried gateway notification to not double-count revenue, so that my ledger stays correct.

#### Acceptance Criteria

1. THE Webhook_Handler SHALL expose an unauthenticated HTTP endpoint that accepts Payment_Gateway event notifications.
2. WHEN a webhook request arrives, THE Webhook_Handler SHALL verify the request signature against the configured webhook secret before parsing the payload for business meaning.
3. IF the webhook signature is absent or does not verify, THEN THE Webhook_Handler SHALL respond with HTTP 400, SHALL log the rejection, and SHALL make no change to any Payment, Invoice, or Membership record.
4. WHEN a verified webhook event reports a successful payment, THE Webhook_Handler SHALL set the corresponding Payment status to `succeeded`, SHALL record the gateway payment reference, and SHALL mark the Invoice as settled.
5. WHEN a verified webhook event reports a failed payment, THE Webhook_Handler SHALL set the corresponding Payment status to `failed` and SHALL leave the Invoice open.
6. FOR ALL verified webhook events, processing the same event N times SHALL produce exactly one Payment record in a terminal status and SHALL produce the same Invoice settlement state as processing the event once.
7. WHEN a verified webhook event references a gateway order that matches no Payment record, THE Webhook_Handler SHALL respond with HTTP 200, SHALL record the event for reconciliation, and SHALL create no Payment record.
8. THE Webhook_Handler SHALL respond within 10 seconds for every request, so that the Payment_Gateway does not treat the endpoint as unavailable.
9. THE Webhook_Handler SHALL persist each verified event's gateway event identifier and SHALL treat a repeated identifier as already processed.
10. THE Platform SHALL exempt the webhook endpoint from CSRF enforcement and SHALL rely on signature verification as the sole authentication for that endpoint.

### Requirement 19: Invoices, Receipts, and GST

**User Story:** As a Gym_Owner, I want a numbered invoice for every charge, so that I can satisfy my accounting and tax obligations.

#### Acceptance Criteria

1. THE Platform SHALL provide an Invoice model with an invoice number, a Payer reference, a Gym foreign key, a nullable SaasSubscription reference, a nullable Membership reference, a taxable value, nullable CGST, SGST, and IGST amounts, a nullable HSN or SAC code, a total amount, a currency, a status, an issue date, and a due date.
2. THE Platform SHALL restrict Invoice status values to `open`, `settled`, `void`, and `refunded`.
3. THE Platform SHALL generate invoice numbers that are unique per Gym and per financial year, and SHALL generate numbers in a gapless ascending sequence within that scope.
4. WHERE the issuing party has a GSTIN recorded, THE Platform SHALL populate the tax fields and SHALL include the GSTIN and the HSN or SAC code on the Invoice.
5. WHERE the issuing party has no GSTIN recorded, THE Platform SHALL leave the tax fields null and SHALL issue the document as a plain receipt.
6. FOR ALL Invoices, the total amount SHALL equal the taxable value plus the sum of the populated CGST, SGST, and IGST amounts.
7. THE Platform SHALL treat an Invoice as immutable once its status is `settled`, and SHALL reject any request to change the amount, taxable value, or tax fields of a settled Invoice with HTTP 409.
8. WHEN an Invoice requires correction after settlement, THE Platform SHALL create a separate credit note record rather than altering the settled Invoice.
9. WHEN a Payment reaches status `succeeded`, THE Platform SHALL make a receipt document available to the Payer through the API.

### Requirement 20: Membership Period and Expiry

**User Story:** As a Gym_Owner, I want memberships to expire automatically when the paid period ends, so that unpaid members stop getting access without me tracking dates by hand.

#### Acceptance Criteria

1. THE Platform SHALL provide a Membership model with a MemberProfile reference, a MembershipPlan reference, a start date, a computed end date, and a status derived from those dates against the current date in the Gym's timezone, with values restricted to `upcoming` before the start date, `active` from the start date through the end date inclusive, and `expired` after the end date.
2. THE Platform SHALL compute the Membership end date as the start date plus MembershipPlan `duration_days` minus one day, so that the start-date-through-end-date inclusive period spans exactly `duration_days` days and the end date is never earlier than the start date.
3. IF a request creates a Membership whose MembershipPlan `duration_days` is less than 1 or greater than 3650, THEN THE Platform SHALL reject the request with a validation error naming the plan field and SHALL create no Membership record.
4. THE Platform SHALL derive the MemberProfile active state at request time from Membership start and end dates and Invoice settlement, and SHALL provide no manually settable active or status field on MemberProfile.
5. THE Platform SHALL treat a Member as active if and only if that Member holds a Membership whose status is `active` and which either references an Invoice whose status is `settled`, or references a MembershipPlan whose price equals 0 and has no associated Invoice.
6. WHERE a Member holds a Membership whose end date is later than or equal to the current date in the Gym's timezone, WHEN a renewal Invoice for that Member reaches status `settled`, THE Platform SHALL create a new Membership whose start date is the day after the latest such end date.
7. WHERE a Member holds no Membership whose end date is later than or equal to the current date in the Gym's timezone, WHEN a renewal Invoice for that Member reaches status `settled`, THE Platform SHALL create a new Membership whose start date is the settlement date expressed in the Gym's timezone.
8. WHILE a Member is not active, THE Authorization_Layer SHALL deny with HTTP 403 every request from that Member other than HTTP GET requests the Member is otherwise authorized to make and requests to the endpoints for viewing and paying that Member's own Invoices.
9. THE Platform SHALL replace the `auto_now_add` behaviour on MemberProfile `join_date` with an explicit, settable date, so that a Gym_Owner can record a Member's true join date during onboarding.
10. THE Platform SHALL expose on the Member's own profile endpoint the computed active state as a boolean and the end date of that Member's latest Membership, returning a null end date WHERE the Member holds no Membership.
11. IF a request would create a Membership for a Member whose start-date-through-end-date period overlaps the period of an existing Membership of that Member, THEN THE Platform SHALL reject the request with a validation error naming the start date field and SHALL create no Membership record.
12. WHEN a Member is assigned a different MembershipPlan while holding a Membership whose status is `active`, THE Platform SHALL leave that Membership's start date, end date, and Invoice unchanged, SHALL create the new Membership with a start date of the day after the existing end date, and SHALL apply no proration to either plan price.

### Requirement 21: SaaS Subscription Billing

**User Story:** As a Platform_Operator, I want gyms billed for their subscription, so that the platform earns revenue and unpaid gyms lose access.

#### Acceptance Criteria

1. THE Platform SHALL provide a SaasSubscription model with a Gym reference, a SaasPlan reference, a start date, a current period end date, a status, and a nullable gateway subscription reference.
2. THE Platform SHALL restrict SaasSubscription status values to `trialing`, `active`, `past_due`, and `cancelled`.
3. WHEN a Gym is created, THE Platform SHALL create a SaasSubscription in status `trialing` with a period end date set by a configured trial length.
4. WHEN a SaasSubscription period end date passes without a settled Invoice for the next period, THE Platform SHALL set the subscription status to `past_due`.
5. WHILE a Gym's SaasSubscription status is `past_due` or `cancelled`, THE Authorization_Layer SHALL permit that Gym's Users read access and SHALL deny write access to tenant-scoped endpoints other than the endpoints for viewing and paying SaaS Invoices.
6. WHEN a SaaS Invoice is settled, THE Platform SHALL set the subscription status to `active` and SHALL update the stored period end date to the previous period end date plus the SaasPlan billing interval.
7. THE Platform SHALL issue a SaaS Invoice to the Gym_Owner a configured number of days before each period end date.

### Requirement 22: Financial Audit Trail and Retention

**User Story:** As a Gym_Owner, I want financial history preserved and attributable, so that a mistake or a dispute can be reconstructed.

#### Acceptance Criteria

1. WHEN a Payment, Invoice, or Membership record is created or modified, THE Platform SHALL write an Audit_Record capturing the acting User, the timestamp, the record identifier, and the changed field values before and after the change.
2. THE Platform SHALL make Audit_Records append-only, and SHALL expose no API endpoint that updates or deletes an Audit_Record.
3. THE Platform SHALL apply Soft_Delete to Payment, Invoice, and Membership records, and SHALL expose no API endpoint that issues a hard delete for those records.
4. THE Platform SHALL exclude soft-deleted records from default querysets and SHALL include soft-deleted records in Gym_Owner financial reports WHERE the report explicitly requests them.
5. FOR ALL Members, the sum of the amounts of that Member's `succeeded` Payments SHALL equal the sum of the total amounts of that Member's `settled` Invoices, excluding refunded amounts.
6. FOR ALL Payments, the amount SHALL be greater than 0, so that no stored Payment reduces a Payer's recorded settlements.
7. WHEN a refund is recorded, THE Platform SHALL create a Payment record with status `refunded` referencing the original Payment, and SHALL leave the original Payment record unchanged apart from its status field.

### Requirement 23: Cardholder Data Scope

**User Story:** As a Platform_Operator, I want card data never to touch the Platform, so that PCI DSS scope stays minimal.

#### Acceptance Criteria

1. THE Platform SHALL store no primary account number, card expiry, cardholder name, CVV, or UPI PIN in any database field.
2. THE Platform SHALL exclude request bodies of payment endpoints from log output, and SHALL log only the gateway order reference, the gateway payment reference, the amount, the currency, and the status.
3. THE Platform SHALL collect payment credentials only through the Payment_Gateway's hosted or client-side collection flow, so that credentials do not transit the Platform's servers.
4. IF a request body submitted to a payment endpoint contains a field name matching a card-data field, THEN THE Platform SHALL reject the request with HTTP 400 and SHALL log the rejection without the field value.
5. THE Platform SHALL store the Payment_Gateway secret key and webhook secret only in environment variables, and SHALL exclude both values from log output and from API responses.

### Requirement 24: Minimum API Surface for Phase 1

**User Story:** As a developer, I want Phase 1 to expose only the endpoints needed for authentication and payment, so that the surface stays small enough to secure and test properly.

#### Acceptance Criteria

1. THE Platform SHALL install and configure a REST framework, since no REST framework is currently present in the project.
2. THE API SHALL expose endpoints for owner registration, login, token refresh, logout, email verification, password-reset request, and password-reset confirmation.
3. THE API SHALL expose endpoints for the authenticated User's own profile, for a Gym_Owner to invite and list Trainers and Members, for listing MembershipPlans of the requesting Gym, and for listing SaasPlans.
4. THE API SHALL expose endpoints for listing the requesting User's Invoices, creating a payment order for an Invoice, retrieving a receipt, and receiving Payment_Gateway webhooks.
5. THE Platform SHALL expose no API endpoints for workout tracking, body metrics, form checks, diet plans, attendance, equipment, or notifications in this phase.
6. WHEN a deployment is prepared, THE Platform SHALL verify that the registered URL patterns exclude every category named in criterion 5, and SHALL fail the deployment IF one or more of those categories is registered.
7. THE API SHALL apply rate limiting to the login, registration, and password-reset endpoints, at a request rate read from an environment variable.
8. THE Config_Loader SHALL treat 5 requests per minute per client as the minimum enforceable rate limit, and SHALL use that minimum WHERE the configured value is lower, so that a misconfigured value cannot lock legitimate users out.
9. THE API SHALL return errors in a single documented shape containing a machine-readable code and a human-readable message.

## Correctness Properties for Verification

These properties restate acceptance criteria in a form suitable for property-based testing, and are
carried forward into the design phase.

| Property | Statement | Source |
| --- | --- | --- |
| Tenant isolation | For any two distinct Gyms A and B, no request authenticated as a User of A reads or mutates any record belonging to B. | 3.4 |
| Role monotonicity | A User's effective permissions never exceed those granted by the stored role, for any request payload. | 15.7, 11.6 |
| Payment idempotency | Processing the same gateway event N times yields exactly one terminal Payment record and the same Invoice settlement state. | 18.6 |
| Ledger conservation | The sum of a Member's succeeded Payments equals the sum of that Member's settled Invoice totals, net of refunds. | 22.5 |
| Amount positivity | Every stored Payment amount is strictly greater than 0. | 16.6, 22.6 |
| Invoice total consistency | Invoice total equals taxable value plus the populated tax components. | 19.6 |
| Money round trip | Converting an amount to gateway minor units and back is the identity for 2-decimal amounts. | 17.4 |
| Token claim round trip | Decoding an issued access token yields exactly the User, role, and Gym claims encoded. | 13.7 |
| Expiry monotonicity | A Membership's computed end date is always greater than or equal to its start date. | 20.2 |
| Membership non-overlap | For any Member, no two of that Member's Memberships have overlapping date periods. | 20.11 |
| Active-iff-paid | A Member is active if and only if the current date lies within a settled or zero-price Membership period. | 20.5 |
| Seat limit | A Gym's Seat_Count, the number of that Gym's MemberProfile rows that are not soft-deleted, never exceeds that Gym's SaasPlan `max_members_allowed`, unless that value is null. | 5.4 |
| Role/profile agreement | Every User holds exactly the profile type corresponding to the stored role. | 12.4 |

Note on testing approach: tenant isolation, role monotonicity, money conversion, expiry computation,
seat limits, and ledger arithmetic vary meaningfully with input and are appropriate for property-based
testing against an in-memory or SQLite database. Webhook signature verification and gateway order
creation are tested with property-based tests against a mocked Payment_Gateway, plus a small number of
integration tests against the Payment_Gateway sandbox. Configuration and security-header requirements
are verified with single-execution checks rather than property tests, since the behaviour does not vary
with input.

## Known Tensions

Two conflicts survived the refinement pass. Both are recorded here rather than resolved, because each
needs a product decision that belongs in the design phase.

1. **MemberProfile updates without an active subscription.** Requirement 5.8 permits updates to existing
   MemberProfile records while a Gym has no SaasSubscription in status `trialing` or `active`, while
   Requirement 21.5 denies write access to tenant-scoped endpoints while a Gym's SaasSubscription status
   is `past_due` or `cancelled`. The two criteria disagree on whether a MemberProfile update is permitted
   in that state. Design must pick one rule and align both criteria to it.
2. **Staff account role and profile.** Requirement 11.2 requires `createsuperuser` to assign a role that
   is a member of the role choices but does not state which value, while the revised Requirement 12
   excludes accounts whose `is_staff` or `is_superuser` is true from the role-and-profile invariant. The
   Glossary carries no entry for a Platform_Operator staff account, so criteria 12.4, 12.6, and 12.7 lean
   on an undefined term. Adding a Glossary entry for the staff account and fixing the `createsuperuser`
   role value would make those criteria self-contained.

## Out of Scope / Future Phases

Deferred deliberately. Recorded here so the boundary is explicit, not because these are unimportant.

- The full REST API surface for workout tracking, workout splits, exercises, strength tiers, body metrics, attendance, diet plans, and equipment.
- Media upload handling, including Cloudinary integration for member photos, equipment images, and form-check video.
- Notifications and background jobs, including the Celery and Redis workers, fee-due reminders, and attendance alerts.
- The web frontend, including the django-htmx templates.
- Downloadable or installable app packaging. Phase 1 fixes the JWT token strategy so this phase does not require reworking authentication.
- AI workout generation, including the `WorkoutSplit.assigned_by = "ai"` path.
- Form-check video review workflow.
- Gateway-agnostic payment abstraction beyond Razorpay. Phase 1 targets Razorpay directly, while keeping the gateway name on the Payment record so a second gateway does not require a schema change.
