"""Pure helper functions for accounting data parsing and formatting.

These functions have no Qt dependencies and are extracted from accounting_export.py
for testability and reuse.
"""

from __future__ import annotations

import csv

# Column name candidates (case-insensitive) for each semantic field
_TIME_COLS = ["time", "timestamp", "ts"]
_PRICE_COLS = ["price", "money", "amount"]
_QTY_COLS = ["quantity", "qty", "count"]
_ITEM_COLS = ["itemstring", "item", "itemid"]

# Sign multiplier for copper totals; 0 = excluded from financial summary
_GOLD_SIGN = {
    "Sales": 1,
    "Purchases": -1,
    "Income": 1,
    "Expenses": -1,
    "Expired Auctions": 0,
    "Canceled Auctions": 0,
}


def _find_col(headers_lower: list[str], candidates: list[str]) -> int:
    for c in candidates:
        try:
            return headers_lower.index(c)
        except ValueError:
            pass
    return -1


def _parse_tsm_csv(csv_string: str) -> tuple[list[str], list[list[str]]]:
    lines = csv_string.replace("\\n", "\n").split("\n")
    all_rows = [r for r in csv.reader([ln for ln in lines if ln.strip()]) if r]
    if not all_rows:
        return [], []
    return all_rows[0], all_rows[1:]


def _to_unified_rows(
    raw_rows: list[list[str]], headers: list[str], label: str
) -> list[dict]:
    """Convert raw CSV rows to unified dicts with label/item/qty/copper/timestamp."""
    hl = [h.lower().strip() for h in headers]
    t_idx = _find_col(hl, _TIME_COLS)
    p_idx = _find_col(hl, _PRICE_COLS)
    q_idx = _find_col(hl, _QTY_COLS)
    i_idx = _find_col(hl, _ITEM_COLS)
    sign = _GOLD_SIGN.get(label, 0)

    result = []
    for row in raw_rows:
        try:
            ts = int(row[t_idx]) if 0 <= t_idx < len(row) else 0
            price = int(row[p_idx]) if 0 <= p_idx < len(row) else 0
            qty = int(row[q_idx]) if 0 <= q_idx < len(row) else 1
            item = row[i_idx] if 0 <= i_idx < len(row) else (row[0] if row else "?")
            item = item.strip().rstrip(":")
            copper = price * qty * sign
        except (ValueError, IndexError):
            continue
        result.append(
            {"label": label, "item": item, "qty": qty, "copper": copper, "timestamp": ts}
        )
    return result


def _base_item_str(item_str: str) -> str:
    """Return the base item string (i:ID) from a full TSM item string.

    For non-item strings like 'Repair Bill' or 'Money Transfer', returns as-is.
    """
    parts = item_str.split(":")
    if len(parts) >= 2 and parts[0] == "i" and parts[1].isdigit():
        return f"i:{parts[1]}"
    return item_str


def _is_fetchable(item_id: str) -> bool:
    """True only for numeric item IDs that Wowhead can resolve."""
    return item_id.isdigit()


def _fmt_gold(copper: int, with_sign: bool = False) -> str:
    gold = copper / 10000
    if with_sign and gold > 0:
        return f"+{gold:,.0f}g"
    return f"{gold:,.0f}g"
