"""Compact, readable tool output.

Tools return Markdown text. Rows are capped so a big property cannot flood
the model's context, and the cap is always stated so the model knows to
narrow the question instead of assuming it saw everything.

Two things are never done to a value: a URL is never shortened (a cut-off URL
cannot be passed back to another tool), and text from Search Console is never
allowed to act as Markdown — queries are typed by the public.
"""

from __future__ import annotations

import os
import unicodedata
from collections.abc import Iterable, Sequence

_RTL_BIDI = {"R", "AL"}
_ESCAPES = str.maketrans({"|": "\\|", "[": "\\[", "]": "\\]", "<": "&lt;", "`": "'", "\r": " ", "\n": " "})


def _has_rtl(s: str) -> bool:
    return any(unicodedata.bidirectional(ch) in _RTL_BIDI for ch in s)


def bidi(s: str) -> str:
    """Isolate RTL text so a mixed table renders in order.

    Off unless ``GSC_BIDI_ISOLATE=1``: the marks are invisible to people but a
    few clients show them as boxes.
    """
    if s and os.environ.get("GSC_BIDI_ISOLATE", "").lower() in ("1", "true", "yes") and _has_rtl(s):
        return "\u2068" + s + "\u2069"
    return s


def fmt_int(n: float | int) -> str:
    return f"{int(round(n)):,}"


def fmt_pct(x: float, digits: int = 1) -> str:
    return f"{x * 100:.{digits}f}%"


def fmt_pos(p: float) -> str:
    return f"{p:.1f}"


def fmt_delta(cur: float, prev: float, pct: bool = True) -> str:
    """``+12.5%`` style change, or ``new`` / ``gone`` when one side is zero."""
    if prev == 0 and cur == 0:
        return "0"
    if prev == 0:
        return "new"
    if cur == 0:
        return "gone"
    d = (cur - prev) / prev
    sign = "+" if d >= 0 else ""
    return f"{sign}{d * 100:.1f}%" if pct else f"{sign}{cur - prev:,.0f}"


def fmt_pos_delta(cur: float, prev: float) -> str:
    """Position deltas: lower is better, so a drop in the number is shown as an improvement."""
    if not prev or not cur:
        return "—"
    d = prev - cur
    if abs(d) < 0.05:
        return "="
    return f"{'▲' if d > 0 else '▼'}{abs(d):.1f}"


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.2f}"
    return bidi(str(v).translate(_ESCAPES))


def md_table(headers: Sequence[str], rows: Iterable[Sequence], max_rows: int | None = None) -> str:
    rows = list(rows)
    shown = rows if max_rows is None else rows[:max_rows]
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for r in shown:
        lines.append("| " + " | ".join(_cell(c) for c in r) + " |")
    if max_rows is not None and len(rows) > max_rows:
        lines.append(f"\n_{len(rows) - max_rows:,} more rows not shown (of {len(rows):,}). Narrow the request or raise `limit`._")
    return "\n".join(lines)


def kv(items: Iterable[tuple[str, object]]) -> str:
    return "\n".join(f"- **{k}:** {v}" for k, v in items)


def metrics_line(m: dict) -> str:
    return (
        f"clicks {fmt_int(m.get('clicks', 0))} · impressions {fmt_int(m.get('impressions', 0))} · "
        f"CTR {fmt_pct(m.get('ctr', 0))} · position {fmt_pos(m.get('position', 0))}"
    )


def truncate(s: str, n: int = 60) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"

