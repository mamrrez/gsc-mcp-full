"""Multilingual query handling.

Search Console reports every distinct *string* as its own query. In most
languages the same search is typed several ways, so one real keyword is spread
across several rows and looks smaller and noisier than it is. This package
computes a *match key* per query so those rows can be grouped — and never
rewrites the original text, which is what the user actually sees.

Public surface:

- :func:`detect` — script + language guess for a string
- :func:`normalize` — the match key, with a record of what was folded
- :func:`group_queries` — group rows by match key
- :func:`api_regex` — a Search Console (RE2) regex that matches every spelling
- :func:`find_layout_mistypes` — queries typed with the keyboard on the wrong layout
- :func:`tokenize` / :func:`term_frequency` — words, including for scripts without spaces
"""

from .keyboard import LAYOUTS, find_layout_mistypes, remap_from_qwerty, remap_to_qwerty
from .normalize import Normalized, group_queries, match_key, normalize
from .regexes import api_regex
from .scripts import Detection, detect, dominant_script, script_profile
from .terms import term_frequency, tokenize

__all__ = [
    "LAYOUTS",
    "Detection",
    "Normalized",
    "api_regex",
    "detect",
    "dominant_script",
    "find_layout_mistypes",
    "group_queries",
    "match_key",
    "normalize",
    "remap_from_qwerty",
    "remap_to_qwerty",
    "script_profile",
    "term_frequency",
    "tokenize",
]
