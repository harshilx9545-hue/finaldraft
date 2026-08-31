"""Plain-function factories.

No factory_boy: the dependency graph here is shallow and the interesting part is
that some objects must be built through the *service* layer rather than the ORM.
`make_member` goes through `create_member_atomically` because that is where the seat
and subscription gates live, and a factory that bypassed them would let a test pass
against a rule the API actually enforces.

Every factory takes a `gym` explicitly. Defaulting it would make cross-tenant tests
read as if tenancy were incidental, when it is the thing under test.
"""
from __future__ import annotations

import datetime
import itertools
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from core.models import (
    Equipment,
    Gym,
    Invoice,
    Membership,
    MembershipPlan,
    MemberProfile,
    Payment,
    SaasPlan,
    SaasSubscription,
    StrengthStandard,
    TrainerProfile,
)

User = get_user_model()

_counter = itertools.count(1)

DEFAULT_PASSWORD = "Correct-Horse-Battery-7"


def unique(prefix="x"):
    return f"{prefix}{next(_counter)}"


def unique_email(prefix="user"):
    return f"{unique(prefix)}@example.com"


def unique_phone():
    # +91 followed by 10 digits, kept inside E.164's 15-digit ceiling.
    return f"+91{9000000000 + next(_counter)}"


# ============ TENANT ============

def make_gym(
    *,
    name=None,
    slug=None,
    timezone_name="Asia/Kolkata",
    gstin=None,
    is_active=True,
    with_subscription=True,
    saas_plan=None,
    max_members=None,
    subscription_status="active",
):
    """A Gym, by default with a live subscription so writes are permitted.

    `with_subscription=False` is the fixture for the 402 path, and
    `subscription_status="past_due"` for the read-only path.
    """
    name = name or f"Iron Pit {unique('')}"
    gym = Gym.objects.create(
        name=name,
        slug=slug or f"iron-pit-{unique('')}".lower(),
        contact_email=unique_email("gym"),
        contact_phone=unique_phone(),
        timezone=timezone_name,
        gstin=gstin,
        is_active=is_active,
    )
    if with_subscription:
        plan = saas_plan or make_saas_plan(max_members_allowed=max_members)
        make_subscription(gym, plan, status=subscription_status)
    return gym


def make_saas_plan(
    *,
    name=None,
    price="999.00",
    currency="INR",
    billing_interval_months=1,
    max_members_allowed=None,
    is_active=True,
):
    return SaasPlan.objects.create(
        name=name or f"Tier {unique('')}",
        price=Decimal(price),
        currency=currency,
        billing_interval_months=billing_interval_months,
        max_members_allowed=max_members_allowed,
        is_active=is_active,
    )


def make_subscription(gym, plan=None, *, status="active", start=None, period_end=None):
    start = start or gym.today()
    return SaasSubscription.objects.create(
        gym=gym,
        plan=plan or make_saas_plan(),
        status=status,
        start_date=start,
        current_period_end=period_end or start + datetime.timedelta(days=30),
    )


# ============ USERS ============

def make_user(*, role="member", email=None, password=DEFAULT_PASSWORD, phone=None, **extra):
    """A bare User with no profile. Use `make_owner`/`make_trainer`/`make_member`
    when the test needs a usable tenant identity.
    """
    return User.objects.create_user(
        email=email or unique_email(role),
        password=password,
        phone=phone,
        role=role,
        **extra,
    )


def make_staff(*, email=None, password=DEFAULT_PASSWORD, superuser=True):
    """A platform operator: staff, no profile, no Gym (D6).

    Its `role` stays at the model default, which is deliberate and is what
    requirement 11.2 permits.
    """
    return User.objects.create_superuser(
        email=email or unique_email("staff"), password=password
    ) if superuser else User.objects.create_user(
        email=email or unique_email("staff"), password=password, is_staff=True
    )


def make_owner(gym, *, email=None, password=DEFAULT_PASSWORD, business_name=None):
    from core.models import OwnerProfile

    user = make_user(role="owner", email=email, password=password)
    profile = OwnerProfile.objects.create(
        user=user, gym=gym, business_name=business_name or gym.name
    )
    return profile


def make_trainer(gym, *, email=None, password=DEFAULT_PASSWORD, specialization=""):
    user = make_user(role="trainer", email=email, password=password)
    return TrainerProfile.objects.create(
        user=user, gym=gym, specialization=specialization
    )


def make_member(
    gym,
    *,
    email=None,
    password=DEFAULT_PASSWORD,
    plan=None,
    trainer=None,
    join_date=None,
    through_service=True,
    goal="",
):
    """A member, created through the seat service by default.

    `through_service=False` inserts directly and is only for tests that need to
    construct a state the gates would refuse (for example, seeding a Gym already
    over its limit to check that a *restore* is refused).
    """
    if through_service:
        from core.services.seats import create_member_atomically

        return create_member_atomically(
            gym,
            email=email or unique_email("member"),
            password=password,
            plan=plan,
            trainer=trainer,
            join_date=join_date,
            goal=goal,
        )

    user = make_user(role="member", email=email, password=password)
    return MemberProfile.objects.create(
        user=user,
        gym=gym,
        plan=plan,
        trainer=trainer,
        join_date=join_date or gym.today(),
        goal=goal,
    )


