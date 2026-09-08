"""Conservative POS resolution for normalized sales rows."""

from scripts.models import validate_gstin_str


def resolve_pos(row: dict[str, str], explicit: str, ctin: str) -> tuple[str, str]:
    if explicit:
        warning = ""
        if ctin and explicit.zfill(2) != ctin[:2]:
            warning = "Explicit POS differs from recipient GSTIN state; confirm applicable special rule"
        return explicit.zfill(2), warning
    if not ctin:
        raise ValueError("POS_REVIEW_REQUIRED: missing POS and registered recipient GSTIN")
    recipient = validate_gstin_str(ctin)
    state = row.get("customer_state_code", "").strip().zfill(2)
    if state != "00" and state != recipient[:2]:
        raise ValueError("POS_REVIEW_REQUIRED: customer state conflicts with recipient GSTIN")
    special = any(row.get(key, "").strip() for key in
                  ("exp_typ", "export_type", "port_code", "sb_num", "sb_dt"))
    special = special or row.get("inv_typ", "R").upper() != "R"
    description = " ".join(row.get(key, "") for key in ("description", "item_description", "desc")).lower()
    special = special or any(word in description for word in
                             ("immovable", "hotel", "accommodation", "restaurant", "event", "sez", "export"))
    rule = row.get("pos_rule", "").strip().lower()
    if special or rule != "domestic_b2b_general_services":
        raise ValueError("POS_REVIEW_REQUIRED: confirm pos_rule=domestic_b2b_general_services or provide reviewed POS; goods/special/unknown services cannot be inferred safely")
    return recipient[:2], "Derived from recipient GSTIN under confirmed domestic B2B general-services rule; review exceptions"
