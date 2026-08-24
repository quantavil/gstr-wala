"""Shared utilities for gstr-wala: currency rounding, safe parsing, formatting."""

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


def safe_float(val: Any, default: float = 0.0) -> float:
    """Defensively converts to float, handling commas, strings, None."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        # reject inf/nan explicitly -> default
        try:
            f = float(val)
            if f != f or f in (float("inf"), float("-inf")):  # nan/inf
                return default
            return f
        except Exception:
            return default
    try:
        s = str(val).strip().replace(",", "").replace(" ", "")
        if not s or s.lower() in ("none", "nan", "inf", "-inf"):
            return default
        f = float(s)
        if f != f or f in (float("inf"), float("-inf")):
            return default
        return f
    except (ValueError, TypeError, AttributeError):
        return default


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
