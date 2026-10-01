import re

from gsc_mcp_full.i18n import api_regex, find_layout_mistypes, remap_from_qwerty, remap_to_qwerty, term_frequency, tokenize
from gsc_mcp_full.i18n.regexes import python_regex

# -- keyboard --------------------------------------------------------------------


def test_persian_layout_roundtrip():
    assert remap_from_qwerty("sghl", "fa") == "سلام"
    assert remap_to_qwerty("سلام", "fa") == "sghl"


def test_russian_layout():
    assert remap_from_qwerty("ghbdtn", "ru") == "привет"


def test_unmappable_returns_none():
    assert remap_from_qwerty("sgh1", "fa") is None


def test_mistype_reports_only_the_garbled_side():
    rows = [
        {"query": "سلام", "clicks": 5, "impressions": 50, "position": 3.0},
        {"query": "sghl", "clicks": 0, "impressions": 4, "position": 9.0},
        {"query": "hvac", "clicks": 2, "impressions": 10, "position": 5.0},
    ]
    hits = find_layout_mistypes(rows)
    assert len(hits) == 1
    h = hits[0]
    assert h.query == "sghl" and h.intended == "سلام" and h.matched_query == "سلام" and h.layout == "fa"


def test_reverse_direction_persian_gibberish_for_english_word():
    # «سثخ» is "seo" typed while the layout was still Persian.
    rows = [
        {"query": "seo", "clicks": 50, "impressions": 500, "position": 3.0},
        {"query": "سثخ", "clicks": 0, "impressions": 3, "position": 20.0},
    ]
    hits = find_layout_mistypes(rows)
    assert len(hits) == 1 and hits[0].query == "سثخ" and hits[0].matched_query == "seo"


def test_unmatched_needs_opt_in():
    rows = [{"query": "ghbl", "clicks": 0, "impressions": 2, "position": 30.0}]
    assert find_layout_mistypes(rows) == []
    assert find_layout_mistypes(rows, include_unmatched=True)[0].matched_query is None


# -- regex -----------------------------------------------------------------------


def test_arabic_regex_matches_every_spelling_locally():
    pat = python_regex("کولر گازی")
    for s in ["کولر گازی", "قیمت كولر گازي ارزان", "کولر‌گازی"]:
        assert pat.search(s), s
    assert not pat.search("کولرگازی")  # words must be separated at standard
    assert python_regex("کولر گازی", loose=True).search("کولرگازی")


def test_regex_uses_unicode_boundaries_not_backslash_b():
    r = api_regex("کولر")
    assert "\\b" not in r and "[^\\pL\\pN]" in r


def test_cjk_regex_has_no_boundary():
    assert api_regex("空调") == "(?i)空调"


def test_latin_regex_case_insensitive_flag():
    r = api_regex("hvac design")
    assert r.startswith("(?i)")
    assert re.compile(r.replace("(?i)", "").replace("[\\s\\x{200C}\\x{200D}\\x{00A0}]+", "\\s+").replace("[^\\pL\\pN]", "\\W"), re.I).search("Best HVAC Design")


def test_digits_match_all_scripts():
    pat = python_regex("12000", whole_word=False)
    assert pat.search("۱۲۰۰۰") and pat.search("١٢٠٠٠") and pat.search("12000")


# -- terms -----------------------------------------------------------------------


def test_tokenize_whitespace_and_fallbacks():
    assert tokenize("کولر گازی ارزان")[0] == ["کولر", "گازی", "ارزان"]
    toks, method = tokenize("空调安装")
    assert method in ("jieba", "han-bigrams") and toks
    toks, method = tokenize("エアコン取り付け費用")
    assert method in ("fugashi", "ja-runs") and "エアコン" in toks


def test_term_frequency_merges_spellings_and_drops_stopwords():
    rows = [
        {"query": "کولر گازی", "clicks": 1, "impressions": 100},
        {"query": "قیمت كولر", "clicks": 1, "impressions": 50},
        {"query": "کولر و پکیج", "clicks": 1, "impressions": 10},
    ]
    terms, _ = term_frequency(rows, top=10)
    top = terms[0]
    assert top["term"] in ("کولر", "كولر") and top["queries"] == 3 and top["impressions"] == 160
    assert all(t["term"] != "و" for t in terms)
