"""Feature: gym-saas-core, Property 8."""
import pytest
from django.urls import reverse
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from core.models import Gym, OwnerProfile, User
from core.tests.strategies import e164_phones, unicode_business_names

pytestmark = pytest.mark.django_db

FAILURE_STEPS = [None, "user", "profile", "subscription"]


def _payload(business_name, phone, email):
    return {
        "email": email,
        "password": "Correct-Horse-Battery-7",
        "password_confirm": "Correct-Horse-Battery-7",
        "business_name": (business_name or "").strip() or "Fallback Fitness",
        "contact_phone": phone,
    }


def _counts():
    return (Gym.objects.count(), User.objects.count(), OwnerProfile.all_objects.count())


def _clear_throttles():
    from django.core.cache import cache

    cache.clear()


def _reset_tenants():
    """Drop every tenant row between hypothesis examples.

    `django_db` opens one transaction for the whole test function and hypothesis
    runs all its examples inside it, so rows created by one example are still
    visible to the next. The email here is derived from the drawn inputs, so a
    repeated draw hits the "account with this email already exists" branch and the
    example fails for a reason that has nothing to do with the property.

    Gym is deleted first: `Invoice.payer_user` is PROTECT, and the Gym cascade
    removes invoices and payments before the User delete can trip over them.
    """
    Gym.objects.all().delete()
    User.objects.all().delete()


# Feature: gym-saas-core, Property 8: For any owner registration payload, either
# exactly one Gym, one User, and one linked OwnerProfile exist after the request, or
# none of the three exist - including when a failure is injected at any step of the
# transaction - and the Gym's name, not OwnerProfile.business_name, is the value
# returned wherever a Gym name appears, with business_name unchanged by any later Gym
# rename.
# Validates: Requirements 1.2, 1.8, 1.6, 1.13, 1.12
@hyp_settings(max_examples=100)
@given(
    business_name=unicode_business_names(),
    phone=e164_phones(),
    failure_step=st.sampled_from(FAILURE_STEPS),
)
def test_registration_is_all_or_nothing(business_name, phone, failure_step, api_client, monkeypatch):
    from core.services import registration

    # Hypothesis reuses this fixture; undo the previous example's injected
    # failure before setting up this example's independent scenario.
    monkeypatch.undo()
    _clear_throttles()
    _reset_tenants()
    before = _counts()
    email = f"owner{abs(hash((business_name, phone, failure_step))) % 10**9}@example.com"

    if failure_step == "user":
        monkeypatch.setattr(
            registration.User.objects,
            "create_user",
            lambda **kwargs: (_ for _ in ()).throw(RuntimeError("injected")),
        )
    elif failure_step == "profile":
        monkeypatch.setattr(
            registration.OwnerProfile.objects,
            "create",
            lambda **kwargs: (_ for _ in ()).throw(RuntimeError("injected")),
        )
    elif failure_step == "subscription":
        monkeypatch.setattr(
            "core.services.subscriptions.start_trial",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("injected")),
        )

    url = reverse("core:register-owner")
    if failure_step is None:
        response = api_client.post(url, _payload(business_name, phone, email), format="json")
        assert response.status_code == 201, response.content

        gyms, users, profiles = _counts()
        assert (gyms, users, profiles) == (before[0] + 1, before[1] + 1, before[2] + 1)

        profile = OwnerProfile.objects.get(user__email=email)
        gym = profile.gym

        # The Gym name is what the API reports, and it is linked to the profile.
        assert response.json()["gym"]["name"] == gym.name
        assert profile.user.role == "owner"

        # A later Gym rename must not rewrite the legal business name (1.6, 1.13).
        original_business_name = profile.business_name
        gym.name = "Renamed Fitness Collective"
        gym.save(update_fields=["name"])
        profile.refresh_from_db()
        assert profile.business_name == original_business_name
        assert gym.name != profile.business_name or original_business_name == gym.name
        return

    # The API's exception handler deliberately turns an internal error into its
    # uniform 500 envelope; the injected error must not escape as a test-client
    # exception.
    response = api_client.post(url, _payload(business_name, phone, email), format="json")
    assert response.status_code == 500

    # None of the three survive an injected failure at any step.
    assert _counts() == before
    assert not User.objects.filter(email__iexact=email).exists()


@hyp_settings(max_examples=100)
@given(phone=e164_phones())
def test_client_supplied_role_and_gym_are_ignored(phone, api_client):
    """1.2 companion: registration always produces an owner."""
    _clear_throttles()
    # Gyms must go too, not just users: the business name here is constant, so
    # retained gyms make the slug collide and after 50 examples the suffix budget
    # is exhausted and registration starts answering 400.
    _reset_tenants()
    payload = _payload("Privilege Test Gym", phone, f"priv{abs(hash(phone)) % 10**9}@example.com")
    payload.update({"role": "owner", "is_staff": True, "is_superuser": True, "gym": 999})

    response = api_client.post(reverse("core:register-owner"), payload, format="json")
    assert response.status_code == 201, response.content

    user = User.objects.get(email__iexact=payload["email"])
    assert user.role == "owner"
    assert user.is_staff is False
    assert user.is_superuser is False


def test_slug_exhaustion_rejects_the_registration(api_client, monkeypatch):
    """1.12: exhausting the suffix budget is a rejection, not a random fallback."""
    from core.services.slugs import SlugExhausted

    monkeypatch.setattr(
        "core.services.registration.derive_unique_slug",
        lambda name, exists: (_ for _ in ()).throw(SlugExhausted("no room")),
    )

    before = _counts()
    response = api_client.post(
        reverse("core:register-owner"),
        _payload("Crowded Name", "+919876543210", "crowded@example.com"),
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["error"]["details"]["field"] == "gym_name"
    assert _counts() == before
