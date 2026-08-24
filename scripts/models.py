"""Pydantic v2 Strict Data Models & Typed Structures for gstr-wala.

Provides strict, high-speed validation, IDE type hinting, and schema generation for:
  - GSTR-1 Invoices, Items, Credit/Debit Notes, HSN Summaries
  - GSTR-3B Outward Supplies, Eligible ITC, Ledger Balances, Set-off Matrix
  - Purchase Register & GSTR-2B Invoices, Reconciliation Summaries
"""

import re
from typing import Any, Dict, List, Literal, Optional, TypedDict
from pydantic import BaseModel, Field, field_validator

from scripts.constants import CHAR_SET, DATE_REGEX, GSTIN_REGEX, PERIOD_REGEX, STATE_CODES, VALID_RATES


def _compute_gstin_checksum(gstin14: str) -> str:
    factor = 1
    total = 0
    for char in gstin14:
        code_point = CHAR_SET.index(char)
        addend = factor * code_point
        factor = 1 if factor == 2 else 2
        addend = (addend // 36) + (addend % 36)
        total += addend
    remainder = total % 36
    check_code = (36 - remainder) % 36
    return CHAR_SET[check_code]


class TaxAmounts(TypedDict, total=False):
    iamt: float
    camt: float
    samt: float
    csamt: float


class TaxBucket(TypedDict, total=False):
    txval: float
    iamt: float
    camt: float
    samt: float
    csamt: float


class SetOffMatrixRow(TypedDict, total=False):
    total: float
    paid_by_igst_credit: float
    paid_by_cgst_credit: float
    paid_by_sgst_credit: float
    paid_by_cess_credit: float
    paid_by_cash: float


class SetOffMatrix(TypedDict):
    igst_liability: SetOffMatrixRow
    cgst_liability: SetOffMatrixRow
    sgst_liability: SetOffMatrixRow
    cess_liability: SetOffMatrixRow


class OptimizationResult(TypedDict, total=False):
    outward_liabilities: TaxAmounts
    rcm_liabilities: TaxAmounts
    rcm_cash_liability: Dict[str, float]
    available_itc: TaxAmounts
    available_itc_opening_plus_current: TaxAmounts
    credit_utilization: Dict[str, Any]
    itc_utilized: TaxAmounts
    setoff_matrix: SetOffMatrix
    net_cash_required: Dict[str, float]
    closing_credit_ledger: TaxAmounts
    closing_cash_ledger: Dict[str, float]
    interest_liability: Dict[str, float]
    late_fee_liability: Dict[str, float]
    challan_pmt06: Dict[str, Any]
    challan_pmt06_required: Dict[str, float]


class StatutoryInterestResult(TypedDict):
    net_cash_liability: float
    delay_days: int
    annual_rate: float
    interest_amount: float
    due_date: str
    filing_date: str


class StatutoryLateFeeResult(TypedDict, total=False):
    delay_days: int
    is_nil_return: bool
    turnover_slab: str
    cgst_late_fee: float
    sgst_late_fee: float
    camt: float
    samt: float
    total_late_fee: float
    capped: bool



class GSTRItem(BaseModel):
    txval: float = Field(ge=0.0, description="Taxable value")
    rt: float = Field(description="GST Rate percentage")
    iamt: float = Field(default=0.0, ge=0.0, description="Integrated Tax amount")
    camt: float = Field(default=0.0, ge=0.0, description="Central Tax amount")
    samt: float = Field(default=0.0, ge=0.0, description="State/UT Tax amount")
    csamt: float = Field(default=0.0, ge=0.0, description="Cess amount")
    hsn_sc: Optional[str] = Field(default="9999", description="HSN or SAC Code")
    desc: Optional[str] = Field(default="Goods / Services", description="Description")
    uqc: Optional[str] = Field(default="NOS", description="Unit Quantity Code")
    qty: Optional[float] = Field(default=1.0, ge=0.0, description="Quantity")

    @field_validator("rt")
    @classmethod
    def validate_rate(cls, v: float) -> float:
        if float(v) not in VALID_RATES:
            raise ValueError(f"Invalid GST rate: {v}%. Must be one of {sorted(list(VALID_RATES))}")
        return float(v)


class GSTR1Invoice(BaseModel):
    inum: str = Field(min_length=1, max_length=16, description="Invoice Number")
    idt: str = Field(description="Invoice Date (DD-MM-YYYY)")
    pos: str = Field(min_length=2, max_length=2, description="Place of Supply state code")
    val: Optional[float] = Field(default=0.0, ge=0.0, description="Total invoice value")
    ctin: Optional[str] = Field(default=None, description="Recipient GSTIN")
    rchrg: Literal["Y", "N"] = Field(default="N", description="Reverse Charge")
    inv_typ: Literal["R", "DE", "SEZWP", "SEZWOP", "CBW"] = Field(default="R")
    etin: Optional[str] = Field(default=None, description="E-Commerce Operator GSTIN")
    exp_typ: Optional[Literal["WPAY", "WOPAY"]] = None
    sb_num: Optional[str] = None
    sb_dt: Optional[str] = None
    port_code: Optional[str] = None
    items: List[GSTRItem] = Field(min_length=1)

    @field_validator("idt")
    @classmethod
    def validate_date(cls, v: str) -> str:
        if not DATE_REGEX.match(v):
            raise ValueError(f"Invalid date format '{v}'. Must be DD-MM-YYYY.")
        return v


class GSTR1CreditDebitNote(BaseModel):
    nt_num: str = Field(min_length=1, max_length=16, description="Note Number")
    nt_dt: str = Field(description="Note Date (DD-MM-YYYY)")
    ntty: Literal["C", "D"] = Field(description="C: Credit Note, D: Debit Note")
    inum: str = Field(description="Original Invoice Number")
    idt: str = Field(description="Original Invoice Date")
    pos: str = Field(min_length=2, max_length=2)
    val: float = Field(ge=0.0)
    ctin: Optional[str] = None
    rchrg: Literal["Y", "N"] = "N"
    items: List[GSTRItem] = Field(min_length=1)


class GSTR1Input(BaseModel):
    gstin: str = Field(description="15-character Supplier GSTIN")
    fp: str = Field(description="Financial Period in MMYYYY format")
    gt: Optional[float] = Field(default=0.0, ge=0.0, description="Gross turnover preceding FY")
    cur_gt: Optional[float] = Field(default=0.0, ge=0.0, description="Current FY turnover")
    invoices: List[GSTR1Invoice] = Field(default_factory=list)
    credit_debit_notes: List[GSTR1CreditDebitNote] = Field(default_factory=list)
    nil_exempt_non_gst: Dict[str, float] = Field(default_factory=dict)
    advances_received: List[Dict[str, Any]] = Field(default_factory=list)
    advances_adjusted: List[Dict[str, Any]] = Field(default_factory=list)
    doc_summary: List[Dict[str, Any]] = Field(default_factory=list)

    @field_validator("gstin")
    @classmethod
    def validate_gstin_format(cls, v: str) -> str:
        v = v.strip().upper()
        if not GSTIN_REGEX.match(v):
            raise ValueError(f"Invalid GSTIN format: '{v}'")
        state_code = v[:2]
        if state_code not in STATE_CODES:
            raise ValueError(f"Invalid State Code '{state_code}' in GSTIN '{v}'")
        expected = _compute_gstin_checksum(v[:14])
        if v[14] != expected:
            raise ValueError(f"GSTIN checksum mismatch for '{v}': expected '{expected}', found '{v[14]}'")
        return v

    @field_validator("fp")
    @classmethod
    def validate_period(cls, v: str) -> str:
        if not PERIOD_REGEX.match(v):
            raise ValueError(f"Invalid Period format '{v}'. Expected MMYYYY.")
        return v


class GSTR3BInput(BaseModel):
    gstin: str
    ret_period: str
    due_date: Optional[str] = None
    filing_date: Optional[str] = None
    turnover_slab: Literal["upto_1.5cr", "1.5cr_to_5cr", "above_5cr"] = "upto_1.5cr"
    outward_supplies: Dict[str, Any] = Field(default_factory=dict)
    eco_supplies: Dict[str, Any] = Field(default_factory=dict)
    inter_state_supplies: List[Dict[str, Any]] = Field(default_factory=list)
    itc: Dict[str, Any] = Field(default_factory=dict)
    inward_exempt_nil_non_gst: Dict[str, Any] = Field(default_factory=dict)
    opening_credit_ledger: Dict[str, float] = Field(default_factory=dict)
    opening_cash_ledger: Dict[str, float] = Field(default_factory=dict)
    interest_details: Dict[str, float] = Field(default_factory=dict)
    late_fee_details: Dict[str, float] = Field(default_factory=dict)

    @field_validator("gstin")
    @classmethod
    def validate_gstin_gstr3b(cls, v: str) -> str:
        v = v.strip().upper()
        if not GSTIN_REGEX.match(v):
            raise ValueError(f"Invalid GSTIN format: '{v}'")
        state_code = v[:2]
        if state_code not in STATE_CODES:
            raise ValueError(f"Invalid State Code '{state_code}' in GSTIN '{v}'")
        expected = _compute_gstin_checksum(v[:14])
        if v[14] != expected:
            raise ValueError(f"GSTIN checksum mismatch for '{v}': expected '{expected}', found '{v[14]}'")
        return v

    @field_validator("ret_period")
    @classmethod
    def validate_ret_period(cls, v: str) -> str:
        if not PERIOD_REGEX.match(v):
            raise ValueError(f"Invalid ret_period format '{v}'. Expected MMYYYY.")
        return v
