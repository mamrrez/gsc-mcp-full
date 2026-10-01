"""Script and language detection by Unicode block.

Cheap and dependency-free. It is exact for *script* (a character is either in
the Arabic block or it is not) and a heuristic for *language* within a script:
Persian, Arabic and Urdu share the Arabic script but each has letters the
others do not use, which is enough to tell them apart most of the time.
Latin-script languages are the least reliable and are only guessed when a
language has distinctive letters (Turkish, Vietnamese).
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from dataclasses import dataclass

# (low, high, script) — inclusive ranges, checked in order.
_RANGES: tuple[tuple[int, int, str], ...] = (
    (0x0600, 0x06FF, "arabic"),
    (0x0750, 0x077F, "arabic"),
    (0x08A0, 0x08FF, "arabic"),
    (0xFB50, 0xFDFF, "arabic"),
    (0xFE70, 0xFEFF, "arabic"),
    (0x0590, 0x05FF, "hebrew"),
    (0xFB1D, 0xFB4F, "hebrew"),
    (0x0400, 0x052F, "cyrillic"),
    (0x0370, 0x03FF, "greek"),
    (0x1F00, 0x1FFF, "greek"),
    (0x0530, 0x058F, "armenian"),
    (0x10A0, 0x10FF, "georgian"),
    (0x1200, 0x137F, "ethiopic"),
    (0x0900, 0x097F, "devanagari"),
    (0x0980, 0x09FF, "bengali"),
    (0x0A00, 0x0A7F, "gurmukhi"),
    (0x0A80, 0x0AFF, "gujarati"),
    (0x0B00, 0x0B7F, "odia"),
    (0x0B80, 0x0BFF, "tamil"),
    (0x0C00, 0x0C7F, "telugu"),
    (0x0C80, 0x0CFF, "kannada"),
    (0x0D00, 0x0D7F, "malayalam"),
    (0x0D80, 0x0DFF, "sinhala"),
    (0x0E00, 0x0E7F, "thai"),
    (0x0E80, 0x0EFF, "lao"),
    (0x1000, 0x109F, "myanmar"),
    (0x1780, 0x17FF, "khmer"),
    (0x3040, 0x309F, "hiragana"),
    (0x30A0, 0x30FF, "katakana"),
    (0x31F0, 0x31FF, "katakana"),
    (0xFF66, 0xFF9F, "katakana"),
    (0x3005, 0x3007, "han"),  # 々 〆 〇
    (0x2E80, 0x2FDF, "han"),
    (0x3400, 0x4DBF, "han"),
    (0x4E00, 0x9FFF, "han"),
    (0xF900, 0xFAFF, "han"),
    (0x20000, 0x2FA1F, "han"),
    (0x1100, 0x11FF, "hangul"),
    (0x3130, 0x318F, "hangul"),
    (0xA960, 0xA97F, "hangul"),
    (0xAC00, 0xD7FF, "hangul"),
)

#: Scripts whose zero-width joiner / non-joiner change how a word is written.
#: They must never be stripped there (unlike Persian, where ZWNJ is a spacing choice).
INDIC_SCRIPTS = frozenset(
    {"devanagari", "bengali", "gurmukhi", "gujarati", "odia", "tamil", "telugu", "kannada", "malayalam", "sinhala"}
)

#: Scripts written without spaces between words.
UNSPACED_SCRIPTS = frozenset({"han", "hiragana", "katakana", "thai", "lao", "khmer", "myanmar"})

# Letters that only one language of the Arabic script uses.
_PERSIAN_ONLY = frozenset("پچژگ")
_PERSIAN_FORMS = frozenset("یک")  # ی ک (Persian keyboard)
_ARABIC_FORMS = frozenset("يكةى")  # ي ك ة ى (Arabic keyboard)
_URDU_ONLY = frozenset("ٹڈڑںےھۃ")
_PASHTO_ONLY = frozenset("ټډړږښګڼ")
_UKRAINIAN_ONLY = frozenset("іїєґІЇЄҐ")
_TURKISH_ONLY = frozenset("ğışİĞŞ")
_VIETNAMESE_ONLY = frozenset("ăâđêôơưĂÂĐÊÔƠƯạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳýỵỷỹ")


def char_script(ch: str) -> str | None:
    """Script of one character, or ``None`` for digits, punctuation and spaces."""
    cp = ord(ch)
    for lo, hi, name in _RANGES:
        if lo <= cp <= hi:
            cat = unicodedata.category(ch)
            # Marks and punctuation inside a block still belong to that script,
            # but we only count letters for profiling.
            return name if cat[0] in "LM" else None
    if ch.isalpha():
        return "latin" if cp < 0x0250 or 0x1E00 <= cp <= 0x1EFF or 0xFF21 <= cp <= 0xFF5A else "other"
    return None


def script_profile(text: str) -> Counter[str]:
    """How many letters of each script the text contains."""
    profile: Counter[str] = Counter()
    for ch in text:
        s = char_script(ch)
        if s:
            profile[s] += 1
    return profile


def dominant_script(text: str) -> str:
    """The script most of the letters belong to; ``"none"`` if there are no letters.

    Japanese text mixes han and kana; both are reported as ``"japanese"`` when
    any kana is present, because that is the only useful answer.
    """
    profile = script_profile(text)
    if not profile:
        return "none"
    if profile.get("hiragana") or profile.get("katakana"):
        return "japanese"
    return profile.most_common(1)[0][0]


@dataclass(frozen=True)
class Detection:
    script: str  # e.g. "arabic", "latin", "japanese", "han", "none"
    lang: str  # BCP-47-ish guess: "fa", "ar", "ja", "zh", ... or "" when unknown
    mixed: bool  # letters of more than one script (excluding kanji+kana)
    profile: tuple[tuple[str, int], ...]

    @property
    def rtl(self) -> bool:
        return self.script in ("arabic", "hebrew")


_WEAK_GUESSES = frozenset({"ru", "hi", "zh"})  # the default for a script shared by several languages


def _guess_lang(script: str, text: str, profile: Counter[str]) -> str:
    chars = set(text)
    if script == "arabic":
        if chars & _URDU_ONLY:
            return "ur"
        if chars & _PASHTO_ONLY:
            return "ps"
        persian = bool(chars & _PERSIAN_ONLY)
        p_forms = bool(chars & _PERSIAN_FORMS)
        a_forms = bool(chars & _ARABIC_FORMS)
        if persian or (p_forms and not a_forms):
            return "fa"
        if a_forms and not p_forms:
            return "ar"
        return "fa" if p_forms else ""  # both keyboards mixed, or no telling letter
    if script == "japanese":
        return "ja"
    if script == "han":
        return "zh"
    if script == "hangul":
        return "ko"
    if script == "hebrew":
        return "he"
    if script == "thai":
        return "th"
    if script == "devanagari":
        return "hi"
    if script == "bengali":
        return "bn"
    if script == "greek":
        return "el"
    if script == "cyrillic":
        return "uk" if chars & _UKRAINIAN_ONLY else "ru"
    if script == "latin":
        if chars & _VIETNAMESE_ONLY:
            return "vi"
        if chars & _TURKISH_ONLY:
            return "tr"
        return ""
    if script in ("lao", "khmer", "myanmar", "tamil", "telugu", "kannada", "malayalam", "gujarati", "gurmukhi", "odia", "sinhala", "armenian", "georgian", "ethiopic"):
        return {
            "lao": "lo", "khmer": "km", "myanmar": "my", "tamil": "ta", "telugu": "te", "kannada": "kn",
            "malayalam": "ml", "gujarati": "gu", "gurmukhi": "pa", "odia": "or", "sinhala": "si",
            "armenian": "hy", "georgian": "ka", "ethiopic": "am",
        }[script]
    return ""


def _strong_arabic(text: str) -> bool:
    """Arabic beyond keyboard forms: ة, hamza-carrying alefs, or the article ال.

    ي and ك alone only say the *keyboard* was Arabic — Persian typed on an Arabic
    layout is the commonest source of split queries — so they are a weak signal.
    """
    if set(text) & set("\u0629\u0623\u0625"):
        return True
    return any(w.startswith("\u0627\u0644") and len(w) > 3 for w in text.split())


def detect(text: str, lang_hint: str | None = None) -> Detection:
    """Script and language guess for ``text``.

    ``lang_hint`` (e.g. ``"fa"``) overrides the language guess when the script
    agrees with it — useful when the site's language is known and a query has
    no distinguishing letters.
    """
    profile = script_profile(text)
    script = dominant_script(text)
    letters = sum(profile.values())
    top = profile.most_common()
    if script == "japanese":
        non_ja = letters - profile.get("han", 0) - profile.get("hiragana", 0) - profile.get("katakana", 0)
        mixed = non_ja > 0
    else:
        mixed = len(top) > 1 and top[1][1] > 0
    lang = _guess_lang(script, text, profile)
    if lang_hint:
        # A hint settles what the letters cannot: it replaces an empty or weak guess,
        # never a query that plainly is another language (Urdu on a Persian site stays Urdu).
        code = lang_hint.lower().split("-")[0]
        hint_script = _SCRIPT_OF_LANG.get(code, "latin")  # every language not listed is Latin-script
        same_script = hint_script == script or (hint_script == "japanese" and script == "han")
        weak = not lang or lang in _WEAK_GUESSES or (lang == "ar" and not _strong_arabic(text))
        if same_script and weak:
            lang = code
    return Detection(script=script, lang=lang, mixed=mixed, profile=tuple(top))


_SCRIPT_OF_LANG = {
    "fa": "arabic", "ar": "arabic", "ur": "arabic", "ps": "arabic", "ku": "arabic",
    "he": "hebrew", "yi": "hebrew",
    "ja": "japanese", "zh": "han", "ko": "hangul", "th": "thai", "lo": "lao", "km": "khmer", "my": "myanmar",
    "hi": "devanagari", "mr": "devanagari", "ne": "devanagari", "bn": "bengali", "pa": "gurmukhi", "gu": "gujarati",
    "ta": "tamil", "te": "telugu", "kn": "kannada", "ml": "malayalam", "si": "sinhala",
    "ru": "cyrillic", "uk": "cyrillic", "bg": "cyrillic", "sr": "cyrillic", "kk": "cyrillic",
    "el": "greek", "hy": "armenian", "ka": "georgian", "am": "ethiopic",
}
# Every other language is Latin-script.
