"""Feature: gym-saas-core, Property 25 (stateful).

The machine drives the real money path — issue, order, webhook settle, webhook
fail, retry, refund, soft delete — through the services, never by writing rows
directly, and checks the ledger identity plus the immutability rules after every
step.

Two deliberate restrictions on what the machine generates, both because the
requirement set does not define an answer and inventing one would be inventing a
requirement:

* **One live order per Invoice.** A second order is created only after the first
  Payment has failed, which is the retry path 18.5 describes. Two *simultaneous*
  orders both captured would produce two `succeeded` Payments against one Invoice;
  17.5 only forbids creating a new order once one has already succeeded, and no
  criterion says what settlement should do with the second capture.
* **Soft delete of ledger-bearing rows is not driven by the machine.** 22.3 permits
  soft-deleting a settled Invoice and 22.4 excludes it from default querysets, but
  no criterion says whether its `succeeded` Payment should also leave the ledger.
  The machine soft-deletes only failed Payments and open Invoices, which cannot
  affect the 22.5 identity; the settled case is asserted separately below for
  exactly what 22.3 and 22.4 do specify.

Full refunds only, for the same reason: 22.5 nets "refunded amounts" against
"settled Invoice totals", and a *partial* refund flips the original Payment out of
`succeeded` entirely (22.7 says the status changes), which leaves the identity with
no defined value. A partial refund is asserted separately against the clauses 22.7
does state.
"""
import datetime
import itertools
from decimal import Decimal

import pytest
from django.contrib.admin.sites import AdminSite
from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import RequestFactory
from django.urls import reverse
from hypothesis import settings as hyp_settings
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, precondition, rule

from core.exceptions import Http409, InvoiceImmutable
from core.models import AuditRecord, CreditNote, Invoice, Membership, MembershipPlan, Payment
from core.services.gateway import EVENT_PAYMENT_CAPTURED, EVENT_PAYMENT_FAILED, get_adapter
from core.services.invoicing import (
    IMMUTABLE_WHEN_SETTLED,
    assert_amendable,
    settle,
    void_via_credit_note,
)
from core.services.payments import (
    WebhookOutcome,
    create_order,
    ledger_balance,
    process_event,
    refund,
)
from core.tests import factories
from core.tests.fakes import build_event_payload

pytestmark = pytest.mark.django_db(transaction=True)

_events = itertools.count(1)

PLAN_DURATION_DAYS = 30
ZERO = Decimal("0.00")

#: Models whose rows must never be hard-deleted (22.3).
SOFT_DELETE_ONLY_MODELS = (Payment, Invoice, Membership)


def deliver(payload_kind, order_ref, *, amount_minor=None, method="upi"):
    """Build and process one verified gateway event through the real parse path."""
    adapter = get_adapter()
    payload = build_event_payload(
        event_id=f"evt_p25_{next(_events):08d}",
        kind=payload_kind,
        order_ref=order_ref,
        payment_ref=f"pay_p25_{next(_events):08d}",
        method=method,
        amount_minor=amount_minor if amount_minor is not None else 10000,
    )
    return process_event(adapter.parse_event(payload), payload)


def audit_rows(instance, action=None):
    query = AuditRecord.objects.filter(
        model_label=f"core.{type(instance).__name__}", object_id=str(instance.pk)
    )
    if action is not None:
        query = query.filter(action=action)
    return list(query)


