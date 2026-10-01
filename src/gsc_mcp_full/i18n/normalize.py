"""Match keys: fold the spellings of one query into one string, per script.

Two levels:

``standard``
    Safe folds only — things that are the *same word* typed differently:
    Unicode compatibility forms, digit scripts, Arabic-script letter variants
    (ي→ی, ك→ک, ة→ه, أ/إ/آ→ا), harakat and tatweel, zero-width characters,
    ё→е, case, separator punctuation, whitespace runs.

``loose``
    Adds folds that merge *near*-spellings: all spaces removed (half-space vs
    space vs nothing in Persian; inconsistent spacing in Korean), Latin and
    Greek diacritics dropped (café/cafe, điều hòa/dieu hoa), hiragana→katakana,
    Simplified↔Traditional Chinese (when OpenCC is installed), ؤ→و, ئ→ی, ء
    dropped, Urdu ے→ی and ھ→ه.

Every fold is applied to the letters of its own script wherever they appear,
so a mixed query such as «خريد iphone 13» is folded exactly like a pure
Persian one. The original text is never changed; only the key is derived.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from .scripts import INDIC_SCRIPTS, Detection, char_script, detect

LEVELS = ("standard", "loose")

_ZERO_WIDTH = frozenset(
    "\u200b\u200c\u200d\u200e\u200f\u2060\ufeff\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\u00ad\u180e"
)
_JOINERS = frozenset("\u200c\u200d")

_ARABIC_STANDARD = str.maketrans(
    {
        "\u064a": "\u06cc",  # ي → ی
        "\u0649": "\u06cc",  # ى → ی
        "\u0643": "\u06a9",  # ك → ک
        "\u0629": "\u0647",  # ة → ه
        "\u06c0": "\u0647",  # ۀ → ه
        "\u0623": "\u0627",  # أ → ا
        "\u0625": "\u0627",  # إ → ا
        "\u0622": "\u0627",  # آ → ا
        "\u0671": "\u0627",  # ٱ → ا
    }
)
_ARABIC_LOOSE = str.maketrans(
    {
        "\u0624": "\u0648",  # ؤ → و
        "\u0626": "\u06cc",  # ئ → ی
        "\u0621": "",  # ء dropped
        "\u06d2": "\u06cc",  # ے → ی (Urdu)
        "\u06be": "\u0647",  # ھ → ه (Urdu)
        "\u06c1": "\u0647",  # ہ → ه (Urdu)
        "\u06c2": "\u0647",  # ۂ → ه (Urdu)
        "\u06cd": "\u06cc",  # ۍ → ی (Pashto)
    }
)
_CYRILLIC_STANDARD = str.maketrans({"ё": "е", "Ё": "Е"})
_LATIN_LOOSE = str.maketrans(
    {"ß": "ss", "ø": "o", "æ": "ae", "œ": "oe", "ł": "l", "đ": "d", "ð": "d", "þ": "th", "ı": "i"}
)
_GREEK_LOOSE = str.maketrans({"ς": "σ"})
_JA_DASHES = frozenset("\u2010\u2011\u2012\u2013\u2014\u2015\u2212\uff0d-")  # things typed for ー
_APOSTROPHES = frozenset("'\u2019\u2018\u02bc`")

_arabic_block = range(0x0600, 0x0700)
_hebrew_block = range(0x0590, 0x0600)


@dataclass(frozen=True)
class Normalized:
    raw: str
    key: str
    level: str
    detection: Detection
    changes: tuple[str, ...]

    @property
    def script(self) -> str:
        return self.detection.script

    @property
    def lang(self) -> str:
        return self.detection.lang


def _fold_digits(s: str) -> str:
    out = []
    for ch in s:
        if ch.isdecimal():
            out.append(str(unicodedata.decimal(ch)))
        else:
            out.append(ch)
    return "".join(out)


def _strip_semitic_marks(s: str) -> str:
    """Drop harakat / niqqud / tatweel. Indic combining marks are NOT touched here."""
    out = []
    for ch in s:
        cp = ord(ch)
        if cp == 0x0640:  # tatweel
            continue
        if (cp in _arabic_block or cp in _hebrew_block) and unicodedata.category(ch).startswith("M"):
            continue
        out.append(ch)
    return "".join(out)


def _strip_diacritics(s: str, scripts: frozenset[str]) -> str:
    """Drop combining marks, but only those sitting on a letter of ``scripts``.

    A blanket strip would delete the vowel signs of Indic scripts, which are
    letters in all but name.
    """
    out = []
    base: str | None = None
    for ch in unicodedata.normalize("NFD", s):
        if unicodedata.combining(ch):
            if base in scripts:
                continue
        else:
            base = char_script(ch)
        out.append(ch)
    return unicodedata.normalize("NFC", "".join(out))


def _kana_to_katakana(s: str) -> str:
    out = []
    for ch in s:
        cp = ord(ch)
        if 0x3041 <= cp <= 0x3096:
            out.append(chr(cp + 0x60))
        else:
            out.append(ch)
    return "".join(out)


def _ja_long_vowel(s: str) -> str:
    """A dash right after kana is almost always a mistyped chōonpu (ー)."""
    out = []
    for i, ch in enumerate(s):
        if ch in _JA_DASHES and i > 0 and (0x3041 <= ord(s[i - 1]) <= 0x30FF):
            out.append("\u30fc")
        else:
            out.append(ch)
    return "".join(out)


_opencc = None


def _to_simplified(s: str) -> str:
    """Traditional → Simplified when OpenCC is installed; otherwise unchanged."""
    global _opencc
    if _opencc is None:
        try:
            from opencc import OpenCC  # type: ignore

            _opencc = OpenCC("t2s")
        except Exception:  # pragma: no cover - optional dependency
            _opencc = False
    if not _opencc:
        return s
    return _opencc.convert(s)


def _fold_punctuation(s: str) -> str:
    """Separator punctuation becomes a space; punctuation that carries meaning stays.

    ``c++``, ``c#`` and ``.net`` are not ``c`` and ``net``; ``3.5`` is not ``35``;
    ``$100`` is not ``100%``. An apostrophe inside a word is dropped so that
    ``don't`` and ``dont`` share a key.
    """
    out: list[str] = []
    n = len(s)
    for i, ch in enumerate(s):
        cat = unicodedata.category(ch)
        if cat[0] not in "PS":
            out.append(ch)
            continue
        prev = out[-1] if out else ""
        nxt = s[i + 1] if i + 1 < n else ""
        if ch in "+#" and (prev.isalnum() or prev in ("+", "#") or nxt.isalnum()):
            out.append(ch)
        elif ch in ".,/:" and prev.isdigit() and nxt.isdigit():
            out.append(ch)
        elif ch == "." and nxt.isalnum() and (not prev or prev == " "):
            out.append(ch)
        elif ch == "&" and prev.isalnum() and nxt.isalnum():
            out.append(ch)
        elif (cat == "Sc" or ch == "%") and (prev.isdigit() or nxt.isdigit()):
            out.append(ch)
        elif ch in _APOSTROPHES and prev.isalpha() and nxt.isalpha():
            continue
        else:
            out.append(" ")
    return "".join(out)


def normalize(raw: str, level: str = "standard", lang_hint: str | None = None) -> Normalized:
    """Compute the match key of ``raw``. See the module docstring for the levels."""
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}, got {level!r}")
    loose = level == "loose"
    changes: list[str] = []

    s = unicodedata.normalize("NFKC", raw)
    if s != raw:
        changes.append("compatibility-forms")

    det = detect(s, lang_hint)
    lang = det.lang
    present = {name for name, _ in det.profile}
    kana = bool(present & {"hiragana", "katakana"})

    folded = _fold_digits(s)
    if folded != s:
        changes.append("digits")
    s = folded

    # Zero-width characters. Joiners carry meaning in Indic scripts — keep them there.
    keep_joiners = bool(present & INDIC_SCRIPTS)
    kept = []
    removed_zwnj = removed_other = False
    for ch in s:
        if ch in _ZERO_WIDTH and not (keep_joiners and ch in _JOINERS):
            if ch == "\u200c":
                removed_zwnj = True
            else:
                removed_other = True
            continue
        kept.append(ch)
    s = "".join(kept)
    if removed_zwnj:
        changes.append("half-space")
    if removed_other:
        changes.append("zero-width")

    if present & {"arabic", "hebrew"}:
        stripped = _strip_semitic_marks(s)
        if stripped != s:
            changes.append("diacritics")
        s = stripped

    if "arabic" in present:
        t = s.translate(_ARABIC_STANDARD)
        if t != s:
            changes.append("letter-forms")
        s = t
        if loose:
            t = s.translate(_ARABIC_LOOSE)
            if t != s:
                changes.append("letter-forms-loose")
            s = t
    if "cyrillic" in present:
        t = s.translate(_CYRILLIC_STANDARD)
        if t != s:
            changes.append("yo")
        s = t
    if kana:
        t = _ja_long_vowel(s)
        if t != s:
            changes.append("long-vowel")
        s = t
        if loose:
            t = _kana_to_katakana(s).replace("\u30fb", "")
            if t != s:
                changes.append("kana")
            s = t
    elif "han" in present and loose:  # kanji in a Japanese query must not be converted
        t = _to_simplified(s)
        if t != s:
            changes.append("simplified")
        s = t

    # Case. Turkish has a dotted and a dotless i that plain casefold() mangles.
    if lang == "tr":
        t = s.replace("I", "ı").replace("İ", "i").lower()
    else:
        t = s.casefold()
    if t != s:
        changes.append("case")
    s = t

    if loose and present & {"latin", "greek"}:
        t = _strip_diacritics(s, frozenset(present & {"latin", "greek"}))
        if "latin" in present:
            t = t.translate(_LATIN_LOOSE)
        if "greek" in present:
            t = t.translate(_GREEK_LOOSE)
        if t != s:
            changes.append("accents")
        s = t

    t = _fold_punctuation(s)
    if t != s:
        changes.append("punctuation")
    s = " ".join(t.split())

    if loose:
        t = s.replace(" ", "")
        if t != s:
            changes.append("spaces")
        s = t

    return Normalized(raw=raw, key=s, level=level, detection=det, changes=tuple(changes))


def match_key(raw: str, level: str = "standard", lang_hint: str | None = None) -> str:
    return normalize(raw, level, lang_hint).key


def group_queries(
    rows: Iterable[dict],
    level: str = "standard",
    lang_hint: str | None = None,
    query_field: str = "query",
) -> list[dict]:
    """Group Search Analytics rows whose queries share a match key.

    Each row needs ``query``, ``clicks``, ``impressions`` and ``position``.
    Returns one dict per group, sorted by impressions, with the summed
    metrics, an impression-weighted position, and the list of variants
    (each with its own metrics and the folds that were applied), most-seen first.
    """
    groups: dict[str, dict] = {}
    for row in rows:
        q = row.get(query_field, "")
        n = normalize(q, level, lang_hint)
        g = groups.get(n.key)
        if g is None:
            g = groups[n.key] = {
                "key": n.key,
                "script": n.script,
                "lang": n.lang,
                "clicks": 0,
                "impressions": 0,
                "_pos_weight": 0.0,
                "variants": [],
            }
        clicks = int(row.get("clicks", 0) or 0)
        imps = int(row.get("impressions", 0) or 0)
        pos = float(row.get("position", 0) or 0)
        g["clicks"] += clicks
        g["impressions"] += imps
        g["_pos_weight"] += pos * imps
        g["variants"].append(
            {"query": q, "clicks": clicks, "impressions": imps, "position": pos, "changes": list(n.changes)}
        )
    out = []
    for g in groups.values():
        imps = g["impressions"]
        g["position"] = round(g["_pos_weight"] / imps, 2) if imps else 0.0
        g["ctr"] = round(g["clicks"] / imps, 4) if imps else 0.0
        del g["_pos_weight"]
        g["variants"].sort(key=lambda v: (-v["impressions"], -v["clicks"]))
        canon = g["variants"][0]
        g["canonical"] = canon["query"]
        g["variant_count"] = len(g["variants"])
        # How each spelling differs from the most-seen one (not from the internal key).
        for v in g["variants"]:
            v["differs"] = [] if v is canon else (sorted(set(v["changes"]) ^ set(canon["changes"])) or v["changes"] or ["spelling"])
        out.append(g)
    out.sort(key=lambda g: (-g["impressions"], -g["clicks"]))
    return out
