"""clip_senses - the other words for a thing, so the SFX guy can find it.

[#1386] "i want the sfx guy also going by synonyms, antonyms and even
entendre to find clips appropriate."

The matcher scores a clip on the words it shares with the line. That is
literal: a line about a CAR never reaches a clip about an AUTOMOBILE, and
a line about somebody being BRAVE never reaches the one that says COWARD -
which is the funnier answer and the one a person in the booth would pick.

WordNet is already vendored here (vendor/wordnet, read by
crystal_contract.py), so the senses cost a file read rather than a model.

THREE WIDENINGS, and they are NOT the same weight:

  synonym   the same thing said differently. Nearly as good as the word
            itself, so it scores just under it.
  antonym   the opposite. Worth much less on average and worth a great
            deal occasionally, because the joke is very often the
            opposite - the station says "we are completely in control"
            and the right clip says "everything is on fire". Kept, and
            marked, so `explain()` can say WHY it was chosen.
  entendre  a word with several unrelated senses is a word a clip can be
            funny about. WordNet already knows how many senses a word has
            and cntlist.rev knows how often each is meant; a word whose
            second sense is common is a pun waiting to happen.

Nothing here reads a clock, a socket or a global, and nothing loops: the
caller decides how wide to go.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable

BASE = Path(__file__).resolve().parent / "vendor" / "wordnet"

# What a widened word is worth against the word itself.
SYNONYM = 0.72
ANTONYM = 0.34
MOST_PER_WORD = 6

_INDEX: dict[str, dict[str, list[str]]] = {}
_DATA: dict[str, dict[str, str]] = {}
_MEMO: dict[str, tuple] = {}

POS = ("noun", "verb", "adj", "adv")


def _index(pos: str) -> dict[str, list[str]]:
    """word -> its synset offsets, out of index.<pos>."""
    got = _INDEX.get(pos)
    if got is not None:
        return got
    out: dict[str, list[str]] = {}
    try:
        with (BASE / ("index." + pos)).open(encoding="utf-8",
                                            errors="replace") as fh:
            for line in fh:
                if line.startswith("  ") or not line.strip():
                    continue
                bits = line.split()
                if len(bits) < 6:
                    continue
                word = bits[0].replace("_", " ")
                # the offsets are the trailing all-digit fields
                offs = [b for b in bits[::-1] if b.isdigit() and len(b) == 8]
                if offs:
                    out[word] = offs
    except OSError:
        out = {}
    _INDEX[pos] = out
    return out


def _data(pos: str) -> dict[str, str]:
    """offset -> its raw synset line, out of data.<pos>."""
    got = _DATA.get(pos)
    if got is not None:
        return got
    out: dict[str, str] = {}
    try:
        with (BASE / ("data." + pos)).open(encoding="utf-8",
                                           errors="replace") as fh:
            for line in fh:
                if line.startswith("  ") or not line.strip():
                    continue
                off = line.split(" ", 1)[0]
                if off.isdigit():
                    out[off] = line
    except OSError:
        out = {}
    _DATA[pos] = out
    return out


def _synset_words(line: str) -> list[str]:
    """The words of one synset line."""
    try:
        head = line.split("|", 1)[0].split()
        # offset lex_filenum ss_type w_cnt word lex_id [word lex_id...]
        count = int(head[3], 16)
        out: list[str] = []
        at = 4
        for _ in range(count):
            if at >= len(head):
                break
            out.append(head[at].replace("_", " ").lower())
            at += 2
        return out
    except (ValueError, IndexError):
        return []


def _pointers(line: str, symbol: str) -> list[tuple[str, str]]:
    """(offset, pos) for every pointer of this kind on the line."""
    try:
        head = line.split("|", 1)[0].split()
        count = int(head[3], 16)
        at = 4 + count * 2
        if at >= len(head):
            return []
        n = int(head[at])
        at += 1
        out: list[tuple[str, str]] = []
        for _ in range(n):
            if at + 3 >= len(head):
                break
            sym, off, pos = head[at], head[at + 1], head[at + 2]
            if sym == symbol:
                out.append((off, {"n": "noun", "v": "verb",
                                  "a": "adj", "s": "adj",
                                  "r": "adv"}.get(pos, "noun")))
            at += 4
        return out
    except (ValueError, IndexError):
        return []


def senses(word: Any) -> int:
    """How many distinct senses this word has. A high count is a word a
    clip can be funny about - the entendre signal."""
    body = " ".join(str(word or "").lower().split())
    if not body:
        return 0
    return sum(len(_index(pos).get(body) or []) for pos in POS)


def widen(word: Any, most: int = MOST_PER_WORD) -> dict[str, float]:
    """{other word -> what it is worth}, for one word.

    The word itself is not in the answer: the caller already has it, and
    at full weight."""
    body = " ".join(str(word or "").lower().split())
    if len(body) < 3:
        return {}
    got = _MEMO.get(body)
    if got is not None:
        return dict(got[0])
    out: dict[str, float] = {}
    for pos in POS:
        for off in (_index(pos).get(body) or [])[:5]:
            line = _data(pos).get(off)
            if not line:
                continue
            for mate in _synset_words(line):
                if mate != body and mate not in out:
                    out[mate] = SYNONYM
            # `!` is WordNet's antonym pointer - but it lives on the HEAD
            # adjective, and most adjectives you look up are SATELLITES
            # (ss_type `s`) hanging off one. "good" resolves to a satellite
            # whose only pointer is `&` back to the head, so a naive read
            # finds no antonym for the most obviously antonymous word in
            # the language. So: this synset's antonyms, AND the antonyms of
            # any head it points at.
            heads = [(off, pos)] + _pointers(line, "&")
            for h_off, h_pos in heads:
                h_line = _data(h_pos).get(h_off)
                if not h_line:
                    continue
                for a_off, a_pos in _pointers(h_line, "!"):
                    a_line = _data(a_pos).get(a_off)
                    if not a_line:
                        continue
                    for mate in _synset_words(a_line):
                        if mate != body and out.get(mate, 0) < ANTONYM:
                            out[mate] = ANTONYM
    # KEEP THEM APART WHEN TRIMMING. Sorting by weight and taking the top
    # `most` means a synonym at 0.72 always beats an antonym at 0.34, so
    # six synonyms fill every slot and the opposite word - the funny one,
    # the whole reason antonyms are here - is never returned at all. The
    # lookup was right the first time; this line was throwing the answer
    # away.
    syn = sorted(((k, v) for k, v in out.items() if v >= SYNONYM),
                 key=lambda kv: -kv[1])[:max(1, most)]
    ant = sorted(((k, v) for k, v in out.items() if v < SYNONYM),
                 key=lambda kv: -kv[1])[:3]
    trimmed = dict(syn + ant)
    if len(_MEMO) > 4000:
        _MEMO.clear()
    _MEMO[body] = (trimmed,)
    return dict(trimmed)


def expand(words: Iterable[Any], most: int = MOST_PER_WORD
           ) -> dict[str, float]:
    """Every widened word for a line, with the best weight each earned."""
    out: dict[str, float] = {}
    for w in words or ():
        for mate, worth in widen(w, most).items():
            if out.get(mate, 0.0) < worth:
                out[mate] = worth
    return out


def ready() -> bool:
    try:
        return (BASE / "index.noun").is_file()
    except OSError:
        return False
