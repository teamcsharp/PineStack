"""PineRhyme: the crystal's own rhyme dictionary. ZERO model asks.

The station had a pronouncing dictionary that could only answer "do these two
words rhyme", so the one function that offered the writer a rhyme walked the
crystal's vocabulary in ALPHABETICAL ORDER and stopped at the first forty
hits. Measured over thirty real landings, 70% of every word it offered began
with a, b or c: "rhymes with 'be' - ability, adhd, albee, anarchy, apology,
avi, bbc, brea". That is a monotony generator sitting upstream of everything
the listener hears.

This holds the crystal's RHYME FAMILIES instead - every crystal word grouped
by its pronunciation tail from the final stressed vowel, so a family is a set
of words that perfectly rhyme by the grader's own reading - and ranks a
suggestion by how DISTINCTIVE it is: frequent in the crystal, rare in
ordinary English, more syllables after the stress, and never the station's own
furniture. Measured on the DOOM crystal: 6,863 perfect families over 17,288
words, 1,644 of them multisyllabic; 9,298 crystal words have five or more
perfect partners inside the crystal.

One persistent artifact (data/rhyme_families.json), memoised per process, read
in 0.12 s, 16 MB resident. A warm ask is 0.01 ms against the 442 ms the
alphabetical scan cost.

The artifact supplies SOUND, FREQUENCY AND PROVENANCE ONLY. Membership is
always the live station's `_crystal_vocab()`, passed as `vocab=`: the index
never overrides the crystal that is actually on, and a word the live set
carries that the artifact lacks is read straight from the pinned CMUdict.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
from collections import Counter, defaultdict

import crystal_rhyme as CR

_WORD = re.compile(r"[a-z][a-z']*")
VOWELS = frozenset({"AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER",
                    "EY", "IH", "IY", "OW", "OY", "UH", "UW"})

# The closed class: app._RAP_STOP + app._RAP_END_EXCL + rhyme_assistance._STOP,
# plus the contractions and quantifiers those lists spell without apostrophes.
FUNCTION = frozenset(
    "a an and are as at be been but by do for from had has have he her hers him his i if in into "
    "is it its me my of on or our she so that the their them they this to us was we were what when "
    "where which who why with you your yeah yes no oh ok okay the or nor being can could did does "
    "how just not out some than then there these those too up please "
    "am aint cant dont wont isnt wasnt shall should may might must will would im ive id ill "
    "youre youve youll youd theyre theyve thats whats hes shes weve well theres heres "
    "one two three four five six seven eight nine ten "
    "very really quite rather much many more most less least also still yet even only ever never "
    "always about after again against all any because before between both down during each few "
    "further off once other over own same such through under until while".split())

# The station's own furniture: the landings the writer already over-uses.
# Derived, not guessed - measured over 13,009 bar landings in four days of air
# as log2(share of the air / share of the crystal). "notion", "reside",
# "concoction", "berth" and "decree" are not the crystal's words at all.
FURNITURE = frozenset(
    "fm station tonight here there now right time sound live me you it that show radio air night "
    "day thing things way ways one people talk music song track record play played box pine "
    "listener listeners flow vibe groove moment moments minute minutes hour hours notion motion "
    "concoction reside ripe berth decree studio".split())

_CACHE: dict[str, "PineRhyme"] = {}
_LOCK = threading.RLock()


def load(path: str) -> "PineRhyme":
    """Memoised per path. The first call pays the JSON read; later ones are free.
    Raises if the artifact is absent - every caller must have a fallback."""
    key = os.path.abspath(str(path))
    with _LOCK:
        got = _CACHE.get(key)
        if got is None:
            got = _CACHE[key] = PineRhyme(key)
        return got


def forget(path: str = "") -> None:
    """Drop the memo, so a rebuilt artifact is read fresh."""
    with _LOCK:
        if path:
            _CACHE.pop(os.path.abspath(str(path)), None)
        else:
            _CACHE.clear()


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            return word[: -len(suffix)]
    return word


def _nuclei_of(tail_key: str) -> int:
    return sum(1 for phone in str(tail_key).split() if phone in VOWELS) or 1


class PineRhyme:
    def __init__(self, path: str):
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        self.path = path
        self.totals = data.get("totals") or {}
        self.cmudict = data.get("cmudict") or {}
        self.fam = data.get("families") or {}
        self.index = data.get("index") or {}
        self._member: dict[str, dict] = {}
        for fam in self.fam.values():
            for member in fam.get("members") or []:
                self._member.setdefault(member["w"], member)
        self._ask_cache: dict[tuple, list] = {}
        self._views: dict[tuple, tuple] = {}
        self._open = self._build_open_pairs()

    # ---------- the crystal's ready-made couplets ----------
    def _build_open_pairs(self, keep: int = 600) -> list[dict]:
        """Two distinctive non-function crystal words out of one multisyllabic
        family, one pair per family, best first - computed once at load."""
        out: list[dict] = []
        for key, fam in self.fam.items():
            if int(fam.get("n") or 0) < 2 or int(fam.get("nuclei") or 1) < 2:
                continue
            picks: list[tuple[float, dict]] = []
            for member in fam.get("members") or []:
                word = member["w"]
                if (member.get("fn") or word in FURNITURE or len(word) < 4
                        or int(member.get("f") or 0) < 3
                        or (not member.get("wn", 1) and int(member.get("f") or 0) < 8)
                        or member.get("pn")):
                    continue
                if any(word.startswith(p[1]["w"]) or p[1]["w"].startswith(word)
                       or _stem(word) == _stem(p[1]["w"]) for p in picks):
                    continue
                picks.append((self.score(member, int(fam.get("nuclei") or 1)), member))
                if len(picks) >= 2:
                    break
            if len(picks) == 2:
                out.append({"kind": "open", "from": "crystal", "tail": key,
                            "tail_nuclei": int(fam.get("nuclei") or 1), "grade": "perfect",
                            "pair": [picks[0][1]["w"], picks[1][1]["w"]],
                            "score": round((picks[0][0] + picks[1][0]) / 2, 3)})
        out.sort(key=lambda row: -row["score"])
        return out[:keep]

    # ---------- sound ----------
    def tails(self, word: str) -> list[str]:
        """The word's rhyme tails, from the SAME pinned CMUdict the grader
        reads, so a partner offered here is a partner it proves."""
        word = str(word or "").lower().strip().strip("'’")
        got = self.index.get(word)
        if got:
            return list(got)
        try:
            return list(dict.fromkeys(" ".join(t) for _p, t, _n in CR._pronunciations(word)))
        except Exception:  # noqa: BLE001
            return []

    def family(self, word: str) -> list[dict]:
        return [self.fam[key] for key in self.tails(word) if key in self.fam]

    # ---------- the ranking ----------
    def score(self, member: dict, nuclei: int) -> float:
        """Distinctive crystal words first; function words and the station's
        furniture last. The crystal pull SATURATES so one top-twenty slang
        word cannot own every list; ordinary-English use (the WordNet tagged
        counts) drags a word down; reach lifts the multisyllabic, which is
        the crystal's own signature and the thing the station never writes."""
        pull = min(math.log2(1.0 + float(member.get("f") or 0)), 6.5)
        drag = 0.55 * math.log2(1.0 + float(member.get("uses") or 0))
        reach = 0.90 * (nuclei - 1) + 0.35 * max(0, int(member.get("syl") or 1) - 1)
        penalty = (4.0 * bool(member.get("fn")) + 3.0 * (member["w"] in FURNITURE)
                   + 2.5 * bool(member.get("pn")))
        return pull - drag + reach - penalty

    def _view(self, vocab) -> tuple:
        """A live word set is the AUTHORITY on membership; the artifact only
        supplies sound, frequency and provenance. Words the live set carries
        that the artifact does not are read from the pinned CMUdict, once."""
        if vocab is None:
            return None, {}
        key = (id(vocab), len(vocab))
        got = self._views.get(key)
        if got is None:
            extra: dict[str, list] = {}
            for word in vocab:
                word = str(word).lower()
                if word in self.index or len(word) < 2:
                    continue
                try:
                    prons = CR._pronunciations(word)
                except Exception:  # noqa: BLE001
                    continue
                for phones, tail, _n in prons:
                    extra.setdefault(" ".join(tail), []).append(
                        {"w": word, "f": 0, "uses": 0, "d": 0.0,
                         "syl": sum(p[-1:].isdigit() for p in phones),
                         "fn": int(word in FUNCTION), "wn": 1, "pn": 0})
            got = (frozenset(str(w).lower() for w in vocab), extra)
            if len(self._views) > 6:
                self._views.clear()
            self._views[key] = got
        return got

    def partners(self, word: str, limit: int = 12, near: bool = True,
                 alpha_only: bool = False, min_freq: int = 2, exclude=(),
                 avoid_furniture: bool = True, vocab=None) -> list[dict]:
        """Ranked crystal partners for `word`; grade is "perfect" or "near"."""
        word = str(word or "").lower().strip().strip("'’")
        if len(word) < 2:
            return []
        allowed, extra = self._view(vocab)
        key = (word, limit, near, alpha_only, min_freq, avoid_furniture,
               tuple(sorted(str(x).lower() for x in exclude)),
               None if allowed is None else (id(vocab), len(allowed)))
        hit = self._ask_cache.get(key)
        if hit is not None:
            return [dict(row) for row in hit]
        drop = {word, _stem(word)} | set(str(x).lower() for x in exclude)
        rows: list[dict] = []
        seen: set[str] = set()
        perfect_keys = self.tails(word)
        near_keys = self._near_keys(perfect_keys) if near else []
        for grade, keys in (("perfect", perfect_keys), ("near", near_keys)):
            for tail_key in keys:
                fam = self.fam.get(tail_key)
                members = list((fam or {}).get("members") or []) + extra.get(tail_key, [])
                if not members:
                    continue
                nuclei = int((fam or {}).get("nuclei") or 0) or _nuclei_of(tail_key)
                thin = len(members) < 6
                for member in members:
                    cand = member["w"]
                    if cand in seen or cand in drop or len(cand) < 3:
                        continue
                    if allowed is not None and cand not in allowed:
                        continue
                    # one stem is not a pair: call/called, mask/unmask, ask/asked
                    if (cand.startswith(word) or word.startswith(cand) or _stem(cand) in drop
                            or (len(word) >= 4 and cand.endswith(word))
                            or (len(cand) >= 4 and word.endswith(cand))):
                        continue
                    if alpha_only and not cand.isalpha():
                        continue
                    if avoid_furniture and cand in FURNITURE:
                        continue
                    if int(member.get("f") or 0) < min_freq and not thin and allowed is None:
                        continue
                    # a word WordNet does not carry as a lowercase lemma is a
                    # name or a coinage: keep it only if the crystal leans on it
                    if not member.get("wn", 1) and int(member.get("f") or 0) < 8:
                        continue
                    if member.get("pn") and int(member.get("f") or 0) < 8:
                        continue
                    seen.add(cand)
                    rows.append({
                        "word": cand, "grade": grade, "tail": tail_key,
                        "crystal": int(member.get("f") or 0), "uses": int(member.get("uses") or 0),
                        "syllables": int(member.get("syl") or 1), "tail_nuclei": nuclei,
                        "distinct": member.get("d", 0.0), "function": bool(member.get("fn")),
                        "score": round(self.score(member, nuclei)
                                       - (0.75 if grade == "near" else 0), 3)})
        # Perfect before near, always: the grader's strongest evidence leads,
        # and a near suggestion can never displace a proven pair.
        rows.sort(key=lambda row: (row["grade"] != "perfect", -row["score"], row["word"]))
        rows = rows[:max(1, int(limit))]
        if len(self._ask_cache) > 4000:
            self._ask_cache.clear()
        self._ask_cache[key] = [dict(row) for row in rows]
        return rows

    def _near_keys(self, keys) -> list[str]:
        out: list[str] = []
        for key in keys:
            out.extend((self.fam.get(key) or {}).get("near") or [])
        return list(dict.fromkeys(out))

    def options_for(self, word: str, limit: int = 8, vocab=None) -> list[str]:
        """Drop-in for app.rhyme_options_for: plain crystal words, perfect
        first, distinctive first, alphabetic only (what the prompt prints)."""
        return [row["word"] for row in
                self.partners(word, limit, alpha_only=True, vocab=vocab)]

    # ---------- the pairs the writer aims at ----------
    def landing_pairs(self, line: str, want: int = 4, answering: str = "",
                      exclude=(), vocab=None) -> list[dict]:
        """Landing pairs to aim two bars at, out of the crystal and never out
        of the station's furniture.

        ANCHORED pairs come first: a content word the SOURCE already contains
        plus the crystal's best answer to it, so the bar keeps the source's
        fact and only the landing is chosen - which is the one shape that
        satisfies the meaning contract and the crystal at the same time.
        OPEN pairs follow: two distinctive crystal words from one family,
        multisyllabic first, rotated on the source's hash so two turns of a
        round are never handed the same ready-made couplet."""
        words = [w.strip("'") for w in _WORD.findall(str(line or "").lower())]
        drop = set(str(x).lower() for x in exclude)
        anchors: list[str] = []
        out: list[dict] = []
        used: set[str] = set()
        for word in reversed(words):
            if len(word) < 3 or word in drop or word in FURNITURE or word in anchors:
                continue
            member = self._member.get(word)
            if member is not None and member.get("fn"):
                continue
            if word in FUNCTION:
                continue
            anchors.append(word)
            if len(anchors) >= 6:
                break
        prev = ""
        if answering:
            tail = [w for w in _WORD.findall(str(answering).lower()) if len(w) > 2]
            prev = tail[-1] if tail else ""
        if prev:
            anchors.insert(0, prev)
        for anchor in anchors:
            for partner in self.partners(anchor, 3, vocab=vocab):
                if partner["word"] in used:
                    continue
                used.add(partner["word"])
                out.append({"kind": "anchored",
                            "from": "previous_bar" if anchor == prev else "source",
                            "pair": [anchor, partner["word"]], "grade": partner["grade"],
                            "tail": partner["tail"], "tail_nuclei": partner["tail_nuclei"],
                            "score": round(partner["score"] + 1.5, 3)})
                break
        seed = sum(ord(c) for c in str(line or "")) % max(1, len(self._open) or 1)
        for row in self._open[seed:] + self._open[:seed]:
            if len(out) >= want + 4:
                break
            if row["pair"][0] in used or row["pair"][1] in used or set(row["pair"]) & drop:
                continue
            used.update(row["pair"])
            out.append(dict(row))
        out.sort(key=lambda row: (row["kind"] != "anchored", -row["score"]))
        return out[:max(1, int(want))]


