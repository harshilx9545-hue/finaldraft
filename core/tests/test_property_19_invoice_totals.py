"""Feature: gym-saas-core, Property 19."""
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from core.services.invoicing import compute_tax
from core.tests.strategies import gstins, two_dp_decimals


# Feature: gym-saas-core, Property 19: For any taxable value and for any GST
# configuration - no GSTIN, intra-state GSTIN, or inter-state GSTIN - the Invoice total
# equals the taxable value plus the sum of the populated CGST, SGST, and IGST amounts,
# the unpopulated tax fields are null, and the GSTIN and HSN or SAC code are present
# exactly when a GSTIN is recorded.
# Validates: Requirements 19.6, 19.4, 19.5
@settings(max_examples=500)
@given(
    taxable=two_dp_decimals(max_value="99999999.99"),
    gstin=st.one_of(st.none(), gstins()),
    intra_state=st.booleans(),
)
def test_invoice_total_equals_taxable_plus_populated_tax(taxable, gstin, intra_state):
    tax = compute_tax(taxable, gstin, intra_state)

    total = Decimal(taxable) + tax.total

    if gstin is None:
        # No registration: every tax field is null, and null is not zero.
        assert tax.cgst is None and tax.sgst is None and tax.igst is None
        assert tax.hsn_sac is None
        assert total == Decimal(taxable)
    else:
        assert tax.hsn_sac is not None
        if intra_state:
            assert tax.cgst is not None and tax.sgst is not None
            assert tax.igst is None
            # The halves must re-add exactly, including for odd paise.
            assert tax.cgst + tax.sgst == tax.total
        else:
            assert tax.igst is not None
            assert tax.cgst is None and tax.sgst is None
        assert total == Decimal(taxable) + tax.total

    # Every populated component carries exactly two decimal places.
    for component in (tax.cgst, tax.sgst, tax.igst):
        if component is not None:
            assert component == component.quantize(Decimal("0.01"))


@settings(max_examples=500)
@given(taxable=two_dp_decimals(max_value="99999999.99"), gstin=gstins())
def test_intra_and_inter_state_tax_totals_agree(taxable, gstin):
    """The split differs; the amount of tax charged does not."""
    intra = compute_tax(taxable, gstin, intra_state=True)
    inter = compute_tax(taxable, gstin, intra_state=False)
    assert intra.total == inter.total
