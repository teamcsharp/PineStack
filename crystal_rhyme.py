"""Positive, inspectable terminal-rhyme evidence from a pinned local CMUdict.

This module never rejects speech or judges meaning. Missing/modified dictionary
data yields no new evidence, leaving the caller's existing rhyme rules intact.
Only final words of supplied bars are considered; no internal-word search.
"""
from __future__ import annotations

import hashlib
import re
import threading
from functools import lru_cache
from pathlib import Path


DICTIONARY_VERSION = "74790861f652b15e4ac49015a90074ad62a27690"
DICTIONARY_SHA256 = "81917843c7f44ce2b094ac63873c2c7a4cf802040792c455ba3ca406891c3d22"
_PATH = Path(__file__).resolve().parent / "vendor" / "cmudict" / "cmudict.dict"
_MAX_BYTES = 4_000_000
_LOCK = threading.RLock()
_LINES: tuple[bytes, ...] | None = None
_ERROR = ""
_WORD = re.compile(r"[a-z][a-z']*")
_VARIANT = re.compile(rb"\(\d+\)$")
_PHONE = re.compile(r"(?:AA|AE|AH|AO|AW|AY|EH|ER|EY|IH|IY|OW|OY|UH|UW)[012]|(?:B|CH|D|DH|F|G|HH|JH|K|L|M|N|NG|P|R|S|SH|T|TH|V|W|Y|Z|ZH)")


def _entry_word(line: bytes) -> bytes:
    return _VARIANT.sub(b"", line.split(b" ", 1)[0])


def _dictionary() -> tuple[bytes, ...]:
    global _LINES, _ERROR
    with _LOCK:
        if _LINES is not None:
            return _LINES
        try:
            # Hash verification and the byte ceiling happen once. Keeping raw
            # lines avoids a Python phone object graph for 135,000 entries.
            with _PATH.open("rb") as handle:
                data = handle.read(_MAX_BYTES + 1)
            if len(data) > _MAX_BYTES:
                raise ValueError("dictionary exceeds the pinned resource ceiling")
            if hashlib.sha256(data).hexdigest() != DICTIONARY_SHA256:
                raise ValueError("dictionary hash does not match the pinned version")
            _LINES = tuple(sorted((line for line in data.splitlines()
                                   if line and not line.startswith(b";;;")), key=_entry_word))
        except (OSError, ValueError) as exc:
            _ERROR = str(exc)
            _LINES = ()  # No repeated filesystem retry in a grading loop.
        return _LINES


@lru_cache(maxsize=2048)
def _pronunciations(word: str) -> tuple[tuple[tuple[str, ...], tuple[str, ...], int], ...]:
    lines = _dictionary()
    key = word.encode("ascii", "ignore")
    low, high = 0, len(lines)
    while low < high:
        mid = (low + high) // 2
        if _entry_word(lines[mid]) < key:
            low = mid + 1
        else:
            high = mid
    found = []
    while low < len(lines) and _entry_word(lines[low]) == key:
        phones = tuple(lines[low].split(b"#", 1)[0].decode("ascii").split()[1:])
        if not phones or any(_PHONE.fullmatch(phone) is None for phone in phones):
            low += 1
            continue
        stressed = [i for i, phone in enumerate(phones) if phone[-1:] in ("1", "2")]
        if stressed:
            tail = phones[stressed[-1]:]
            nuclei = sum(phone[-1:].isdigit() for phone in tail)
            found.append((phones, tuple(re.sub(r"[012]$", "", p) for p in tail), nuclei))
        low += 1
    return tuple(found)


def terminal_rhymes(bars, *, normalize=None, excluded=(), required_depth=None) -> dict:
    """Return at most four proven end pairs, with words, positions and phones.

    The caller supplies its existing word-equivalence, stop-word and suffix
    depth guards. Matching includes every phone from the final stressed vowel;
    an unstressed suffix alone cannot manufacture a rhyme. Any documented
    pronunciation may supply evidence, which is reported explicitly.
    """
    normalize = normalize or (lambda word: re.sub(r"[^a-z]", "", word.lower()))
    required_depth = required_depth or (lambda _word: 1)
    excluded = set(excluded)
    groups, matches, seen = {}, [], set()
    for position, bar in enumerate(bars):
        text = str(bar).lower().replace("\u2019", "'")
        tokens = list(_WORD.finditer(text))
        if not tokens:
            continue
        final = tokens[-1]
        # Numbers and unknown letter forms are spoken endpoints too. Do not
        # promote an earlier English word (or the letters in move42) to one.
        if (any(char.isalnum() for char in text[final.end():])
                or final.start() and text[final.start() - 1].isalnum()):
            continue
        word = final.group().strip("'")
        normal = normalize(word)
        # A dictionary-proven lexical two-letter endpoint such as go is a
        # real rhyme. Function words still follow the caller's excluded set.
        if word in excluded or len(normal) < 2:
            continue
        depth = max(1, int(required_depth(word)))
        for phones, tail, nuclei in _pronunciations(word):
            if nuclei < depth:
                continue
            group = groups.setdefault(tail, {})
            for other_normal, previous in group.items():
                if other_normal == normal:
                    continue
                for index, other_word, other_phones in previous:
                    pair = frozenset((other_normal, normal))
                    if pair in seen:
                        continue
                    seen.add(pair)
                    matches.append({"words": [other_word, word], "bars": [index, position],
                                    "phones": [list(other_phones), list(phones)],
                                    "rhyme_phones": list(tail)})
                    if len(matches) == 4:
                        return _result(matches)
            # Repeated tags can be arbitrarily common. One retained position
            # per normalized word suffices for distinct unordered pair proof.
            previous = group.setdefault(normal, [])
            if not previous:
                previous.append((position, word, phones))
    return _result(matches)


def _result(matches: list[dict]) -> dict:
    return {"pairs": matches, "dictionary": {"name": "CMUdict",
            "version": DICTIONARY_VERSION, "sha256": DICTIONARY_SHA256,
            "available": bool(_LINES), "error": _ERROR}}