# --------------------------------------------------------------------------
# The build. One pass over the pinned dictionary, one over the crystal's own
# lexicon, one bucketed pass for the near edges. No model, no network.
# --------------------------------------------------------------------------
def _usage_counts(cntlist: str) -> Counter:
    """WordNet tagged-sense counts - the ORDINARY-ENGLISH side, the way
    rhyme_assistance.initialize already reads them."""
    use: Counter = Counter()
    try:
        with open(cntlist, encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) == 3:
                    use[parts[0].split("%", 1)[0]] += int(parts[2])
    except Exception:  # noqa: BLE001
        pass
    return use


def _wordnet_forms(base: str) -> tuple[set, set]:
    """The lowercase lemma set and the proper-name-only set, from the pinned
    WordNet data files (data.* keeps the case that index.* has lowered)."""
    lower: set[str] = set()
    upper: set[str] = set()
    for pos in ("noun", "verb", "adj", "adv"):
        try:
            with open(os.path.join(base, "data." + pos), encoding="utf-8",
                      errors="ignore") as handle:
                for line in handle:
                    if not line or line.startswith(" "):
                        continue
                    left = line.partition("|")[0].split()
                    if len(left) < 5:
                        continue
                    try:
                        size = int(left[3], 16)
                    except ValueError:
                        continue
                    for i in range(size):
                        at = 4 + 2 * i
                        if at >= len(left):
                            break
                        word = re.sub(r"\((?:a|p|ip)\)$", "", left[at])
                        (upper if word[:1].isupper() else lower).add(word.lower())
        except Exception:  # noqa: BLE001
            continue
    return lower, upper - lower


