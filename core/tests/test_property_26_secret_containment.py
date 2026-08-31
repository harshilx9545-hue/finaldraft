"""Feature: gym-saas-core, Property 26.

Two containment rules, checked against the actual log stream rather than by reading
the code:

* A card-data field name anywhere in a payment body is refused, and the *value*
  never reaches a log record. The field name may be logged — a client needs to know
  which key offended — but the number must not.
* The gateway secret key and webhook secret appear in no response body and no log
  record, for any payment interaction.

`caplog` is set to capture the whole tree at DEBUG so nothing the platform emits is
outside the assertion, and the stored `WebhookEvent.raw_payload` is checked too:
a payload persisted with card keys intact would be a durable leak rather than a
transient one.
"""
import json
import logging

import pytest
from django.test import override_settings
from django.urls import reverse
from hypothesis import given, settings
from hypothesis import strategies as st
from rest_framework.test import APIClient

from core.models import WebhookEvent
from core.services.gateway import EVENT_PAYMENT_CAPTURED, get_adapter
from core.services.payments import (
    create_order,
    find_card_data_field,
    order_response,
    strip_card_data,
)
from core.tests import factories
from core.tests.fakes import (
    FAKE_KEY_SECRET,
    FAKE_WEBHOOK_SECRET,
    build_event_payload,
    signed_body,
)
from core.tests.strategies import (
    card_data_field_names,
    nested_card_data_bodies,
)

pytestmark = pytest.mark.django_db

#: A deliberately fake test card number. Its only job is to be searched for.
CARD_VALUE = "4111111111111111"

#: Values that must never appear in a log record or a response body (23.5).
SECRETS = (FAKE_KEY_SECRET, FAKE_WEBHOOK_SECRET)


def paying_world():
    from core.services.memberships import create_membership

    gym = factories.make_gym()
    factories.make_owner(gym)
    plan = factories.make_membership_plan(gym, price="1500.00", duration_days=30)
    member = factories.make_member(gym, plan=plan)
    result = create_membership(member, plan, start=gym.today())

    client = APIClient()
    factories.authenticate(client, member.user)
    return {
        "gym": gym,
        "member": member,
        "invoice": result["invoice"],
        "client": client,
    }


def captured_text(caplog):
    """Everything the platform logged during the test, as one searchable string."""
    return "\n".join(
        [record.getMessage() for record in caplog.records]
        + [str(record.args) for record in caplog.records]
    )


# Feature: gym-saas-core, Property 26: For any payment-endpoint request body containing
# a card-data field name at any nesting depth, the request is refused with 400 and the
# field value appears in no log record; and for any payment interaction, the
# Payment_Gateway secret key and webhook secret appear in no response body and no log
# record.
# Validates: Requirements 23.4, 23.2, 23.5
@settings(max_examples=100)
@given(body=nested_card_data_bodies())
def test_card_data_at_any_depth_is_refused_without_logging_the_value(body, caplog):
    world = paying_world()
    url = reverse("core:invoice-pay", kwargs={"pk": world["invoice"].pk})

    with caplog.at_level(logging.DEBUG):
        response = world["client"].post(url, body, format="json")

    assert response.status_code == 400, response.data
    envelope = response.json()["error"]
    assert envelope["code"] == "CARD_DATA_REJECTED"
    assert envelope["message"]
    # The offending key is named so the client can fix the request (23.4).
    assert envelope["details"]["field"]

    logged = captured_text(caplog)
    assert CARD_VALUE not in logged, "a card value reached the log"
    assert CARD_VALUE not in json.dumps(response.json())

    # Nothing was created: the screen runs before any row is written.
    from core.models import Payment

    assert not Payment.all_objects.filter(invoice=world["invoice"]).exists()


@settings(max_examples=100)
@given(field=card_data_field_names(), depth=st.integers(min_value=0, max_value=4))
def test_the_card_data_screen_finds_the_key_at_every_depth(field, depth):
    """Pure check of the detector, so the API test above cannot pass by accident."""
    body = {field: CARD_VALUE}
    for level in range(depth):
        body = {f"wrapper_{level}": body}

    assert find_card_data_field(body) is not None
    assert CARD_VALUE not in json.dumps(strip_card_data(body))