# Feature: gym-saas-core, Property 25: For any sequence of invoice issue, order
# creation, webhook settlement, refund, and soft-delete operations, the sum of each
# Member's succeeded Payment amounts equals the sum of that Member's settled Invoice
# totals net of refunds; every stored Payment amount is greater than 0; every attempt
# to change the amount, taxable value, or tax fields of a settled Invoice is refused
# with 409 leaving the row unchanged, with corrections appearing as CreditNote rows;
# every refund is a new Payment with status refunded referencing the original, leaving
# the original unchanged apart from its status; and every create or modify of a
# Payment, Invoice, or Membership has a matching append-only AuditRecord naming actor,
# timestamp, record identifier, and before/after values for exactly the changed fields.
# Validates: Requirements 22.5, 22.6, 22.7, 22.1, 22.2, 22.3, 22.4, 19.7, 19.8, 16.9,
#            16.7, 19.9, 3.10
class LedgerMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.gym = None
        self.owner = None
        self.member = None
        self.plan = None
        #: Frozen financial fields of every settled Invoice, so a later mutation
        #: attempt can be shown to have changed nothing.
        self.settled_snapshots = {}

    @initialize()
    def setup(self):
        self.gym = factories.make_gym()
        self.owner = factories.make_owner(self.gym)
        self.plan = factories.make_membership_plan(
            self.gym, price="1500.00", duration_days=PLAN_DURATION_DAYS
        )
        self.member = factories.make_member(self.gym, plan=self.plan)
        self.settled_snapshots = {}

    # -- helpers -------------------------------------------------------------

    def member_invoices(self, **filters):
        return Invoice.objects.filter(membership__member=self.member, **filters)

    def next_membership_start(self):
        latest = (
            Membership.objects.filter(member=self.member)
            .order_by("-end_date")
            .values_list("end_date", flat=True)
            .first()
        )
        if latest is None:
            return self.gym.today()
        return latest + datetime.timedelta(days=1)

    def payable_invoice(self):
        """An open Invoice with no live Payment attempt against it."""
        for invoice in self.member_invoices(status="open", deleted_at__isnull=True):
            live = invoice.payments.filter(status__in=["pending", "succeeded"])
            if not live.exists():
                return invoice
        return None

    # -- rules ---------------------------------------------------------------

    @rule()
    def issue_membership_and_invoice(self):
        """A priced plan produces a Membership and an Invoice (4.7)."""
        from core.services.memberships import create_membership

        result = create_membership(
            self.member, self.plan, start=self.next_membership_start()
        )
        membership, invoice = result["membership"], result["invoice"]

        assert invoice is not None, "a priced plan must produce an invoice"
        assert invoice.status == "open"
        # 22.1: creation is audited for both records.
        assert audit_rows(membership, "create"), "membership create not audited"
        assert audit_rows(invoice, "create"), "invoice create not audited"

    @rule()
    def create_payment_order(self):
        invoice = self.payable_invoice()
        if invoice is None:
            return

        result = create_order(invoice, actor=self.member.user)
        payment = result["payment"]

        assert payment.status == "pending"
        assert payment.gateway_order_ref == result["order"].order_ref
        assert payment.amount == invoice.total_amount
        # 16.7: recorded_on is an explicit date, not auto_now_add.
        assert payment.recorded_on == self.gym.today()
        assert audit_rows(payment, "create"), "payment create not audited"

    @rule()
    def settle_pending_payment(self):
        payment = Payment.objects.filter(
            gym=self.gym, status="pending", invoice__membership__member=self.member
        ).first()
        if payment is None:
            return

        invoice = payment.invoice
        result = deliver(EVENT_PAYMENT_CAPTURED, payment.gateway_order_ref)
        assert result["outcome"] == WebhookOutcome.PROCESSED

        payment.refresh_from_db()
        invoice.refresh_from_db()
        assert payment.status == "succeeded"
        # 16.9: the paid timestamp is set on the transition to succeeded.
        assert payment.paid_at is not None
        assert invoice.status == "settled"

        self.settled_snapshots[invoice.pk] = {
            name: getattr(invoice, name) for name in IMMUTABLE_WHEN_SETTLED
        }

        # 22.1: the modification records only the fields that changed.
        updates = audit_rows(invoice, "settle")
        assert updates, "settlement not audited"
        assert set(updates[-1].changes) == {"status"}
        assert updates[-1].changes["status"] == ["open", "settled"]

    @rule()
    def fail_pending_payment(self):
        payment = Payment.objects.filter(
            gym=self.gym, status="pending", invoice__membership__member=self.member
        ).first()
        if payment is None:
            return

        invoice = payment.invoice
        status_before = invoice.status
        deliver(EVENT_PAYMENT_FAILED, payment.gateway_order_ref)

        payment.refresh_from_db()
        invoice.refresh_from_db()
        assert payment.status == "failed"
        # 18.5: a failure settles nothing. Asserted as "unchanged" rather than
        # "open" because a preceding rule may have voided the invoice, and the
        # requirement is that the failure does not move it, not that it is open.
        assert invoice.status == status_before
        assert invoice.status != "settled"

    @rule()
    def refund_succeeded_payment(self):
        original = Payment.objects.filter(
            gym=self.gym,
            status="succeeded",
            refund_of__isnull=True,
            invoice__membership__member=self.member,
        ).first()
        if original is None:
            return

        before = {
            "amount": original.amount,
            "currency": original.currency,
            "order_ref": original.gateway_order_ref,
            "payment_ref": original.gateway_payment_ref,
            "method": original.method,
            "recorded_on": original.recorded_on,
        }

        reversal = refund(original, actor=self.owner.user)
        original.refresh_from_db()

        # 22.7: a new refunded Payment referencing the original.
        assert reversal.status == "refunded"
        assert reversal.refund_of_id == original.pk
        assert reversal.amount == before["amount"]
        # The original is unchanged apart from its status.
        assert original.status == "refunded"
        assert original.amount == before["amount"]
        assert original.currency == before["currency"]
        assert original.gateway_order_ref == before["order_ref"]
        assert original.gateway_payment_ref == before["payment_ref"]
        assert original.method == before["method"]
        assert original.recorded_on == before["recorded_on"]
        assert audit_rows(reversal, "create")
        assert audit_rows(original, "refund")

    @rule()
    def attempt_to_amend_a_settled_invoice(self):
        """19.7: a financial-field change on a settled Invoice is refused with 409."""
        invoice = self.member_invoices(status="settled").first()
        if invoice is None:
            return

        frozen = self.settled_snapshots.get(invoice.pk) or {
            name: getattr(invoice, name) for name in IMMUTABLE_WHEN_SETTLED
        }

        for field in IMMUTABLE_WHEN_SETTLED:
            with pytest.raises(InvoiceImmutable) as caught:
                assert_amendable(invoice, [field])
            assert caught.value.status_code == 409
            assert caught.value.details["field"] == field

        # The model layer refuses the same change, so the admin inherits the rule.
        invoice.taxable_value = frozen["taxable_value"] + Decimal("1.00")
        with pytest.raises(DjangoValidationError) as model_error:
            invoice.clean()
        assert "taxable_value" in model_error.value.message_dict

        invoice.refresh_from_db()
        for name, value in frozen.items():
            assert getattr(invoice, name) == value, f"{name} changed on a settled invoice"

    @rule()
    def attempt_to_reopen_a_succeeded_payment(self):
        """16.9: a succeeded Payment never returns to pending."""
        payment = Payment.objects.filter(gym=self.gym, status="succeeded").first()
        if payment is None:
            return

        payment.status = "pending"
        with pytest.raises(DjangoValidationError) as caught:
            payment.clean()
        assert "status" in caught.value.message_dict

        payment.refresh_from_db()
        assert payment.status == "succeeded"

    @rule()
    def soft_delete_a_failed_payment(self):
        """22.3/22.4: the row is retained and leaves the default queryset."""
        payment = Payment.objects.filter(gym=self.gym, status="failed").first()
        if payment is None:
            return

        pk = payment.pk
        payment.delete()  # hard_delete_allowed is False, so this soft-deletes

        assert not Payment.objects.filter(pk=pk).exists()
        retained = Payment.all_objects.filter(pk=pk).first()
        assert retained is not None
        assert retained.deleted_at is not None
        assert audit_rows(retained, "soft_delete"), "soft delete not audited"

    @rule()
    def void_an_open_invoice_via_credit_note(self):
        """19.8: a correction is a CreditNote row, never an edit."""
        # Only an invoice with no live payment attempt: voiding one that a member is
        # mid-way through paying is a state the API cannot produce, so generating it
        # would test a rule the requirements do not define.
        invoice = self.payable_invoice()
        if invoice is None:
            return

        before = {name: getattr(invoice, name) for name in IMMUTABLE_WHEN_SETTLED}
        note = void_via_credit_note(invoice, "machine-generated correction")
        invoice.refresh_from_db()

        assert note.invoice_id == invoice.pk
        assert note.amount == before["total_amount"]
        assert invoice.status == "void"
        for name, value in before.items():
            assert getattr(invoice, name) == value

    # -- invariants ----------------------------------------------------------

    @precondition(lambda self: self.member is not None)
    @invariant()
    def ledger_conserves(self):
        """22.5: succeeded payments equal settled invoice totals, net of refunds."""
        balance = ledger_balance(self.member)
        assert balance["received"] == balance["invoiced"] - balance["refunded"], balance

    @precondition(lambda self: self.gym is not None)
    @invariant()
    def every_stored_payment_amount_is_positive(self):
        """22.6/16.6: including soft-deleted rows, no amount is zero or negative."""
        amounts = Payment.all_objects.filter(gym=self.gym).values_list("amount", flat=True)
        assert all(amount > ZERO for amount in amounts), list(amounts)

    @precondition(lambda self: self.gym is not None)
    @invariant()
    def every_financial_row_has_a_create_audit_record(self):
        """22.1: nothing enters the ledger without an attributable audit record."""
        for model in (Invoice, Payment, Membership):
            for instance in model.all_objects.filter(
                **({"gym": self.gym} if model is not Membership else {"member": self.member})
            ):
                assert audit_rows(instance, "create"), (
                    f"{model.__name__}#{instance.pk} has no create audit record"
                )

    @precondition(lambda self: self.gym is not None)
    @invariant()
    def settled_invoices_never_change_their_financial_fields(self):
        for pk, frozen in self.settled_snapshots.items():
            invoice = Invoice.all_objects.filter(pk=pk).first()
            if invoice is None:
                continue
            for name, value in frozen.items():
                assert getattr(invoice, name) == value, (
                    f"invoice {invoice.number} {name} moved after settlement"
                )