def build(counts, out_path: str, vendor: str = "") -> dict:
    """Build the family index from `counts` ({word: how often the crystal uses
    it}) and write it to `out_path`. Returns the payload's totals."""
    vendor = vendor or os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")
    crystal = [(str(w).lower(), int(n)) for w, n in dict(counts or {}).items()
               if str(w).strip() and int(n or 0) > 0]
    use = _usage_counts(os.path.join(vendor, "wordnet", "cntlist.rev"))
    wn_lower, wn_proper = _wordnet_forms(os.path.join(vendor, "wordnet"))
    total_crystal = sum(n for _w, n in crystal) or 1
    total_use = sum(use.values()) or 1
    fams: dict[str, dict] = {}
    known = 0
    unknown: list[tuple[str, int]] = []
    for word, freq in crystal:
        try:
            prons = CR._pronunciations(word)
        except Exception:  # noqa: BLE001
            prons = ()
        if not prons:
            unknown.append((word, freq))
            continue
        known += 1
        seen_tails: set[str] = set()
        for phones, tail, nuclei in prons:
            key = " ".join(tail)
            if key in seen_tails:
                continue
            seen_tails.add(key)
            uses = use.get(word, 0)
            fam = fams.setdefault(key, {"tail": key, "nuclei": nuclei, "members": []})
            fam["members"].append({
                "w": word, "f": freq, "syl": sum(p[-1:].isdigit() for p in phones),
                "uses": uses,
                "d": round(math.log2(((freq + 0.5) / total_crystal)
                                     / ((uses + 0.5) / total_use)), 3),
                "fn": int(word in FUNCTION), "wn": int(word in wn_lower),
                "pn": int(word in wn_proper)})
    for fam in fams.values():
        fam["members"].sort(key=lambda m: (m["fn"], -m["d"], -m["f"], m["w"]))
        fam["n"] = len(fam["members"])
        fam["content"] = sum(1 for m in fam["members"] if not m["fn"])
    buckets: dict[str, list] = defaultdict(list)
    for key in fams:
        buckets[key.split(" ", 1)[0]].append(key)
    edges = 0
    for _vowel, keys in buckets.items():
        tails = [(k, tuple(k.split())) for k in keys]
        for i in range(len(tails)):
            key_a, tail_a = tails[i]
            near = fams[key_a].setdefault("near", [])
            for j in range(i + 1, len(tails)):
                key_b, tail_b = tails[j]
                if CR.near_tails(tail_a, tail_b):
                    near.append(key_b)
                    fams[key_b].setdefault("near", []).append(key_a)
                    edges += 1
    index: dict[str, list] = {}
    for key, fam in fams.items():
        for member in fam["members"]:
            index.setdefault(member["w"], []).append(key)
    payload = {
        "version": 1,
        "cmudict": {"version": CR.DICTIONARY_VERSION, "sha256": CR.DICTIONARY_SHA256},
        "totals": {"crystal_words": len(crystal), "crystal_tokens": total_crystal,
                   "cmu_known": known, "cmu_unknown": len(crystal) - known,
                   "families": len(fams), "near_edges": edges,
                   "multisyllabic_families": sum(1 for f in fams.values()
                                                 if int(f.get("nuclei") or 1) >= 2),
                   "wordnet_tagged_total": total_use,
                   "wordnet_lower_lemmas": len(wn_lower),
                   "wordnet_proper_only": len(wn_proper), "built": int(__import__("time").time())},
        "families": fams, "index": index,
    }
    out_path = str(out_path)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"))
    os.replace(tmp, out_path)
    forget(out_path)
    return payload["totals"]
