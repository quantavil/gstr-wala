"""Shared utilities for gstr-wala: currency rounding, safe parsing, formatting."""

import datetime
import math
import re
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from typing import Any, List


def round_cur(val: Any) -> float:
    """Statutory currency rounding: Decimal HALF_UP to 2 decimals."""
    if val is None:
        return 0.0
    try:
        d = Decimal(str(val).strip() if isinstance(val, str) else str(val))
        if not d.is_finite():
            return 0.0
        return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except Exception:
        return 0.0


# --- Truthful money parsing -------------------------------------------------
#
# Design rule: bad/ambiguous input must NEVER be silently coerced into a
# plausible number. safe_float() keeps the legacy lenient contract (returns
# `default` on failure) while refusing to mis-parse; safe_float_strict()
# raises ValueError instead.

_RE_CURRENCY_TOKEN = re.compile(r"(?i)(?<![a-z])(?:rs\.?|inr)(?![a-z])|[₹$€£]")
_RE_PLAIN_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$")
_BLANK_MONEY_SENTINELS = {"", "none", "null", "nan", "na", "n/a", "-", "--"}
_EURO_DECIMAL_MSG = (
    "ambiguous European decimal-comma format {val!r} — expected Indian/US "
    "grouping with '.' as decimal separator (e.g. 1,23,456.78)"
)


def _parse_money_string(s: str) -> float:
    """Parses a money string truthfully; raises ValueError on anything ambiguous.

    Handles accounting negatives "(1,234.56)", currency symbols (₹, Rs., INR),
    Indian digit grouping "1,23,456.78" and US grouping. Rejects European
    decimal-comma format ("1.234,56") instead of mis-parsing it.
    """
    t = s.strip()
    if not t:
        raise ValueError(f"{s!r} is not a valid monetary amount")

    negative = False
    if t.startswith("(") and t.endswith(")"):
        negative = True
        t = t[1:-1].strip()

    t = _RE_CURRENCY_TOKEN.sub("", t)
    t = re.sub(r"\s+", "", t)

    if t.startswith("-"):
        negative = True
        t = t[1:]
    elif t.endswith("-"):  # trailing-minus accounting convention
        negative = True
        t = t[:-1]
    if t.startswith("+"):
        t = t[1:]

    if not t:
        raise ValueError(f"{s!r} is not a valid monetary amount")

    has_dot = "." in t
    has_comma = "," in t
    if has_dot and has_comma:
        # Whichever separator appears last is the decimal separator.
        if t.rfind(",") > t.rfind("."):
            raise ValueError(_EURO_DECIMAL_MSG.format(val=s))
        t = t.replace(",", "")
    elif has_comma:
        # Comma-only: valid only as thousands grouping, whose final group is
        # always 3 digits in both Indian and US conventions. A trailing
        # 2-digit group is European decimal style -> refuse rather than guess.
        if len(t.split(",")[-1]) == 2:
            raise ValueError(_EURO_DECIMAL_MSG.format(val=s))
        t = t.replace(",", "")

    if not _RE_PLAIN_NUMBER.match(t):
        raise ValueError(f"{s!r} is not a parseable monetary amount")

    val = float(t)
    return -val if negative else val


def _to_float_truthful(val: Any) -> float:
    """Converts any scalar to float or raises ValueError; no silent fallbacks."""
    if val is None:
        raise ValueError("None is not a valid monetary amount")
    if isinstance(val, bool):
        raise ValueError(f"boolean {val!r} is not a valid monetary amount")
    if isinstance(val, (int, float)):
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            raise ValueError(f"{val!r} is not a finite number")
        return f
    s = str(val)
    if s.strip().lower() in _BLANK_MONEY_SENTINELS:
        raise ValueError(f"{val!r} is not a valid monetary amount")
    return _parse_money_string(s)


def safe_float(val: Any, default: float = 0.0) -> float:
    """Defensively converts to float, handling commas, currency symbols,
    accounting negatives, strings, None.

    Truthful by construction: unparseable *or ambiguous* input (e.g. European
    decimal comma) returns `default` — it never invents a nearby number.
    Use safe_float_strict() for required fields where silence is unacceptable.
    """
    try:
        return _to_float_truthful(val)
    except (ValueError, TypeError):
        return default


def safe_float_strict(val: Any) -> float:
    """Strict money parsing for REQUIRED fields: raises ValueError on
    unparseable or ambiguous garbage instead of falling back to a default."""
    return _to_float_truthful(val)