TestLedgerAndImmutability = LedgerMachine.TestCase
TestLedgerAndImmutability.settings = hyp_settings(
    max_examples=100, stateful_step_count=12, deadline=None
)


# ============ CLAUSES THE MACHINE DELIBERATELY DOES NOT GENERATE ============

def _settled_membership_payment():
    """A member holding one settled membership Invoice paid by one succeeded Payment."""
    gym = factories.make_gym()
    owner = factories.make_owner(gym)
    plan = factories.make_membership_plan(gym, price="1500.00", duration_days=30)
    member = factories.make_member(gym, plan=plan)

    from core.services.memberships import create_membership

    result = create_membership(member, plan, start=gym.today())
    invoice = result["invoice"]
    order = create_order(invoice, actor=member.user)
    deliver(EVENT_PAYMENT_CAPTURED, order["order"].order_ref)

    invoice.refresh_from_db()
    payment = order["payment"]
    payment.refresh_from_db()
    return {
        "gym": gym,
        "owner": owner,
        "member": member,
        "invoice": invoice,
        "payment": payment,
    }


def test_partial_refund_records_a_reversal_and_leaves_the_original_intact():
    """22.7 for the partial case: only the status of the original moves."""
    world = _settled_membership_payment()
    original = world["payment"]
    before_amount = original.amount

    reversal = refund(original, amount=Decimal("500.00"), actor=world["owner"].user)
    original.refresh_from_db()

    assert reversal.status == "refunded"
    assert reversal.refund_of_id == original.pk
    assert reversal.amount == Decimal("500.00")
    assert original.amount == before_amount, "the original amount must not be rewritten"
    assert original.status == "refunded"


