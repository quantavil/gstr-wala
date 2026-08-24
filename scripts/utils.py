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


def _reject_money(s: str, why: str = "is not a parseable monetary amount") -> ValueError:
    return ValueError(f"{s!r} {why}")


def _validate_grouping_shape(t: str, original: str) -> None:
    """Validates comma grouping before comma-stripping.

    Canonical shapes: Indian "1,23,456[.78]" and US "123,456[.78]" — every
    comma-delimited integer group is 1-3 digits with the FINAL group exactly 3,
    optionally followed by a single decimal part. Rejects irregular widths
    ("1,2345"), dangling commas ("1000," / ",1000") and stray separators.
    """
    if "." in t:
        head, dec = t.rsplit(".", 1)
        if "." in head or not dec.isdigit():
            raise _reject_money(original)
    else:
        head, dec = t, ""

    groups = head.split(",")
    if any(not g.isdigit() or len(g) > 3 for g in groups):
        raise _reject_money(original)
    final = groups[-1]
    if len(groups) > 1 and len(final) != 3:
        if len(final) == 2:
            # Trailing 2-digit group is European decimal style -> refuse to guess.
            raise ValueError(_EURO_DECIMAL_MSG.format(val=original))
        raise _reject_money(original)


def _parse_money_string(s: str) -> float:
    """Parses a money string truthfully; raises ValueError on anything ambiguous.

    Handles accounting negatives "(1,234.56)", currency symbols (₹, Rs., INR),
    Indian digit grouping "1,23,456.78" and US grouping "1,234,567.89". Rejects
    European decimal-comma format ("1.234,56"), dangling commas ("1000,"),
    malformed grouping ("1,2345") and residual sign characters ("--5", "+-5")
    instead of mis-parsing them.
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
        t = t.removeprefix("-")
    elif t.endswith("-"):  # trailing-minus accounting convention
        negative = True
        t = t.removesuffix("-")
    if t.startswith("+"):
        t = t.removeprefix("+")

    # At most one leading/trailing sign was consumed above; any residual sign
    # character means multi-sign garbage — refuse rather than silently flipping
    # the value again ("--5" must not become 5.0, "+-5" must not become -5.0).
    if not t or "-" in t or "+" in t:
        raise ValueError(f"{s!r} is not a valid monetary amount")

    if "," in t:
        # Whichever separator appears last is the decimal separator; a comma
        # after the dot is European decimal-comma format.
        if "." in t and t.rfind(",") > t.rfind("."):
            raise ValueError(_EURO_DECIMAL_MSG.format(val=s))
        _validate_grouping_shape(t, s)
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
        # Wrong *type* (not malformed content) -> TypeError per convention;
        # safe_float() catches both, so lenient behavior is unchanged.
        raise TypeError(f"boolean {val!r} is not a valid monetary amount")
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
    if m_dmy:
        try:
            parsed = datetime.datetime.strptime(s.replace("/", "-"), "%d-%m-%Y")  # noqa: DTZ007 — invoice dates are timezone-naive by definition
        except ValueError as exc:
            raise ValueError(
                f"{prefix}calendar-invalid invoice date {raw!r} — expected "
                f"DD-MM-YYYY, DD/MM/YYYY or YYYY-MM-DD"
            ) from exc
    elif m_ymd:
        try:
            parsed = datetime.datetime.strptime(s, "%Y-%m-%d")  # noqa: DTZ007 — invoice dates are timezone-naive by definition
        except ValueError as exc:
            raise ValueError(
                f"{prefix}calendar-invalid invoice date {raw!r} — expected "
                f"DD-MM-YYYY, DD/MM/YYYY or YYYY-MM-DD"
            ) from exc
    else:
        # Shape errors are raised outside the strptime calls above so we never
        # have to sniff our own exception text to tell them apart.
        raise ValueError(
            f"{prefix}unparseable invoice date {raw!r} — expected DD-MM-YYYY, "
            f"DD/MM/YYYY or YYYY-MM-DD"
        )
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
