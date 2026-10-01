"""Words inside queries — including for scripts that have no spaces.

Chinese, Japanese and Thai queries cannot be split on whitespace. When the
optional segmenters are installed (``pip install gsc-mcp-full[zh]`` / ``[ja]``
/ ``[th]``) they are used; otherwise a script-aware fallback keeps the tool
useful: character bigrams for Chinese, script runs for Japanese, the whole
string for Thai.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from .normalize import normalize
from .scripts import char_script, detect

_STOPWORDS: dict[str, frozenset[str]] = {
    "en": frozenset("the a an of for in to and with on at by from is are or vs".split()),
    "fa": frozenset("و در به از با برای که را های ها یا تا این آن چه چیست".split()),
    "ar": frozenset("في من على و إلى عن مع ما هو هي أو".split()),
    "ru": frozenset("и в на с по для от к о у из за что как".split()),
    "tr": frozenset("ve ile için bir bu ne de da mi mı".split()),
    "de": frozenset("der die das und für mit von in zu ein eine".split()),
    "fr": frozenset("le la les de des du et pour en un une à".split()),
    "es": frozenset("el la los las de del y para en un una".split()),
}

# Terms are compared by match key, so the lists must be in key form too (في → فی, إلى → الی).
_STOPWORDS = {lang: frozenset(normalize(w).key for w in words) for lang, words in _STOPWORDS.items()}

_jieba = _tagger = _thai = None


def _load_jieba():
    global _jieba
    if _jieba is None:
        try:
            import jieba  # type: ignore

            jieba.setLogLevel(60)
            _jieba = jieba
        except Exception:  # pragma: no cover - optional
            _jieba = False
    return _jieba


def _load_fugashi():
    global _tagger
    if _tagger is None:
        try:
            from fugashi import Tagger  # type: ignore

            _tagger = Tagger()
        except Exception:  # pragma: no cover - optional
            _tagger = False
    return _tagger


def _load_thai():
    global _thai
    if _thai is None:
        try:
            from pythainlp.tokenize import word_tokenize  # type: ignore

            _thai = word_tokenize
        except Exception:  # pragma: no cover - optional
            _thai = False
    return _thai


def _han_bigrams(s: str) -> list[str]:
    s = s.replace(" ", "")
    if len(s) <= 2:
        return [s] if s else []
    return [s[i : i + 2] for i in range(len(s) - 1)]


def _ja_runs(s: str) -> list[str]:
    """Split on script changes; hiragana after kanji stays attached (okurigana)."""
    runs: list[str] = []
    cur, prev = "", None
    for ch in s:
        sc = char_script(ch) or ("space" if ch.isspace() else "other")
        if sc == "space":
            if cur:
                runs.append(cur)
            cur, prev = "", None
            continue
        attach = cur and (sc == prev or (sc == "hiragana" and prev == "han"))
        if cur and not attach:
            runs.append(cur)
            cur = ""
        cur += ch
        prev = sc
    if cur:
        runs.append(cur)
    return runs


def tokenize(query: str, lang_hint: str | None = None) -> tuple[list[str], str]:
    """Split ``query`` into terms. Returns ``(terms, method)``.

    ``method`` says how it was done: ``whitespace``, ``jieba``, ``fugashi``,
    ``pythainlp``, ``han-bigrams``, ``ja-runs`` or ``unsegmented``.
    """
    det = detect(query, lang_hint)
    if det.script == "han":
        j = _load_jieba()
        if j:
            return [t for t in j.cut(query) if t.strip()], "jieba"
        return _han_bigrams(query), "han-bigrams"
    if det.script == "japanese":
        t = _load_fugashi()
        if t:
            return [w.surface for w in t(query) if w.surface.strip()], "fugashi"
        return _ja_runs(query), "ja-runs"
    if det.script in ("thai", "lao", "khmer", "myanmar"):
        th = _load_thai() if det.script == "thai" else None
        if th:
            return [t for t in th(query) if t.strip()], "pythainlp"
        return [query.strip()], "unsegmented"
    return query.split(), "whitespace"


def term_frequency(
    rows: Iterable[dict],
    top: int = 30,
    lang_hint: str | None = None,
    min_len: int = 2,
    drop_stopwords: bool = True,
) -> tuple[list[dict], set[str]]:
    """Terms across all queries, weighted by impressions and clicks.

    Returns ``(terms, methods_used)``. Each term dict has ``term``, ``queries``
    (how many distinct queries contain it), ``impressions`` and ``clicks``.
    Terms are compared by their match key so «ماشین» and «ماشين» are one term.
    """
    agg: dict[str, dict] = {}
    methods: set[str] = set()
    for row in rows:
        q = row.get("query", "")
        if not q:
            continue
        terms, method = tokenize(q, lang_hint)
        methods.add(method)
        seen: set[str] = set()
        for t in terms:
            n = normalize(t, "standard", lang_hint)
            k = n.key
            if not k or len(k) < min_len or k in seen or not any(ch.isalpha() for ch in k):
                continue  # also skips bare numbers: «10» and «500» are not terms
            if drop_stopwords and k in _STOPWORDS.get(n.lang or "en", frozenset()):
                continue
            seen.add(k)
            a = agg.setdefault(k, {"term": t, "queries": 0, "impressions": 0, "clicks": 0})
            a["queries"] += 1
            a["impressions"] += int(row.get("impressions", 0) or 0)
            a["clicks"] += int(row.get("clicks", 0) or 0)
    out = sorted(agg.values(), key=lambda a: (-a["impressions"], -a["clicks"], -a["queries"]))
    return out[:top], methods


def queries_containing(rows: Iterable[dict], term: str, level: str = "standard") -> list[dict]:
    """Rows whose query contains ``term`` under match-key comparison (works for CJK)."""
    k = normalize(term, level).key
    if not k:
        return []
    out = []
    for row in rows:
        if k in normalize(row.get("query", ""), level).key:
            out.append(row)
    return out


def group_by_term(rows: Iterable[dict], terms: Iterable[str], level: str = "standard") -> dict[str, list[dict]]:
    keys = {t: normalize(t, level).key for t in terms}
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        qk = normalize(row.get("query", ""), level).key
        for t, k in keys.items():
            if k and k in qk:
                buckets[t].append(row)
    return dict(buckets)