def test_refund_is_refused_for_a_payment_that_never_succeeded():
    world = _settled_membership_payment()
    pending = factories.make_payment(world["invoice"], status="pending")

    with pytest.raises(Http409):
        refund(pending)

    pending.refresh_from_db()
    assert pending.status == "pending"


def test_refund_cannot_exceed_the_original_amount():
    world = _settled_membership_payment()
    with pytest.raises(Http409):
        refund(world["payment"], amount=world["payment"].amount + Decimal("0.01"))


def test_credit_note_against_a_settled_invoice_leaves_its_financial_fields_frozen():
    """19.8: correction after settlement is a separate record, not an amendment."""
    world = _settled_membership_payment()
    invoice = world["invoice"]
    before = {name: getattr(invoice, name) for name in IMMUTABLE_WHEN_SETTLED}

    note = void_via_credit_note(invoice, "duplicate charge", actor=world["owner"].user)
    invoice.refresh_from_db()

    assert CreditNote.objects.filter(pk=note.pk).exists()
    for name, value in before.items():
        assert getattr(invoice, name) == value


def test_soft_deleting_a_settled_invoice_retains_the_row(): 
    """22.3/22.4: retained, out of the default queryset, reachable via all_objects."""
    world = _settled_membership_payment()
    invoice = world["invoice"]
    pk = invoice.pk

    invoice.delete()

    assert not Invoice.objects.filter(pk=pk).exists()
    retained = Invoice.all_objects.filter(pk=pk).first()
    assert retained is not None and retained.deleted_at is not None
    assert retained.status == "settled", "soft delete must not rewrite the status"
    assert audit_rows(retained, "soft_delete")


