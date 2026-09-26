"""Small contextual additions to segment checks; no global editorial policy."""
from __future__ import annotations

import re
import unicodedata


_WORDS = re.compile(r"[^\W_]+(?:'[^\W_]+)*", re.UNICODE)
_GENERIC = frozenset('a an the our your this that live station service services product products server running on own one of for voice cloning clone'.split())
_SALE = re.compile(r'\b(?:sign\s+up|subscribe|place\s+(?:an|your)\s+order|order\s+now|pay\s+(?:through|at)|get\s+yours|book\s+now|purchase|enro[l]{1,2})\b', re.I)
_NEGATIVE = re.compile(r"\b(?:not|never|avoid|cannot|can't|don't|won't|shouldn't|mustn't|without)\b", re.I)
WORDS_PER_MINUTE = 155


def normalize_role(role: str) -> str:
    """Normalize screenplay labels to the station's role names."""
    key = _normal(role).strip().strip(":")
    aliases = {
        "a": "dj",
        "host": "dj",
        "dj": "dj",
        "b": "cohost",
        "co-host": "cohost",
        "cohost": "cohost",
        "c": "caller",
        "caller": "caller",
        "d": "third",
        "third": "third",
        "e": "caller2",
        "caller2": "caller2",
        "caller 2": "caller2",
    }
    return aliases.get(key, key)


def _normal(text):
    return unicodedata.normalize('NFKC', str(text or '')).replace('’', "'").casefold()


def ad_sale_evidence(script: str, product: str = '') -> dict:
    """Recognize an expected product with an affirmative sale instruction.

    The known product's short leading identity must be present. Generic product
    descriptions, an unrelated product, a name alone, or a negated sale do not
    gain permission from this supplemental check. Existing ad-quality and
    source-fidelity checks remain the caller's responsibility.
    """
    if not isinstance(script, str) or not isinstance(product, str):
        raise TypeError('script and product must be strings')
    prefix = re.split(r'[,;:\n—–]|\s+-\s+', product.strip(), maxsplit=1)[0]
    terms = [word for word in _WORDS.findall(_normal(prefix)) if word not in _GENERIC]
    terms = list(dict.fromkeys(terms))
    # A long descriptive clause is not an identified product name. Do not
    # infer one by accepting an arbitrary content word from its description.
    if len(_WORDS.findall(prefix)) > 8:
        terms = []
    text = _normal(script)
    words = set(_WORDS.findall(text))
    matched = [term for term in terms if term in words]
    actions = []
    if terms and len(matched) == len(terms):
        for match in _SALE.finditer(text):
            clause_start = max(text.rfind(char, 0, match.start()) for char in '.!?;/\n') + 1
            before = ' '.join(_WORDS.findall(text[clause_start:match.start()])[-8:])
            if _NEGATIVE.search(before):
                continue
            actions.append(match.group())
    return {'ok': bool(actions), 'identity_terms': terms, 'matched_identity': matched,
            'sale_actions': list(dict.fromkeys(actions)),
            'basis': 'Expected product identity plus affirmative sale action',
            'limitations': 'This recognizes sale wording; it does not prove price accuracy, source fidelity or overall ad quality.'}
