"""Queries typed with the keyboard still on the wrong layout.

A Persian user who forgets to switch layouts types ``ovdn lhadk`` and gets a Latin
query that means nothing — but mapped through the Persian layout it is
«خرید ماشین». Search Console shows it as a separate, meaningless query. This module
maps QWERTY key positions to the standard Persian, Arabic, Russian and Hebrew
layouts (and back), and reports a mistype only when the mapped text matches a
query that really exists in the data — precision first.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .normalize import normalize
from .scripts import detect

_QWERTY = "qwertyuiop[]asdfghjkl;'zxcvbnm,./"

LAYOUTS: dict[str, dict[str, str]] = {
    # Iran standard (ISIRI 9147 / Windows Persian) lower row characters.
    "fa": dict(zip(_QWERTY, "ضصثقفغعهخحجچشسیبلاتنمکگظطزرذدپو./")),
    # Arabic (101) layout.
    "ar": dict(zip(_QWERTY, "ضصثقفغعهخحجدشسيبلاتنمكطئءؤرلاىةوزظ")),
    # Russian ЙЦУКЕН.
    "ru": dict(zip(_QWERTY, "йцукенгшщзхъфывапролджэячсмитьбю.")),
    # Hebrew standard.
    "he": dict(zip(_QWERTY, "/'קראטוןםפ][שדגכעיחלךף,זסבהנמצתץ.")),
}
# The Arabic layout maps 'b' to the ligature "لا" (two characters); fix that entry.
LAYOUTS["ar"] = dict(zip(_QWERTY, list("ضصثقفغعهخحجدشسيبلاتنمكطئءؤر") + ["لا"] + list("ىةوزظ")))

# Two Persian layouts are in everyday use and differ on two keys: one has پ on M,
# the other has ئ on M and پ on the backslash key. Both are tried.
LAYOUTS["fa2"] = {**LAYOUTS["fa"], "m": "\u0626", "\\": "\u067e"}

_REVERSE: dict[str, dict[str, str]] = {
    name: {v: k for k, v in table.items() if len(v) == 1} for name, table in LAYOUTS.items()
}


def remap_from_qwerty(text: str, layout: str) -> str | None:
    """What ``text`` (typed as Latin) would have produced on ``layout``.

    Returns ``None`` if a character has no key on that layout (a digit or a
    letter the layout does not carry), so callers do not get half-mapped text.
    """
    table = LAYOUTS[layout]
    out = []
    for ch in text.lower():
        if ch == " ":
            out.append(" ")
        elif ch in table:
            out.append(table[ch])
        else:
            return None
    return "".join(out)


def remap_to_qwerty(text: str, layout: str) -> str | None:
    """The reverse: text produced on ``layout`` while the user meant to type Latin."""
    table = _REVERSE[layout]
    out = []
    for ch in text:
        if ch == " ":
            out.append(" ")
        elif ch in table:
            out.append(table[ch])
        else:
            return None
    return "".join(out)


_LATIN_VOWELS = frozenset("aeiouy")


@dataclass(frozen=True)
class LayoutMistype:
    query: str
    intended: str
    layout: str
    matched_query: str | None  # the real query it collapses into, if any
    clicks: int
    impressions: int


def find_layout_mistypes(
    rows: Iterable[dict],
    layouts: Iterable[str] = ("fa", "fa2", "ar", "ru", "he"),
    level: str = "standard",
    include_unmatched: bool = False,
) -> list[LayoutMistype]:
    """Find queries that are another query typed on the wrong keyboard layout.

    Every Latin-script query is mapped key by key onto each layout; a hit is
    reported when the result is a query that really appears in ``rows``. The
    mapping is done on the raw text, because on these layouts punctuation keys
    (``;`` ``,`` ``'`` ``[`` ``]`` ``\\``) type letters and must not be treated
    as separators. Of the two queries in a pair, the one seen less often is the
    slip (on a tie, the Latin one).

    With ``include_unmatched`` a Latin query with no vowels that maps cleanly
    onto a layout is reported too (lower precision).
    """
    def _imps(r: dict) -> int:
        return int(r.get("impressions", 0) or 0)

    def _clicks(r: dict) -> int:
        return int(r.get("clicks", 0) or 0)

    layouts = list(layouts)
    latin_rows: list[dict] = []
    by_key: dict[str, dict] = {}  # match key -> most-seen query written in another script
    for row in rows:
        q = row.get("query", "")
        if not q:
            continue
        if detect(q).script == "latin":
            latin_rows.append(row)
            continue
        k = normalize(q, level).key
        if k and (k not in by_key or _imps(row) > _imps(by_key[k])):
            by_key[k] = row

    hits: list[LayoutMistype] = []
    for row in latin_rows:
        q = row["query"]
        for layout in layouts:
            mapped = remap_from_qwerty(q, layout)
            if not mapped or detect(mapped).script in ("latin", "none"):
                continue
            target = by_key.get(normalize(mapped, level).key)
            if target is not None:
                if _imps(row) <= _imps(target):
                    hits.append(LayoutMistype(q, target["query"], layout, target["query"], _clicks(row), _imps(row)))
                else:  # the Latin query is the real word; the other script is the slip
                    hits.append(LayoutMistype(target["query"], q, layout, q, _clicks(target), _imps(target)))
                break
            if include_unmatched and len(q.replace(" ", "")) >= 4 and not (set(q.lower()) & _LATIN_VOWELS):
                hits.append(LayoutMistype(q, mapped, layout, None, _clicks(row), _imps(row)))
                break
    hits.sort(key=lambda h: (-h.impressions, -h.clicks))
    return hits