def test_financial_models_have_no_hard_delete_path():
    """22.3: neither the ORM nor any route can hard-delete a financial record."""
    for model in SOFT_DELETE_ONLY_MODELS:
        assert model.hard_delete_allowed is False, model.__name__

    from core import urls as core_urls

    # Presence of a `delete` handler is what makes a route answer DELETE; the
    # default `http_method_names` list is permissive but a view without the handler
    # answers 405.
    for pattern in core_urls.urlpatterns:
        view = getattr(pattern.callback, "cls", None) or getattr(
            pattern.callback, "view_class", None
        )
        assert not hasattr(view, "delete"), f"{pattern.name} implements a DELETE handler"


def test_audit_records_are_append_only():
    """22.2: no update or delete path exists, by manager."""
    world = _settled_membership_payment()
    rows = AuditRecord.objects.filter(gym=world["gym"])
    assert rows.exists()

    with pytest.raises(NotImplementedError):
        rows.update(action="tampered")
    with pytest.raises(NotImplementedError):
        rows.delete()

    from core.admin import AuditRecordAdmin

    site = AdminSite()
    admin_instance = AuditRecordAdmin(AuditRecord, site)
    request = RequestFactory().get("/admin/")
    request.user = factories.make_staff()
    assert admin_instance.has_add_permission(request) is False
    assert admin_instance.has_change_permission(request) is False
    assert admin_instance.has_delete_permission(request) is False


def test_admin_write_on_a_tenant_scoped_model_is_audited():
    """3.10: staff reach across tenants, so every admin write is attributable."""
    from core.admin import AuditedModelAdmin

    gym = factories.make_gym()
    plan = factories.make_membership_plan(gym, name="Original")
    staff = factories.make_staff()

    admin_instance = AuditedModelAdmin(MembershipPlan, AdminSite())
    request = RequestFactory().post("/admin/")
    request.user = staff

    plan.name = "Renamed by operator"
    admin_instance.save_model(request, plan, None, True)

    entry = (
        AuditRecord.objects.filter(
            model_label="core.MembershipPlan", object_id=str(plan.pk)
        )
        .order_by("-created_at")
        .first()
    )
    assert entry is not None
    assert entry.action == "admin_write"
    assert entry.actor_user_id == staff.pk
    assert entry.gym_id == gym.pk
    assert entry.created_at is not None
    assert entry.changes["name"] == ["Original", "Renamed by operator"]


def test_receipt_is_available_to_the_payer_once_the_payment_succeeded():
    """19.9: the payer can fetch a receipt after settlement, and only then."""
    from rest_framework.test import APIClient

    world = _settled_membership_payment()
    client = APIClient()
    factories.authenticate(client, world["member"].user)

    url = reverse("core:payment-receipt", kwargs={"pk": world["payment"].pk})
    response = client.get(url)
    assert response.status_code == 200, response.data
    body = response.json()
    assert body["payment"]["status"] == "succeeded"
    assert body["invoice"]["number"] == world["invoice"].number
    assert body["issued_to"]["email"] == world["member"].user.email

    pending = factories.make_payment(world["invoice"], status="pending")
    conflict = client.get(reverse("core:payment-receipt", kwargs={"pk": pending.pk}))
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "CONFLICT"


def test_recorded_on_is_explicit_and_settable():
    """16.7: historical payments can be recorded with their true date."""
    world = _settled_membership_payment()
    back_dated = factories.make_payment(world["invoice"], status="pending")
    back_dated.recorded_on = datetime.date(2024, 1, 15)
    back_dated.save(update_fields=["recorded_on"])
    back_dated.refresh_from_db()

    assert back_dated.recorded_on == datetime.date(2024, 1, 15)
    field = Payment._meta.get_field("recorded_on")
    assert field.auto_now_add is False and field.auto_now is False