# --- Canonical cell / date normalization ------------------------------------


def excel_cell_to_str(v: Any) -> str:
    """Canonical string form of an Excel cell value.

    Integer-valued floats lose the trailing '.0' (1001.0 -> "1001"), dates /
    datetimes become canonical DD-MM-YYYY strings, None becomes "" — this kills
    the ".0"-poisoned invoice numbers and timestamp-poisoned dates bug at every
    Excel entry point.
    """
    if v is None:
        return ""
    if isinstance(v, datetime.datetime):
        return v.strftime("%d-%m-%Y")
    if isinstance(v, datetime.date):
        return v.strftime("%d-%m-%Y")
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            return ""
        return str(int(v)) if v.is_integer() else str(v)
    return str(v).strip()


_RE_DMY = re.compile(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$")
_RE_YMD = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")


def normalize_date_str(raw: Any, context: str = "") -> str:
    """Explicitly parses DD-MM-YYYY, DD/MM/YYYY or YYYY-MM-DD into the canonical
    DD-MM-YYYY form (Indian convention: day-first even for US-looking values).

    Calendar-invalid dates ("31-02-2026") and malformed shapes ("05-04-26",
    "April 5") raise ValueError. `context` names the offending row/column in
    the error to make failures actionable.
    """
    prefix = f"{context}: " if context else ""
    _MISSING = (
        f"{prefix}missing invoice date — refusing to fabricate one "
        f"(expected DD-MM-YYYY, DD/MM/YYYY or YYYY-MM-DD)"
    )
    if isinstance(raw, (datetime.datetime, datetime.date)):
        return raw.strftime("%d-%m-%Y")
    if raw is None:
        raise ValueError(_MISSING)
    s = str(raw).strip()
    if not s or s.lower() in {"none", "null", "na", "n/a"}:
        raise ValueError(_MISSING)

    m_dmy = _RE_DMY.match(s)
    m_ymd = _RE_YMD.match(s)
    try:
        if m_dmy:
            parsed = datetime.datetime.strptime(s.replace("/", "-"), "%d-%m-%Y")
        elif m_ymd:
            parsed = datetime.datetime.strptime(s, "%Y-%m-%d")
        else:
            raise ValueError(
                f"{prefix}unparseable invoice date {raw!r} — expected DD-MM-YYYY, "
                f"DD/MM/YYYY or YYYY-MM-DD"
            )
    except ValueError as exc:
        if "unparseable invoice date" in str(exc):
            raise
        raise ValueError(
            f"{prefix}calendar-invalid invoice date {raw!r} — expected "
            f"DD-MM-YYYY, DD/MM/YYYY or YYYY-MM-DD"
        ) from exc
    return parsed.strftime("%d-%m-%Y")


def safe_int(val: Any, default: int = 0) -> int:
    try:
        f = safe_float(val, default=float(default))
        return int(round(f))
    except Exception:
        return default


def format_table(headers: List[str], rows: List[List[Any]]) -> str:
    """Formats an ASCII markdown table."""
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(val)))
    header_line = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
    sep_line = "|-" + "-|-".join("-" * col_widths[i] for i in range(len(headers))) + "-|"
    data_lines = []
    for row in rows:
        data_lines.append(
            "| "
            + " | ".join(
                str(val).rjust(col_widths[i]) if isinstance(val, (int, float)) else str(val).ljust(col_widths[i])
                for i, val in enumerate(row)
            )
            + " |"
        )
    return "\n".join([header_line, sep_line] + data_lines)


_RE_NON_ALNUM = re.compile(r"[^A-Za-z0-9]")
_RE_LEADING_ZERO = re.compile(r"(^|[A-Z]+)0+(\d+)")
RE_TRAILING_NUM = re.compile(r"(\d+)$")


@lru_cache(maxsize=8192)
def normalize_inum_cached(inum: str) -> str:
    if not inum:
        return ""
    cleaned = _RE_NON_ALNUM.sub("", str(inum)).upper()
    normalized = _RE_LEADING_ZERO.sub(r"\1\2", cleaned)
    return normalized


@lru_cache(maxsize=8192)
def extract_trailing_digits_cached(s: str) -> str:
    m = RE_TRAILING_NUM.search(s)
    if m:
        digits = m.group(1).lstrip("0")
        return digits if digits else "0"
    return s
