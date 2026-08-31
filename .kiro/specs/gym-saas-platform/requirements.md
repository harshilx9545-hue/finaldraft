# Requirements Document

## Introduction

This feature converts the existing early-stage Django gym management backend (project `gymapp`, single app `core`, 16 models, empty views, no API, no auth beyond Django admin, development-only settings) into a production-ready, monetizable multi-gym SaaS product delivered as an installable web application, with downloadable Android and desktop builds as a later phase.

**Business model decisions (confirmed with the product owner):**

- The Platform is a **multi-gym SaaS**. Gym owners are the paying customers. Each Gym is a tenant whose data is isolated from every other Gym.
- Member membership fees are **recorded** in the Platform (cash, UPI, card, bank transfer marked by Gym staff). The Platform does not hold or settle member money in Phase 1, which keeps the Platform out of payment-facilitator and settlement scope. Online member collection using each Gym's own gateway account is Phase 2.
- Billing runs through **Razorpay** for India in INR, behind a gateway abstraction so a second provider (for example Stripe) can be added without changing business logic.
- Delivery is an **installable Progressive Web App** in Phase 1. A sideloadable Android package and a Windows desktop installer are Phase 2.
- The existing `db.sqlite3` contains no data worth preserving. Migrations are recreated from a clean slate.

**Phasing:** Requirements 1 through 18 are Phase 1, the monetizable slice. Requirements 19 through 23 are Phase 2. Every requirement is individually verifiable and carries its phase label.

**Existing-code corrections captured here:** the bogus `MAILERS` setting (not a Django setting, so email is currently inert), hardcoded `SECRET_KEY`, `DEBUG = True`, empty `ALLOWED_HOSTS`, sqlite database, missing `STATIC_ROOT` and media configuration, missing `default_auto_field`, `User.role` with no default, `auto_now_add` on `Payment.date`, `WorkoutLog.date`, `BodyMetric.date`, `Attendance.check_in_time` and `FormCheck.date` (which blocks backfill and historical records), `StrengthStandard.tier_for_ratio` raising `TypeError` when compared against a `float`, absence of any tenant entity, and absence of role-based authorization.

## Glossary

- **Platform**: The complete hosted software system, comprising the Django backend, the Web_App, and supporting services.
- **Gym**: The tenant entity. A new model that owns Members, Trainers, Equipment, Membership_Plans, Attendance records, and Member Payments.
- **Owner**: A User with role `owner`. Owns one or more Gyms and is the Platform's paying customer.
- **Trainer**: A User with role `trainer`, associated with exactly one Gym.
- **Member**: A User with role `member`, associated with exactly one Gym.
- **Platform_Admin**: A User with Django `is_staff` and `is_superuser` set to true, operating the Platform itself, not a tenant.
- **Subscription_Tier**: A Platform-level, Owner-facing paid tier (for example Starter, Growth, Pro) defining a monthly or yearly price and a `max_active_members` cap per Gym. Distinct from Membership_Plan.
- **Platform_Subscription**: A record of one Gym's current Subscription_Tier, billing period, and state.
- **Membership_Plan**: A Gym-scoped, Member-facing plan (name, price, duration_days, includes_trainer, includes_diet). This is the renamed and re-scoped replacement for the existing ambiguous `Plan` model.
- **Membership**: The relationship between a Member and a Membership_Plan, carrying `start_date`, `expiry_date`, and derived state.
- **Config_Loader**: The settings module component that reads configuration from environment variables.
- **API**: The REST interface exposed by the backend and consumed by the Web_App and every Installable_Client.
- **Auth_Service**: The backend component handling registration, login, logout, token issue and refresh, email verification, and password reset.
- **Authorization_Layer**: The backend component enforcing role and tenant permissions on every API request.
- **Tenant_Scope_Filter**: The backend component restricting every queryset to the requesting User's Gym.
- **Billing_Service**: The backend component managing Platform_Subscriptions, invoices, and gateway interaction for Owner billing.
- **Payment_Gateway_Adapter**: The provider-agnostic interface the Billing_Service calls. Razorpay is the first concrete implementation.
- **Membership_Service**: The backend component computing Membership expiry and enforcing Subscription_Tier member caps.
- **Attendance_Service**: The backend component recording Member check-in and check-out.
- **Strength_Tier_Calculator**: The backend component mapping a lifted-weight-to-bodyweight ratio to a tier name using Strength_Standard rows.
- **Strength_Standard**: The reference table of per-exercise, per-gender bodyweight ratios for each tier.
- **Media_Service**: The backend component handling file upload, storage, and signed access for images and videos.
- **Notification_Service**: The backend component composing and dispatching notifications over email, SMS, and in-app channels.
- **Scheduler**: The background task system running periodic and deferred jobs.
- **Web_App**: The browser-delivered user interface, installable as a Progressive Web App.
- **Installable_Client**: Any packaged distribution of the user interface installed on a device: the installed Progressive Web App, the Android package, or the Windows desktop application.
- **Marketing_Site**: The public, unauthenticated pages describing the product, pricing, and download links.
- **Test_Suite**: The automated tests, comprising example-based tests and property-based tests.
- **Logger**: The structured logging subsystem.
- **Deployment_Pipeline**: The automated build, check, test, and release process.
- **Data_Rights_Service**: The backend component producing data exports and processing account deletion requests.
- **Audit_Log**: An append-only record of mutations to financially and compliance relevant data.
- **Idempotency_Key**: A caller-supplied unique string that makes a repeated write request produce the original result instead of a duplicate record.

