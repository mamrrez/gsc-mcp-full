from gsc_mcp_full.i18n import detect, group_queries, match_key, normalize


def same(*variants, level="standard"):
    keys = {match_key(v, level) for v in variants}
    assert len(keys) == 1, f"expected one key, got {keys}"


def differ(a, b, level="standard"):
    assert match_key(a, level) != match_key(b, level)


# -- Persian -------------------------------------------------------------------


def test_persian_ye_kaf_forms_fold():
    same("کولر گازی", "كولر گازي", "كولر گازى")


def test_persian_half_space_variants_fold_at_standard():
    # ZWNJ is a spacing choice in Persian; removing it merges «می‌خواهم» with «میخواهم»…
    same("می‌خواهم", "میخواهم")
    # …but not with the spaced form until loose.
    differ("می‌خواهم", "می خواهم")
    same("می‌خواهم", "می خواهم", "میخواهم", level="loose")


def test_persian_and_arabic_indic_digits_fold_to_ascii():
    same("قیمت کولر ۱۲۰۰۰", "قیمت کولر ١٢٠٠٠", "قیمت کولر 12000")


def test_harakat_and_tatweel_are_dropped():
    same("مكيّف", "مكيف", "مكيــف")


def test_persian_detected_by_letters():
    assert detect("پکیج دیواری").lang == "fa"
    assert detect("كولر").lang == "ar"  # Arabic keyboard forms, no Persian-only letter
    assert detect("کولر").lang == "fa"


def test_changes_are_recorded():
    n = normalize("كولر گازي ۱۲")
    assert "letter-forms" in n.changes and "digits" in n.changes


# -- Arabic --------------------------------------------------------------------


def test_arabic_alef_and_ta_marbuta_fold():
    same("أسعار المكيفات", "اسعار المكيفات")
    same("مكيفة", "مكيفه")


def test_arabic_hamza_carriers_only_fold_at_loose():
    differ("مسؤول", "مسوول")
    same("مسؤول", "مسوول", level="loose")


# -- Urdu / Hebrew / Indic -----------------------------------------------------


def test_urdu_detected_and_letters_fold_loose():
    assert detect("ایئر کنڈیشنر").lang == "ur"


def test_hebrew_niqqud_dropped():
    same("מַזְגָּן", "מזגן")


def test_indic_joiners_are_kept():
    # ZWJ/ZWNJ change spelling in Devanagari — must NOT be stripped.
    differ("क‍ष", "कष")


# -- CJK -----------------------------------------------------------------------


def test_halfwidth_katakana_folds_to_fullwidth():
    same("ｴｱｺﾝ", "エアコン")


def test_hiragana_katakana_merge_only_at_loose():
    differ("えあこん", "エアコン")
    same("えあこん", "エアコン", level="loose")


def test_japanese_long_vowel_dash_variants():
    same("エアコン クリーニング", "エアコン クリ－ニング", "エアコン クリ-ニング")


def test_fullwidth_latin_and_digits_fold():
    same("ＨＶＡＣ　２０２６", "hvac 2026")


def test_korean_spacing_merges_at_loose():
    differ("에어컨설치", "에어컨 설치")
    same("에어컨설치", "에어컨 설치", level="loose")


def test_han_script_and_lang():
    d = detect("空调安装")
    assert d.script == "han" and d.lang == "zh"
    assert detect("エアコン取り付け").lang == "ja"
    assert detect("에어컨").lang == "ko"


# -- Latin / Cyrillic / Greek --------------------------------------------------


def test_turkish_dotted_i():
    assert match_key("İstanbul klima") == "istanbul klima"
    assert match_key("ISPARTA klima", lang_hint="tr") == "ısparta klima"


def test_latin_accents_only_fold_at_loose():
    differ("điều hòa", "dieu hoa")
    same("điều hòa", "dieu hoa", level="loose")
    same("café", "cafe", level="loose")
    same("straße", "strasse", level="loose")


def test_russian_yo():
    same("ёлка", "елка")


def test_greek_final_sigma_and_tonos_loose():
    same("κλιματιστικός", "κλιματιστικοσ", level="loose")


def test_case_punctuation_whitespace():
    same("HVAC-Design", "hvac design", "  hvac   design ")


# -- grouping ------------------------------------------------------------------


def test_group_queries_sums_and_weights_position():
    rows = [
        {"query": "کولر گازی", "clicks": 10, "impressions": 100, "position": 2.0},
        {"query": "كولر گازي", "clicks": 1, "impressions": 20, "position": 4.0},
        {"query": "پکیج", "clicks": 3, "impressions": 30, "position": 5.0},
    ]
    g = group_queries(rows)
    assert g[0]["canonical"] == "کولر گازی"
    assert g[0]["impressions"] == 120 and g[0]["clicks"] == 11
    assert g[0]["position"] == round((2.0 * 100 + 4.0 * 20) / 120, 2)
    assert g[0]["variant_count"] == 2 and g[1]["variant_count"] == 1
    assert g[0]["variants"][1]["changes"] == ["letter-forms"]