def test_a_clean_body_is_not_mistaken_for_card_data():
    """The screen must not refuse the ordinary empty pay request."""
    assert find_card_data_field({}) is None
    assert find_card_data_field({"note": "please receipt this"}) is None
    assert find_card_data_field({"invoice": 12, "currency": "INR"}) is None


def test_no_secret_appears_in_a_successful_order_response_or_the_log(caplog):
    """23.2/23.5: the payments logger emits references and amounts only."""
    world = paying_world()
    url = reverse("core:invoice-pay", kwargs={"pk": world["invoice"].pk})

    with caplog.at_level(logging.DEBUG):
        response = world["client"].post(url, {}, format="json")

    assert response.status_code == 201, response.data
    serialised = json.dumps(response.json())
    logged = captured_text(caplog)

    for secret in SECRETS:
        assert secret not in serialised, "a secret was serialised into a response"
        assert secret not in logged, "a secret reached the log"

    # The public key id is the one credential that may cross the boundary.
    assert response.json()["key_id"] == get_adapter().public_key
    assert get_adapter().public_key not in SECRETS


def test_no_secret_appears_during_webhook_settlement_and_card_keys_are_stripped(caplog):
    """The stored payload is the durable risk, so it is checked too (18.7, 23.2)."""
    world = paying_world()
    order = create_order(world["invoice"], actor=world["member"].user)["order"]
    adapter = get_adapter()

    payload = build_event_payload(
        event_id="evt_p26_settle",
        kind=EVENT_PAYMENT_CAPTURED,
        order_ref=order.order_ref,
        payment_ref="pay_p26_settle",
        include_card_data=True,
    )
    raw, signature = signed_body(adapter, payload)

    with caplog.at_level(logging.DEBUG):
        response = APIClient().post(
            reverse("core:razorpay-webhook"),
            data=raw,
            content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE=signature,
        )

    assert response.status_code == 200, response.data
    logged = captured_text(caplog)
    serialised = json.dumps(response.json())

    for secret in SECRETS:
        assert secret not in logged
        assert secret not in serialised

    stored = WebhookEvent.objects.get(event_id="evt_p26_settle")
    persisted = json.dumps(stored.raw_payload)
    assert CARD_VALUE not in persisted, "card data was persisted"
    assert "cvv" not in persisted.lower()
    assert find_card_data_field(stored.raw_payload) is None
    # The references the platform legitimately keeps are still there.
    assert stored.raw_payload["entity"]["order_id"] == order.order_ref


def test_no_secret_appears_when_the_gateway_fails(caplog):
    """The error path logs an exception class, never the credentials it used."""
    from core.tests.fakes import FakeRazorpayAdapter

    world = paying_world()
    url = reverse("core:invoice-pay", kwargs={"pk": world["invoice"].pk})

    with caplog.at_level(logging.DEBUG):
        with override_settings(
            PAYMENT_GATEWAY_ADAPTER=FakeRazorpayAdapter(fail_mode="gateway_rejected")
        ):
            response = world["client"].post(url, {}, format="json")

    assert response.status_code == 502
    logged = captured_text(caplog)
    serialised = json.dumps(response.json())
    for secret in SECRETS:
        assert secret not in logged
        assert secret not in serialised


def test_no_model_or_serializer_declares_a_card_data_field():
    """23.1/23.3: there is no field a card number could be stored in."""
    from django.apps import apps

    from core import serializers as core_serializers

    for model in apps.get_app_config("core").get_models():
        for field in model._meta.get_fields():
            name = getattr(field, "name", "")
            assert find_card_data_field({name: ""}) is None, (
                f"{model.__name__}.{name} looks like a card-data field"
            )

    for attribute in dir(core_serializers):
        candidate = getattr(core_serializers, attribute)
        meta = getattr(candidate, "Meta", None)
        declared = getattr(meta, "fields", None)
        if not isinstance(declared, (list, tuple)):
            continue
        for name in declared:
            assert find_card_data_field({name: ""}) is None, (
                f"{attribute} declares card-data field {name!r}"
            )
