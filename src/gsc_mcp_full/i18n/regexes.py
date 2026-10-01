"""Search Console regex filters that work for every script.

The API's ``INCLUDING_REGEX`` / ``EXCLUDING_REGEX`` filters use RE2, and RE2's
``\\b`` only knows ASCII word characters — so ``\\bماشین\\b`` or ``\\b空调\\b``
silently matches nothing. :func:`api_regex` builds a pattern with a Unicode-safe
boundary that also matches the common spellings of a term:

- Arabic script: ی/ي/ى, ک/ك, ه/ة/ۀ, ا/أ/إ/آ and و/ؤ are one class each; vowel
  marks, tatweel and a half-space may sit between any two letters
- digits match their ASCII, Persian, Arabic-Indic and full-width forms
- Cyrillic е/ё
- letter case, for every script that has it

It does not cover accent-dropping (café/cafe) or kana variants; group those
with ``query_variants`` / ``level=loose`` instead.
"""

from __future__ import annotations

import re
import unicodedata

from .scripts import UNSPACED_SCRIPTS, char_script, detect

# Every member of a class folds to the same letter; the first is the canonical one.
_CLASSES = (
    "\u06cc\u064a\u0649",  # ی ي ى
    "\u06a9\u0643",  # ک ك
    "\u0647\u0629\u06c0",  # ه ة ۀ
    "\u0627\u0623\u0625\u0622\u0671",  # ا أ إ آ ٱ
    "\u0648\u0624",  # و ؤ
    "\u0435\u0451",  # е ё
)
_CLASS_OF: dict[str, str] = {}
for _cls in _CLASSES:
    for _ch in _cls:
        _CLASS_OF[_ch] = "[" + _cls + "]"

# Between two Arabic-script letters: vowel marks, tatweel, half-space, joiner.
_FILL = "[\\x{064B}-\\x{065F}\\x{0670}\\x{0640}\\x{200C}\\x{200D}]*"
_SEP = "[\\s\\x{200C}\\x{200D}\\x{00A0}]"  # space, half-space, joiner, nbsp


def _digit_class(ch: str) -> str:
    d = unicodedata.decimal(ch)
    forms = [str(d), chr(0x06F0 + d), chr(0x0660 + d), chr(0xFF10 + d)]
    if ch not in forms:
        forms.append(ch)  # e.g. a Devanagari or Thai digit must still match itself
    return "[" + "".join(forms) + "]"


def _re2_escape(ch: str) -> str:
    # RE2 accepts a backslash before any ASCII punctuation; letters must not be escaped.
    return "\\" + ch if (ch.isascii() and not ch.isalnum() and not ch.isspace()) else ch


def _is_mark(ch: str) -> bool:
    cp = ord(ch)
    return 0x064B <= cp <= 0x065F or cp in (0x0670, 0x0640)


def api_regex(term: str, whole_word: bool = True, loose: bool = False, case_insensitive: bool = True) -> str:
    """An RE2 pattern for the Search Console API that matches the spellings of ``term``.

    ``whole_word`` uses ``(?:^|[^\\pL\\pN])`` boundaries, which unlike ``\\b`` work
    for non-ASCII letters; it is skipped for scripts written without spaces.
    ``loose`` lets the words of the term run together. The pattern is
    case-insensitive (Search Console lower-cases queries, so an upper-case
    letter in the term would otherwise never match).

    The result is a plain string to pass as the ``expression`` of a dimension filter.
    """
    det = detect(term)
    parts: list[str] = []
    sep = _SEP + ("*" if loose else "+")
    for wi, word in enumerate(term.split()):
        if wi:
            parts.append(sep)
        letters = [ch for ch in word if not _is_mark(ch)]
        for i, ch in enumerate(letters):
            if ch == "\u200c":
                parts.append(_SEP + "?")
                continue
            if ch in _CLASS_OF:
                parts.append(_CLASS_OF[ch])
            elif ch.isdecimal():
                parts.append(_digit_class(ch))
            else:
                parts.append(_re2_escape(ch))
            nxt = letters[i + 1] if i + 1 < len(letters) else ""
            if nxt and nxt != "\u200c" and char_script(ch) == "arabic" and char_script(nxt) == "arabic":
                parts.append(_FILL)
    body = "".join(parts)
    if whole_word and det.script not in UNSPACED_SCRIPTS and det.script not in ("none", "japanese"):
        body = "(?:^|[^\\pL\\pN])" + body + "(?:[^\\pL\\pN]|$)"
    if case_insensitive:
        body = "(?i)" + body
    return body


def python_regex(term: str, whole_word: bool = True, loose: bool = False) -> re.Pattern[str]:
    """The same pattern compiled for local filtering (Python ``re`` syntax)."""
    pat = api_regex(term, whole_word, loose, case_insensitive=False)
    pat = pat.replace("[^\\pL\\pN]", "[\\W_]")
    pat = re.sub(r"\\x\{([0-9A-Fa-f]+)\}", lambda m: chr(int(m.group(1), 16)), pat)
    return re.compile(pat, re.IGNORECASE)
