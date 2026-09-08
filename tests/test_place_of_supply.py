import pytest

from scripts.place_of_supply import resolve_pos


def test_general_service_derivation():
    pos, basis = resolve_pos({"pos_rule": "domestic_b2b_general_services"}, "", "07ACIFA6125A1ZW")
    assert pos == "07"
    assert "Derived" in basis


@pytest.mark.parametrize("row", [{}, {"pos_rule": "domestic_b2b_general_services", "customer_state_code": "09"},
                                 {"pos_rule": "domestic_b2b_general_services", "description": "Hotel accommodation"},
                                 {"pos_rule": "domestic_b2b_general_services", "inv_typ": "SEWP"}])
def test_unknown_and_exceptions_held(row):
    with pytest.raises(ValueError, match="POS_REVIEW_REQUIRED"):
        resolve_pos(row, "", "07ACIFA6125A1ZW")


def test_explicit_preserved_with_conflict_warning():
    pos, warning = resolve_pos({}, "09", "07ACIFA6125A1ZW")
    assert pos == "09"
    assert "differs" in warning


def test_parser_records_basis_and_validator_surfaces_review():
    from scripts.parse_sales_register import parse_rows_sales
    from scripts.validate_gst_input import validate_gstr1_input

    data = parse_rows_sales([{"inum": "190", "idt": "01-08-2026", "ctin": "07ACIFA6125A1ZW",
                              "txval": "40000", "rt": "18", "iamt": "7200",
                              "pos_rule": "domestic_b2b_general_services"}],
                            "09AXBPS5714M1ZZ", "082026")
    assert data["invoices"][0]["pos"] == "07"
    assert "Derived" in data["invoices"][0]["pos_basis"]
    assert any("POS review" in warning for warning in validate_gstr1_input(data).warnings)