## Requirements

### Requirement 1: Environment-Based Configuration (Phase 1)

**User Story:** As an operator, I want every environment-specific and secret value to come from the environment, so that the same code artifact runs safely in development, staging, and production.

#### Acceptance Criteria

1. THE Config_Loader SHALL read `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `DATABASE_URL`, `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_PORT`, `DEFAULT_FROM_EMAIL`, `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, `REDIS_URL`, and `MEDIA_STORAGE_BACKEND` from environment variables.
2. IF the `SECRET_KEY` environment variable is absent or empty when `DEBUG` resolves to false, THEN THE Config_Loader SHALL raise `ImproperlyConfigured` during startup and THE Platform SHALL exit with a non-zero status code.
3. WHERE the `DEBUG` environment variable is absent, THE Config_Loader SHALL resolve `DEBUG` to false.
4. THE Config_Loader SHALL parse `ALLOWED_HOSTS` as a comma-separated list of hostnames.
5. IF `DEBUG` resolves to false AND `ALLOWED_HOSTS` resolves to an empty list, THEN THE Config_Loader SHALL raise `ImproperlyConfigured` during startup.
6. THE Config_Loader SHALL configure PostgreSQL version 14 or later as the default database engine from `DATABASE_URL`.
7. THE Config_Loader SHALL define `STATIC_ROOT`, `STATIC_URL`, `MEDIA_ROOT`, and `MEDIA_URL`.
8. THE Config_Loader SHALL define `EMAIL_BACKEND` and the SMTP settings that Django reads, replacing the non-functional `MAILERS` dictionary present in the current settings module.
9. WHILE `DEBUG` resolves to false, THE Platform SHALL set `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, and `SECURE_HSTS_INCLUDE_SUBDOMAINS` to true, `SECURE_HSTS_SECONDS` to 31536000, and `X_FRAME_OPTIONS` to `DENY`.
10. WHEN `manage.py check --deploy` runs against production configuration values, THE Platform SHALL report zero issues at `WARNING` severity or higher.
11. THE Platform SHALL provide a `.env.example` file listing every environment variable name from criterion 1 with placeholder values and no real secret values.
12. THE Platform SHALL exclude `.env` files, `db.sqlite3`, and media files from version control.

### Requirement 2: Multi-Tenancy and Tenant Data Isolation (Phase 1)

**User Story:** As a gym owner, I want my gym's data to be invisible and unreachable to every other gym on the platform, so that I can trust the platform with my business records.

#### Acceptance Criteria

1. THE Platform SHALL define a `Gym` model with fields `owner` (foreign key to OwnerProfile), `name`, `slug`, `address`, `city`, `country_code`, `timezone`, `currency_code`, `is_active`, and `created_at`.
2. THE Platform SHALL define a non-nullable `gym` foreign key on the MemberProfile, TrainerProfile, Membership_Plan, Equipment, Attendance, Payment, DietPlan, WorkoutSplit, FormCheck, and Notification models.
3. THE Platform SHALL enforce uniqueness of `Gym.slug` across the Platform.
4. WHEN an authenticated User with role `owner`, `trainer`, or `member` requests any tenant-scoped API collection, THE Tenant_Scope_Filter SHALL return only records whose `gym` matches the requesting User's Gym.
5. WHEN an authenticated User requests a tenant-scoped API record belonging to a Gym other than the requesting User's Gym, THE API SHALL respond with HTTP status 404.
6. WHEN an authenticated User creates a tenant-scoped record, THE Platform SHALL set the record's `gym` from the requesting User's Gym and SHALL ignore any `gym` value supplied in the request body.
7. IF a tenant-scoped record is saved with a `gym` value that differs from the `gym` of the record's referenced MemberProfile or TrainerProfile, THEN THE Platform SHALL raise `ValidationError` and SHALL reject the save.
8. THE Platform SHALL scope Django admin querysets for Owner users to the Owner's own Gyms.
9. THE Strength_Standard model SHALL remain Platform-wide and unscoped, because strength ratios are reference data shared by every Gym.

### Requirement 3: User, Role, and Profile Data Integrity (Phase 1)

**User Story:** As a developer, I want the user and profile models to reject invalid states at the database and validation layer, so that no code path can create a user whose role is meaningless.

#### Acceptance Criteria

1. THE Platform SHALL define `User.role` with a default value of `member` and SHALL constrain stored values to `owner`, `trainer`, `member`, or `platform_admin`.
2. WHEN `createsuperuser` creates a User, THE Platform SHALL set that User's `role` to `platform_admin`.
3. THE Platform SHALL enforce uniqueness of `User.email` across the Platform, case-insensitively.
4. THE Platform SHALL require a non-empty `User.email` for every User.
5. WHEN a User with role `member` is saved, THE Platform SHALL require exactly one associated MemberProfile.
6. WHEN a User with role `trainer` is saved, THE Platform SHALL require exactly one associated TrainerProfile.
7. WHEN a User with role `owner` is saved, THE Platform SHALL require exactly one associated OwnerProfile.
8. IF a `User.phone` value is submitted that does not match the E.164 format (a plus sign followed by 8 to 15 digits), THEN THE Platform SHALL raise `ValidationError` and SHALL reject the save.
9. THE Platform SHALL declare `default_auto_field` as `django.db.models.BigAutoField` on the `core` application configuration.
10. THE Platform SHALL replace the existing `core/migrations/0001_initial.py` with a regenerated initial migration reflecting every model change in this document, and `makemigrations --check --dry-run` SHALL report no pending model changes.

### Requirement 4: Membership Plan and Membership Lifecycle (Phase 1)

**User Story:** As a gym owner, I want memberships to expire automatically on the correct date, so that I stop giving free access to members who have not renewed.

#### Acceptance Criteria

1. THE Platform SHALL rename the existing `Plan` model to `Membership_Plan`, scope each Membership_Plan to one Gym, and remove the `max_members_allowed` field from Membership_Plan because the member cap belongs to Subscription_Tier.
2. THE Platform SHALL enforce uniqueness of Membership_Plan `name` within one Gym.
3. THE Platform SHALL constrain `Membership_Plan.price` to values greater than or equal to 0 and `Membership_Plan.duration_days` to values from 1 to 3650 inclusive.
4. THE Platform SHALL define a `Membership` model with fields `member`, `plan`, `start_date`, `expiry_date`, `is_current`, and `created_at`, replacing the direct `MemberProfile.plan` foreign key as the record of what a Member has purchased.
5. WHEN a Membership is created, THE Membership_Service SHALL compute `expiry_date` as `start_date` plus the Membership_Plan `duration_days`.
6. WHILE the current date in the Gym's timezone is later than a Membership's `expiry_date`, THE Membership_Service SHALL report that Membership's state as `expired`.
7. WHILE the current date in the Gym's timezone falls within a Membership's `start_date` through `expiry_date` inclusive, THE Membership_Service SHALL report that Membership's state as `active`.
8. WHEN a Member renews, THE Membership_Service SHALL create a new Membership record, SHALL set `is_current` to false on the previous Membership, and SHALL preserve the previous Membership as history.
9. THE Platform SHALL permit at most one Membership per Member with `is_current` set to true.
10. WHEN a Membership is created with a `start_date` earlier than the current date, THE Membership_Service SHALL accept the record, so that Gym staff can enter historical memberships.
11. THE Platform SHALL derive `MemberProfile` active state from the current Membership rather than from a manually edited status field.

### Requirement 5: Attendance Correctness (Phase 1)

**User Story:** As a gym owner, I want attendance records to be free of duplicate open check-ins and impossible time ranges, so that my attendance reports are trustworthy.

#### Acceptance Criteria

1. THE Platform SHALL replace `Attendance.check_in_time` `auto_now_add` behaviour with a caller-supplied value that defaults to the current time.
2. WHEN a Member check-in is requested AND that Member has an existing Attendance record whose `check_out_time` is null, THE Attendance_Service SHALL respond with HTTP status 409 and SHALL create no new record.
3. WHEN a Member check-out is requested AND that Member has no Attendance record whose `check_out_time` is null, THE Attendance_Service SHALL respond with HTTP status 409.
4. IF an Attendance record is saved with a `check_out_time` earlier than or equal to its `check_in_time`, THEN THE Platform SHALL raise `ValidationError` and SHALL reject the save.
5. IF an Attendance record is saved with a `check_in_time` later than the current time, THEN THE Platform SHALL raise `ValidationError` and SHALL reject the save.
6. THE Platform SHALL enforce, through a database constraint, that at most one Attendance record per Member has a null `check_out_time`.
7. WHEN a Member whose current Membership state is `expired` requests check-in, THE Attendance_Service SHALL create the Attendance record and SHALL include a `membership_expired` flag set to true in the response, so that front-desk staff see the lapse without being blocked.
8. THE Platform SHALL index Attendance on `(gym, check_in_time)` to keep date-range attendance reports responsive.

### Requirement 6: Workout Logging and Strength Tier Calculation (Phase 1)

**User Story:** As a member, I want to log past workouts and see a correct strength tier, so that I can track progress over time.

#### Acceptance Criteria

1. THE Platform SHALL replace `WorkoutLog.date` `auto_now_add` behaviour with a caller-supplied date that defaults to the current date in the Gym's timezone.
2. IF a WorkoutLog is saved with a `date` later than the current date in the Gym's timezone, THEN THE Platform SHALL raise `ValidationError` and SHALL reject the save.
3. THE Platform SHALL constrain `WorkoutLog.weight` to values greater than 0 and less than or equal to 1000, `WorkoutLog.reps` to values from 1 to 1000 inclusive, and `WorkoutLog.sets` to values from 1 to 100 inclusive.
4. THE Platform SHALL define a `set_number` field on WorkoutLog and SHALL enforce uniqueness of `(member, exercise, date, set_number)`.
5. WHEN a WorkoutLog is saved, THE Strength_Tier_Calculator SHALL compute `calculated_tier` from the ratio of `weight` to the Member's most recent `BodyMetric.weight_kg` and SHALL store the result, so that `calculated_tier` is never set by an untrusted caller.
6. IF no BodyMetric exists for the Member when a WorkoutLog is saved, THEN THE Strength_Tier_Calculator SHALL store an empty `calculated_tier`.
7. IF no Strength_Standard row matches the Exercise name and the Member's gender when a WorkoutLog is saved, THEN THE Strength_Tier_Calculator SHALL store an empty `calculated_tier`.
8. THE Strength_Tier_Calculator SHALL accept ratio inputs of type `int`, `float`, and `Decimal` and SHALL return one of `beginner`, `novice`, `intermediate`, `advanced`, or `elite`, correcting the current `tier_for_ratio` implementation that raises `TypeError` when a `float` is compared with a `Decimal` field.
9. IF a Strength_Standard row is saved whose five ratio values are not in non-decreasing order from `ratio_beginner` through `ratio_elite`, THEN THE Platform SHALL raise `ValidationError` and SHALL reject the save.
10. THE Platform SHALL define a `gender` field on MemberProfile with values `m`, `f`, or `unspecified`, because the Strength_Standard lookup requires gender and MemberProfile currently has no such field.
11. THE Platform SHALL replace the comma-separated `WorkoutSplit.muscle_groups` character field with a normalized many-to-many relation to a `MuscleGroup` reference table.

### Requirement 7: Body Metric Integrity (Phase 1)

**User Story:** As a member, I want to enter measurements for past dates with sane bounds, so that my progress history is complete and free of typos.

#### Acceptance Criteria

1. THE Platform SHALL replace `BodyMetric.date` `auto_now_add` behaviour with a caller-supplied date that defaults to the current date in the Gym's timezone.
2. THE Platform SHALL constrain `BodyMetric.height_cm` to values from 50 to 260 inclusive and `BodyMetric.weight_kg` to values from 20 to 400 inclusive.
3. THE Platform SHALL constrain each of `BodyMetric.chest_cm`, `BodyMetric.waist_cm`, and `BodyMetric.arms_cm`, when supplied, to values from 10 to 300 inclusive.
4. THE Platform SHALL enforce uniqueness of `(member, date)` on BodyMetric.
5. IF a BodyMetric is saved with a `date` later than the current date in the Gym's timezone, THEN THE Platform SHALL raise `ValidationError` and SHALL reject the save.
6. WHEN a Member requests body metric history, THE API SHALL return records ordered by `date` descending.