# ============ PLANS AND MEMBERSHIPS ============

def make_membership_plan(
    gym, *, name=None, price="1500.00", currency="INR", duration_days=30, **extra
):
    return MembershipPlan.objects.create(
        gym=gym,
        name=name or f"Monthly {unique('')}",
        price=Decimal(price),
        currency=currency,
        duration_days=duration_days,
        **extra,
    )


def make_membership(profile, plan=None, *, start=None, through_service=False):
    """A Membership. Direct by default because most tests want a known period.

    `through_service=True` also issues the Invoice for a priced plan, which is what
    the renewal and active-state tests need.
    """
    plan = plan or make_membership_plan(profile.gym)
    start = start or profile.gym.today()

    if through_service:
        from core.services.memberships import create_membership

        return create_membership(profile, plan, start=start)["membership"]

    membership = Membership(member=profile, plan=plan, start_date=start)
    membership.save()
    return membership


# ============ MONEY ============

def make_invoice(
    gym,
    payer_user,
    *,
    taxable="1500.00",
    membership=None,
    saas_subscription=None,
    status="open",
    through_service=True,
    currency="INR",
    issue_date=None,
):
    """An Invoice, numbered through the sequence service by default.

    Direct construction skips numbering, which would break the gapless guarantee, so
    `through_service=False` supplies its own number and is only for shape tests.
    """
    if through_service:
        from core.services.invoicing import issue_invoice

        if membership is None and saas_subscription is None:
            saas_subscription = getattr(gym, "subscription", None)
        invoice = issue_invoice(
            gym=gym,
            payer_user=payer_user,
            taxable_value=Decimal(taxable),
            membership=membership,
            saas_subscription=saas_subscription,
            currency=currency,
            issue_date=issue_date,
        )
        if status != "open":
            invoice.status = status
            invoice.save(update_fields=["status"])
        return invoice

    issue_date = issue_date or gym.today()
    return Invoice.objects.create(
        gym=gym,
        payer_user=payer_user,
        membership=membership,
        saas_subscription=saas_subscription,
        number=f"{gym.slug}/2025-26/{next(_counter):05d}",
        financial_year="2025-26",
        sequence_no=next(_counter),
        taxable_value=Decimal(taxable),
        total_amount=Decimal(taxable),
        currency=currency,
        status=status,
        issue_date=issue_date,
        due_date=issue_date + datetime.timedelta(days=7),
    )


def make_payment(
    invoice,
    *,
    amount=None,
    status="pending",
    order_ref=None,
    payment_ref=None,
    method=None,
):
    return Payment.objects.create(
        invoice=invoice,
        gym=invoice.gym,
        amount=amount if amount is not None else invoice.total_amount,
        currency=invoice.currency,
        status=status,
        gateway="razorpay",
        gateway_order_ref=order_ref or f"order_{unique('')}",
        gateway_payment_ref=payment_ref,
        idempotency_key=f"idem-{unique('')}",
        method=method,
        paid_at=timezone.now() if status == "succeeded" else None,
        recorded_on=invoice.gym.today(),
    )


# ============ MISCELLANEOUS TENANT-SCOPED ROWS ============

def make_equipment(gym, *, name=None, category="cardio"):
    return Equipment.objects.create(
        gym=gym, name=name or f"Treadmill {unique('')}", category=category
    )


def make_strength_standard(gym=None, *, exercise_name=None, gender="m"):
    """`gym=None` produces the platform-wide default row every tenant can read (2.2)."""
    return StrengthStandard.objects.create(
        gym=gym,
        exercise_name=exercise_name or f"Bench {unique('')}",
        gender=gender,
        ratio_beginner=Decimal("0.50"),
        ratio_novice=Decimal("0.75"),
        ratio_intermediate=Decimal("1.00"),
        ratio_advanced=Decimal("1.50"),
        ratio_elite=Decimal("2.00"),
    )


# ============ COMPOSITE FIXTURES ============

def make_tenant(*, max_members=None, subscription_status="active", gstin=None, timezone_name="Asia/Kolkata"):
    """A whole tenant: Gym, owner, trainer, member, plan. The common starting point."""
    gym = make_gym(
        max_members=max_members,
        subscription_status=subscription_status,
        gstin=gstin,
        timezone_name=timezone_name,
    )
    owner = make_owner(gym)
    trainer = make_trainer(gym)
    plan = make_membership_plan(gym)
    member = make_member(gym, plan=plan, trainer=trainer)
    return {
        "gym": gym,
        "owner": owner,
        "trainer": trainer,
        "member": member,
        "plan": plan,
    }


def authenticate(api_client, user):
    """Attach a real access token, so token claims are exercised end to end."""
    from core.services.auth_tokens import issue_tokens

    tokens = issue_tokens(user)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return tokens
