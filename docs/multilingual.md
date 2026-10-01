---
title: Languages
nav_order: 5
description: Every normalisation rule, per script, and why each one is standard or loose.
---

# Languages
{: .no_toc }

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

## The idea

Every query gets a **match key**. Two queries with the same key are one keyword. The key is computed from the text with rules that depend on the script; the displayed text is **never changed** — you always see what people typed, and the most-seen spelling is shown as the group's name.

Two levels:

- **standard** — folds only things that are the *same word typed differently*. Safe to apply always. Used by every tool by default.
- **loose** — also merges *near*-spellings that are usually, but not always, the same search. Ask for it (`level=loose`) when you want the fuller picture.

The rules are per script because the same operation can be right in one language and wrong in another (see [Joiners](#joiners-are-not-always-noise)). Each rule is applied to the letters of its own script wherever they appear, so a mixed query — «خريد iphone 13», «قيمت BMW X5» — is folded exactly like a pure Persian one. On most non-English sites those brand-and-model queries are the valuable ones.

## Steps applied to every query

1. **Unicode compatibility normalisation (NFKC)** — full-width `ＡＢＣ１２３` → `ABC123`, half-width `ｴｱｺﾝ` → `エアコン`, Arabic presentation forms → base letters, ligatures.
2. **Digits** — `۱۲۰۰۰`, `١٢٠٠٠`, `१२०००` and every other Unicode decimal digit → `12000`.
3. **Zero-width characters** removed (ZWNJ, ZWJ, ZWSP, BOM, bidi marks) — *except* joiners in Indic scripts.
4. **Case** — Unicode casefold, with a Turkish exception (below).
5. **Separator punctuation** → space; whitespace runs collapsed; edges trimmed. Punctuation that carries meaning is kept: `c++`, `c#` and `.net` stay distinct from `c` and `net`, `3.5` is not `35`, `$100` is not `100%`, `at&t` keeps its `&`. An apostrophe inside a word is dropped, so `don't` = `dont`.
6. (loose) **All spaces removed.**

## Arabic script — Persian, Arabic, Urdu, Pashto, Kurdish

| Rule | Level | Why |
|---|---|---|
| ي (U+064A) → ی (U+06CC), ى → ی | standard | Arabic-keyboard vs Persian-keyboard forms of the same letter |
| ك (U+0643) → ک (U+06A9) | standard | same |
| ة, ۀ → ه | standard | ta marbuta / he-with-hamza typed as plain he |
| أ إ آ ٱ → ا | standard | alef with hamza/madda often typed bare |
| Harakat (fatha, kasra, shadda, sukun…) removed | standard | vowel marks are optional in normal writing |
| Tatweel (ـ) removed | standard | decorative stretching |
| ZWNJ (half-space) removed | standard | «می‌خواهم» = «میخواهم» — a spacing preference, not a spelling |
| ؤ → و, ئ → ی, ء dropped | loose | hamza carriers are real letters but frequently dropped |
| Urdu ے → ی, ھ/ہ/ۂ → ه; Pashto ۍ → ی | loose | letters specific to those languages, folded only on request |
| space ↔ half-space ↔ nothing | loose | «ماشین دست دوم» = «ماشین دستدوم» |

**Persian vs Arabic detection.** The script is the same; the language is guessed from letters only one uses: پ چ ژ گ ی ک mean Persian; ة ى ك ي mean an Arabic keyboard (which a Persian speaker may also be using). A query that only shows which *keyboard* was used (ي and ك, nothing else) is the ambiguous case — Persian typed on an Arabic layout is the commonest source of split queries — and `GSC_LANG=fa` (or `ar`) decides it. A query that is plainly another language keeps its own label: Urdu on a Persian site stays Urdu. Detection only affects labels — the folds are identical.

**Finglish / Arabizi** (Persian or Arabic written in Latin letters, e.g. `koolere gazi`, `mukayyif`) is **not** merged with the native script. Transliteration is many-to-many and would create false merges; use `brand_split` / `query_filter` with both spellings when you need them together.

## Chinese

| Rule | Level |
|---|---|
| Full-width ↔ half-width letters, digits, punctuation | standard |
| Traditional → Simplified (`空調` = `空调`) | loose, needs the `zh` extra (OpenCC) |

Queries have no spaces; `query_filter` and `history_query` match by substring of the key, so `空调` finds `空调安装价格` without word boundaries. `top_terms` segments with **jieba** when installed, else character bigrams.

{: .note }
Simplified and Traditional readers are different markets. The fold is loose so you can keep them apart by default.

## Japanese

| Rule | Level |
|---|---|
| Half-width katakana → full-width | standard |
| A dash typed right after kana → chōonpu (`クリ－ニング` → `クリーニング`) | standard |
| Hiragana → katakana (`えあこん` = `エアコン`) | loose |
| Middle dot (・) removed | loose |

`top_terms` segments with **fugashi** (MeCab) when installed, else splits on script changes with okurigana kept attached to its kanji.

## Korean

Hangul is composed (NFC). Spacing in Korean queries is inconsistent (`에어컨설치` / `에어컨 설치`), so spaces are merged at **loose**.

## Thai, Lao, Khmer, Burmese

No spaces between words. Substring matching works as for Chinese. Thai segmentation uses **pythainlp** when installed; otherwise the whole query is one term in `top_terms`.

## Indic scripts — Hindi, Bengali, Tamil, Telugu…

Combining vowel signs are **never** stripped (they are letters, not decoration).

### Joiners are not always noise
{: .no_toc }

ZWNJ/ZWJ are removed for Persian because they only affect spacing there. In Devanagari and other Indic scripts they change how a conjunct is written and can distinguish words, so they are **kept** — the one place where a "clean up invisible characters" step would corrupt data.

## Hebrew

Niqqud (vowel points) removed at standard. Final letter forms (ך ם ן ף ץ) are left alone: they are determined by position, not by typing habit.

## Latin-script languages

| Rule | Level | Languages |
|---|---|---|
| Case | standard | all |
| **Turkish i**: `İ` → `i`, `I` → `ı` before lowercasing | standard | detected by ğ ş ı İ, or `GSC_LANG=tr` |
| Accents and diacritics stripped (`café` = `cafe`, `điều hòa` = `dieu hoa`) | loose | all — Vietnamese users very often drop tone marks |
| `ß` → `ss`, `ø` → `o`, `æ` → `ae`, `œ` → `oe`, `ł` → `l`, `đ` → `d` | loose | German, Nordic, Polish, Vietnamese |

Python's default `lower()` turns Turkish `İ` into `i` followed by a combining dot — a different string. The Turkish rule is exactly why the case step is script-aware.

## Cyrillic and Greek

- `ё` → `е` at standard (Russian users type either; Ukrainian is detected by і ї є ґ).
- Greek: accents and final sigma (`ς` → `σ`) at loose.

## Wrong keyboard layout

`keyboard_mistypes` maps a query through the two Persian layouts in common use (they differ on where پ sits), plus the Arabic, Russian and Hebrew standard layouts (QWERTY position → letter) in both directions. A hit is reported only when the remapped text has the same match key as **a query that really exists in your data** (`ovdn lhadk` → «خرید ماشین», which you also rank for). With `include_unmatched=True` it also lists vowel-less Latin queries that map cleanly to a layout; those are guesses.

## Regex filters

Search Console's regex filter (API and UI) uses RE2, whose `\b` only knows ASCII letters. `\bماشین\b` matches nothing. `build_query_regex` returns a pattern with `(?:^|[^\pL\pN])…(?:[^\pL\pN]|$)` boundaries and, for Arabic script, character classes for every letter with more than one spelling plus optional harakat between letters and optional half-spaces. Every tool's `query_filter` parameter uses the same builder automatically, so «ماشین» finds «ماشين» in the API call itself. The pattern is case-insensitive and covers Arabic-script letter forms, vowel marks, tatweel, half-spaces, digit scripts and Cyrillic е/ё. It does not cover dropped accents (café/cafe) or kana variants — those are merged afterwards by the grouping, at `level=loose`.

## Limits — what it does not do

- No transliteration between scripts (Finglish, Arabizi, romaji, pinyin).
- No stemming or synonyms — «ماشین» and «ماشین‌ها» are different keys.
- Language *detection* is by letters used, so a Latin-script query with no distinctive letters is just "latin".
- Segmentation without the extras is approximate.

If you have real query pairs the rules get wrong, [open an issue](https://github.com/mamrrez/gsc-mcp-full/issues) with the pair and the language — that is the most useful contribution there is.
