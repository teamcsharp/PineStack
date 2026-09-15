"""line_alignment.py - cut a master recording into its scripted lines, or refuse.

The operator's model is: one performer records their whole part in one take,
then that take is cut into the lines of the script. Nothing in the station
could do the cutting. A code note at `app.py:32685` records why the obvious
attempt failed: a three-line take with deliberate separators reported two
silences at -35 dB/0.45 s and three at -40 dB/0.35 s - and one of those three
was the trailing tail of the recording, not a separator at all. No threshold
tells a pause from a boundary.

So this module never looks at silence to decide *which* line was spoken. It
takes word-level recognition as EVIDENCE, aligns the recognized word sequence
against the known script with a global sequence alignment (Needleman-Wunsch,
banded - not a greedy forward scan), and then either returns per-occurrence
cuts in integer samples or REFUSES with a reason that names the occurrence.

The note this implements is explicit and both halves matter:

    "Silence alone cannot establish which line was spoken. Alignment must
    reject missing, repeated or mismatched speech; a timestamp assigned to
    every input word does not itself prove the audio contains it."

A recognizer hands back a timestamp for every word it emits. That is not
evidence that the *script's* words are in the audio - only the match between
the two sequences is, and only where the match is dense, ordered and
confident. Everything below exists to make that judgement explicit and to
make its failure loud.

Pure: no I/O, no station imports, no third-party dependencies. The recognizer
lives behind an HTTP call somewhere else (voice-lab `/align`); this module
consumes its output, which is what makes the matching testable offline.

Public surface
--------------
    ScriptLine, RecognizedWord, LineCut, Refusal, AlignmentResult
    AlignmentPolicy                     the thresholds, all named
    MODE_CONTINUOUS / MODE_SEGMENTED    explicit mode identity on every cut
    normalize_tokens(text)              the shared normaliser
    from_whisper_words(rows)            faster-whisper / voice-lab word rows
    align_script(...)                   the whole job
    REFUSAL_CODES                       every reason this module can give
    result_to_json(result)              a plain-dict rendering for manifests
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "MODE_CONTINUOUS", "MODE_SEGMENTED", "REFUSAL_CODES",
    "AlignmentPolicy", "AlignmentResult", "LineCut", "RecognizedWord",
    "Refusal", "ScriptLine",
    "align_script", "from_whisper_words", "normalize_tokens",
    "result_to_json",
]

# --- mode identity ---------------------------------------------------------
# The note forbids calling regrouped per-line TTS a continuous performance.
# Every cut this module emits carries which one it came from, and the caller
# must say so at the door; there is no default that quietly flatters itself.
MODE_CONTINUOUS = "continuous_take"
MODE_SEGMENTED = "segmented_synthesis"
_MODES = (MODE_CONTINUOUS, MODE_SEGMENTED)


# --- refusal vocabulary ----------------------------------------------------
# Every string this module can refuse with, in one place, so a caller can
# switch on a code and an operator can read a sentence. A refusal names its
# occurrence wherever the fault belongs to one.
REFUSAL_CODES: dict[str, str] = {
    "empty_script": "the frozen script had no speakable line in it",
    "empty_line": "the line has no word in it once normalised",
    "bad_sample_rate": "the master's sample rate is missing or not positive",
    "bad_master_frames": "the master's frame count is missing or not positive",
    "bad_mode": "the caller did not declare continuous_take or segmented_synthesis",
    "no_recognition": "the recogniser returned no words at all",
    "silence_only": "the recogniser returned only empty or unspeakable tokens",
    "global_coverage_low": "too little of the whole script was heard in this master",
    "coverage_low": "too little of this line was heard",
    "missing_speech": "a run of this line's words is absent from the recording",
    "extra_speech": "unscripted speech sits inside this line",
    "repeated_speech": "words of this line were spoken more than once",
    "mismatched_speech": "this line's words were heard as different words",
    "low_confidence": "the recogniser was not confident enough about this line",
    "no_speech_for_occurrence": "nothing in the recording matched this line",
    "out_of_order": "this line's speech comes before the line that precedes it",
    "ambiguous_boundary": "this line's span overlaps its neighbour's - no boundary",
    "degenerate_cut": "the computed cut is empty or inverted",
    "bounds_outside_master": "the computed cut runs past the end of the master",
    "short_cut": "the computed cut is shorter than a line can be",
    "unscripted_tail": "speech after the last scripted word - a tail, not a line",
    "unscripted_head": "speech before the first scripted word",
    "speaker_conflict": "the line belongs to an actor this master is not",
}


# --- inputs ----------------------------------------------------------------

@dataclass(frozen=True)
class ScriptLine:
    """One frozen occurrence. Two occurrences of identical words are two
    ScriptLines with different occurrence_ids and different ordinals; the
    alignment separates them by POSITION, never by text."""
    occurrence_id: str
    ordinal: int
    speaker: str
    text: str

    def __post_init__(self) -> None:
        if not str(self.occurrence_id or "").strip():
            raise ValueError("a ScriptLine needs an occurrence_id")


@dataclass(frozen=True)
class RecognizedWord:
    """One recognised word and where the recogniser says it is. `probability`
    is the recogniser's own confidence where it offers one; None means it did
    not, and the confidence gate then abstains rather than inventing a score."""
    word: str
    start: float
    end: float
    probability: float | None = None


@dataclass(frozen=True)
class AlignmentPolicy:
    """Every threshold, named, with the reason it exists.

    These are deliberately strict. The cost of a wrong refusal is a retake;
    the cost of a wrong ACCEPT is a line going out on air in the wrong place,
    which is the failure the whole note exists to prevent."""

    # How much of a line's own words must be heard, as matched tokens over
    # script tokens. 0.85 lets a recogniser lose one word in seven from a
    # twenty-word line and no more.
    min_coverage: float = 0.85
    # The same test over the entire script, so a master that is mostly the
    # wrong recording fails once and loudly rather than line by line.
    min_global_coverage: float = 0.70
    # Mean recogniser probability over a line's matched words. Ignored
    # entirely when the recogniser supplied no probabilities.
    min_confidence: float = 0.55
    # Consecutive script words absent from the audio. Two is a stumble; three
    # in a row is a dropped clause.
    max_missing_run: int = 2
    # Consecutive recognised words inside a line that match nothing in it.
    max_insert_run: int = 3
    # Recognised words after the last scripted word. This is the app.py:32685
    # trap: a trailing tail is not a separator and it is not a line.
    max_unscripted_tail_words: int = 2
    max_unscripted_head_words: int = 2
    # A repeated run this long or longer is a retake inside the master.
    repeat_run: int = 2
    # Padding, in milliseconds, around a cut. edge_pad is what a first or last
    # cut gets; gap_pad is the most either side may claim of the silence
    # between two lines (they split it, never take it all).
    edge_pad_ms: int = 60
    max_gap_pad_ms: int = 250
    # Below this a "line" is an artefact, not speech.
    min_line_ms: int = 120
    # Samples a cut may run past the master before it is a fault rather than
    # a rounding difference.
    bounds_slack_samples: int = 2
    # Scoring for the global alignment.
    score_match: int = 2
    score_near: int = 1
    score_sub: int = -2
    score_gap: int = -2
    # Starting half-width of the alignment band; it doubles until the
    # traceback stops touching the edge, so this is a speed knob only.
    band: int = 64

    def __post_init__(self) -> None:
        for name in ("min_coverage", "min_global_coverage", "min_confidence"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be a fraction")


# --- outputs ---------------------------------------------------------------

@dataclass(frozen=True)
class LineCut:
    """One accepted cut. Integer samples with an explicit rate, because the
    note requires it: a float offset multiplied twice is a different edit.

    `boundary_method` says how the two edges were arrived at, and
    `verification` carries the evidence that justified accepting it. A cut
    with neither is not a cut, it is a guess."""
    occurrence_id: str
    ordinal: int
    speaker: str
    start_sample: int
    end_sample: int
    sample_rate: int
    boundary_method: str
    verification: Mapping[str, Any]
    mode: str
    master_hash: str = ""

    @property
    def frames(self) -> int:
        return self.end_sample - self.start_sample

    @property
    def seconds(self) -> float:
        return self.frames / float(self.sample_rate)


@dataclass(frozen=True)
class Refusal:
    """A refusal that names the occurrence and what went wrong. A bare False
    was the thing this module was written to stop returning."""
    code: str
    detail: str
    occurrence_id: str | None = None
    ordinal: int | None = None

    def __str__(self) -> str:
        if self.occurrence_id:
            where = f"occurrence {self.occurrence_id}"
            if self.ordinal is not None:
                where += f" (line {self.ordinal})"
        else:
            where = "the master"
        return f"{where}: {self.detail}"


@dataclass(frozen=True)
class AlignmentResult:
    ok: bool
    mode: str
    sample_rate: int
    master_frames: int
    cuts: tuple[LineCut, ...] = ()
    refusals: tuple[Refusal, ...] = ()
    stats: Mapping[str, Any] = field(default_factory=dict)

    @property
    def refusal_codes(self) -> tuple[str, ...]:
        return tuple(r.code for r in self.refusals)

    def reasons(self) -> tuple[str, ...]:
        return tuple(str(r) for r in self.refusals)


# --- normalisation ---------------------------------------------------------

_NUM_ONES = ("zero one two three four five six seven eight nine ten eleven "
             "twelve thirteen fourteen fifteen sixteen seventeen eighteen "
             "nineteen").split()
_NUM_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
             "eighty", "ninety")
# The recogniser writes "24" where the script wrote "twenty-four" (and the
# reverse). Left alone that is two missing words and a refused line, which is
# a false refusal - the audio was right. Small, bounded, and only for plain
# integers; anything larger stays as digits on both sides and still matches.
_SCALES = ((1000000, "million"), (1000, "thousand"), (100, "hundred"))


def _int_words(value: int) -> list[str]:
    if value < 0:
        return ["minus"] + _int_words(-value)
    if value < 20:
        return [_NUM_ONES[value]]
    if value < 100:
        tens, rest = divmod(value, 10)
        return [_NUM_TENS[tens]] + ([_NUM_ONES[rest]] if rest else [])
    for size, name in _SCALES:
        if value >= size:
            head, rest = divmod(value, size)
            out = _int_words(head) + [name]
            return out + (_int_words(rest) if rest else [])
    return [str(value)]


_WORD_SPLIT = re.compile(r"[^0-9a-z']+")
_DIGITS = re.compile(r"^\d{1,7}$")
_CURLY = "’"


def normalize_tokens(text: str) -> list[str]:
    """The one normaliser both sides go through. Lowercase, drop punctuation,
    keep internal apostrophes, split hyphens and slashes, spell small integers
    out. Used on the script AND on the recogniser's words, so any asymmetry
    here is a bug in both directions at once rather than a silent bias."""
    lowered = str(text or "").lower().replace(_CURLY, "'")
    out: list[str] = []
    for raw in _WORD_SPLIT.split(lowered):
        token = raw.strip("'")
        if not token:
            continue
        if _DIGITS.match(token):
            out.extend(_int_words(int(token)))
            continue
        out.append(token)
    return out


def from_whisper_words(rows: Iterable[Mapping[str, Any]]
                       ) -> tuple[RecognizedWord, ...]:
    """Accept either shape the house produces: voice-lab's compact
    {"w","t0","t1"} transcript rows, or faster-whisper's own
    {"word","start","end","probability"}. Rows without usable timing are
    dropped here rather than becoming a zero-length span downstream."""
    out: list[RecognizedWord] = []
    for row in rows or ():
        word = str(row.get("w", row.get("word", "")) or "").strip()
        start = row.get("t0", row.get("start"))
        end = row.get("t1", row.get("end"))
        if start is None or end is None:
            continue
        try:
            t0, t1 = float(start), float(end)
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(t0) and math.isfinite(t1)) or t1 < t0:
            continue
        prob = row.get("p", row.get("probability"))
        try:
            confidence = None if prob is None else float(prob)
        except (TypeError, ValueError):
            confidence = None
        out.append(RecognizedWord(word, t0, t1, confidence))
    return tuple(out)


@dataclass(frozen=True)
class _Hyp:
    """A normalised recognised token with a timed span. One recognised word
    can produce several of these ("twenty-four" -> twenty, four); the span is
    split across them by character weight so each still has real timing rather
    than three copies of the same interval."""
    token: str
    start: float
    end: float
    probability: float | None


def _explode(words: Sequence[RecognizedWord]) -> list[_Hyp]:
    out: list[_Hyp] = []
    for word in words:
        tokens = normalize_tokens(word.word)
        if not tokens:
            continue
        span = max(0.0, float(word.end) - float(word.start))
        total = sum(len(t) for t in tokens) or 1
        cursor = float(word.start)
        for index, token in enumerate(tokens):
            share = span * (len(token) / total)
            last = index == len(tokens) - 1
            end = float(word.end) if last else cursor + share
            out.append(_Hyp(token, cursor, max(cursor, end), word.probability))
            cursor = end
    return out


# --- the sequence alignment ------------------------------------------------

_OP_MATCH, _OP_NEAR, _OP_SUB, _OP_DEL, _OP_INS = range(5)
_ANCHORS = (_OP_MATCH, _OP_NEAR, _OP_SUB)
_COVERING = (_OP_MATCH, _OP_NEAR)


def _near(a: str, b: str) -> bool:
    """Same word, spelled slightly differently - a recogniser writing
    "colour" for "color" or losing a plural. Edit distance one, and only for
    tokens long enough that one edit is not the whole word. Scores lower than
    a match so a line made entirely of near-misses cannot pass on coverage."""
    if a == b:
        return False
    if min(len(a), len(b)) < 4 or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(1 for x, y in zip(a, b) if x != y) == 1
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    for cut in range(len(long_)):
        if long_[:cut] + long_[cut + 1:] == short:
            return True
    return False


def _align(script: Sequence[str], hyp: Sequence[str],
           policy: AlignmentPolicy) -> list[tuple[int, int, int]]:
    """Banded global alignment (Needleman-Wunsch). Returns the traceback as
    (op, script_index, hyp_index) with -1 where an index does not apply.

    Global, not local and not greedy: a greedy forward scan matching each
    script word to the next recogniser word that looks like it is exactly how
    a repeated phrase gets stolen by the wrong occurrence. The band is a speed
    device only - it doubles until the optimal path stops touching its edge,
    so the answer is the full-matrix answer."""
    n, m = len(script), len(hyp)
    if not n or not m:
        return ([(_OP_DEL, i, -1) for i in range(n)]
                + [(_OP_INS, -1, j) for j in range(m)])
    band = max(policy.band, abs(n - m) + 8)
    limit = max(n, m) + 8
    while True:
        traceback, touched = _banded(script, hyp, policy, band)
        if not touched or band >= limit:
            return traceback
        band *= 2


def _banded(script: Sequence[str], hyp: Sequence[str],
            policy: AlignmentPolicy, band: int
            ) -> tuple[list[tuple[int, int, int]], bool]:
    n, m = len(script), len(hyp)
    slope = m / n
    neg = float("-inf")

    def window(i: int) -> tuple[int, int]:
        centre = int(round(i * slope))
        return max(0, centre - band), min(m, centre + band)

    rows: list[tuple[int, int, list[float], list[int]]] = []
    lo, hi = window(0)
    lo = 0
    score = [neg] * (hi - lo + 1)
    back = [-1] * (hi - lo + 1)
    for j in range(lo, hi + 1):
        score[j - lo] = policy.score_gap * j
        back[j - lo] = _OP_INS if j else -1
    rows.append((lo, hi, score, back))

    for i in range(1, n + 1):
        lo, hi = window(i)
        if i == n:
            hi = m
        prev_lo, prev_hi, prev_score, _ = rows[i - 1]
        score = [neg] * (hi - lo + 1)
        back = [-1] * (hi - lo + 1)
        for j in range(lo, hi + 1):
            best, best_op = neg, -1
            if prev_lo <= j <= prev_hi and prev_score[j - prev_lo] > neg:
                cand = prev_score[j - prev_lo] + policy.score_gap
                if cand > best:
                    best, best_op = cand, _OP_DEL
            if j > lo and score[j - lo - 1] > neg:
                cand = score[j - lo - 1] + policy.score_gap
                if cand > best:
                    best, best_op = cand, _OP_INS
            if j and prev_lo <= j - 1 <= prev_hi \
                    and prev_score[j - 1 - prev_lo] > neg:
                a, b = script[i - 1], hyp[j - 1]
                if a == b:
                    op, gain = _OP_MATCH, policy.score_match
                elif _near(a, b):
                    op, gain = _OP_NEAR, policy.score_near
                else:
                    op, gain = _OP_SUB, policy.score_sub
                cand = prev_score[j - 1 - prev_lo] + gain
                if cand > best:
                    best, best_op = cand, op
            score[j - lo], back[j - lo] = best, best_op
        rows.append((lo, hi, score, back))

    out: list[tuple[int, int, int]] = []
    i, j, touched = n, m, False
    while i > 0 or j > 0:
        if i == 0:
            out.append((_OP_INS, -1, j - 1))
            j -= 1
            continue
        if j == 0:
            out.append((_OP_DEL, i - 1, -1))
            i -= 1
            continue
        lo, hi, _, back = rows[i]
        if not lo <= j <= hi:
            return out[::-1], True
        if (j == lo and lo > 0) or (j == hi and hi < m):
            touched = True
        op = back[j - lo]
        if op == _OP_INS:
            out.append((_OP_INS, -1, j - 1))
            j -= 1
        elif op == _OP_DEL:
            out.append((_OP_DEL, i - 1, -1))
            i -= 1
        elif op in _ANCHORS:
            out.append((op, i - 1, j - 1))
            i -= 1
            j -= 1
        else:
            return out[::-1], True
    return out[::-1], touched


# --- per-line evidence -----------------------------------------------------

@dataclass
class _LineEvidence:
    line: ScriptLine
    tokens: list[str]
    matched: int = 0
    near: int = 0
    substituted: int = 0
    missing: int = 0
    worst_missing_run: int = 0
    inserted: int = 0
    worst_insert_run: int = 0
    worst_unexpected_run: int = 0
    repeated: list[str] = field(default_factory=list)
    unexpected: list[str] = field(default_factory=list)
    anchors: list[int] = field(default_factory=list)
    probabilities: list[float] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        return (self.matched + self.near) / len(self.tokens) if self.tokens else 0.0

    @property
    def confidence(self) -> float | None:
        if not self.probabilities:
            return None
        return sum(self.probabilities) / len(self.probabilities)


def _is_repeat(run: Sequence[str], tokens: Sequence[str],
               policy: AlignmentPolicy) -> bool:
    """Is this run of unmatched recognised words a re-reading of words the
    line already contains? That is a retake inside the master, and it is the
    "repeated speech" the note demands be rejected - not merely a stray word."""
    if len(run) < policy.repeat_run:
        return False
    span = len(run)
    for start in range(0, max(0, len(tokens) - span) + 1):
        if list(tokens[start:start + span]) == list(run):
            return True
    return False


def _collect(script: Sequence[ScriptLine], owner: Sequence[int],
             script_tokens: Sequence[str], hyps: Sequence[_Hyp],
             traceback: Sequence[tuple[int, int, int]],
             policy: AlignmentPolicy
             ) -> tuple[list[_LineEvidence], list[str], list[str]]:
    """Walk the traceback once and hang every operation on the line it
    belongs to. An insertion belongs to the line of the script word it sits
    after; before the first and after the last it belongs to nobody, which is
    exactly the head and tail the note warns about."""
    evidence = [
        _LineEvidence(line, [t for k, t in enumerate(script_tokens)
                             if owner[k] == index])
        for index, line in enumerate(script)
    ]
    head: list[str] = []
    tail: list[str] = []
    current = -1
    missing_run = 0
    insert_run: list[str] = []

    def flush_inserts() -> None:
        nonlocal insert_run
        if not insert_run:
            return
        if current < 0:
            head.extend(insert_run)
        else:
            ev = evidence[current]
            ev.inserted += len(insert_run)
            ev.worst_insert_run = max(ev.worst_insert_run, len(insert_run))
            if _is_repeat(insert_run, ev.tokens, policy):
                ev.repeated.extend(insert_run)
            else:
                # Counted separately from repeats, or a re-read of the line's
                # own words also fired "extra_speech" - with nothing to name,
                # because the words had gone to `repeated`. Measured on a real
                # take: "9 unscripted word(s) in a row inside it: " with an
                # empty list after the colon. One fault, one refusal.
                ev.unexpected.extend(insert_run)
                ev.worst_unexpected_run = max(ev.worst_unexpected_run,
                                              len(insert_run))
        insert_run = []

    for op, i, j in traceback:
        if op == _OP_INS:
            insert_run.append(hyps[j].token)
            continue
        flush_inserts()
        index = owner[i]
        if index != current:
            current = index
            missing_run = 0
        ev = evidence[index]
        if op == _OP_DEL:
            ev.missing += 1
            missing_run += 1
            ev.worst_missing_run = max(ev.worst_missing_run, missing_run)
            continue
        missing_run = 0
        ev.anchors.append(j)
        if hyps[j].probability is not None:
            ev.probabilities.append(float(hyps[j].probability))
        if op == _OP_MATCH:
            ev.matched += 1
        elif op == _OP_NEAR:
            ev.near += 1
        else:
            ev.substituted += 1
    # Anything still pending after the last anchored script word is the tail,
    # never a separator and never part of the last cut (app.py:32685).
    if insert_run and current == len(script) - 1 and current >= 0:
        # Sits after the final scripted word: the tail, not that line's speech.
        tail.extend(insert_run)
        insert_run = []
    flush_inserts()
    return evidence, head, tail


# --- the job ---------------------------------------------------------------

def align_script(script: Sequence[ScriptLine],
                 words: Sequence[RecognizedWord],
                 sample_rate: int,
                 master_frames: int,
                 mode: str,
                 policy: AlignmentPolicy | None = None,
                 master_hash: str = "",
                 actor: str = "") -> AlignmentResult:
    """Validated per-occurrence cuts for one master, or a refusal per fault.

    `script` is the frozen ordered script for THIS master: the occurrences
    this performer is to have spoken, in reading order, with the exact spoken
    text. `words` is the recogniser's evidence over the whole master.
    `mode` must be stated by the caller - a continuous take and bounded
    engine segments produce different artifacts and the manifest must never
    lose which one it holds.

    Returns an AlignmentResult. `ok` is True only when every occurrence got
    exactly one cut and nothing was refused; a partial success is still a
    refusal, because a conversation with a hole in it is not a conversation.
    """
    policy = policy or AlignmentPolicy()
    refusals: list[Refusal] = []
    if mode not in _MODES:
        return AlignmentResult(
            False, str(mode), int(sample_rate or 0), int(master_frames or 0),
            refusals=(Refusal("bad_mode", REFUSAL_CODES["bad_mode"]),))
    rate = int(sample_rate or 0)
    frames = int(master_frames or 0)
    if rate <= 0:
        refusals.append(Refusal("bad_sample_rate",
                                REFUSAL_CODES["bad_sample_rate"]))
    if frames <= 0:
        refusals.append(Refusal("bad_master_frames",
                                REFUSAL_CODES["bad_master_frames"]))

    lines = list(script or ())
    if not lines:
        refusals.append(Refusal("empty_script", REFUSAL_CODES["empty_script"]))
    for line in lines:
        if actor and line.speaker and line.speaker != actor:
            refusals.append(Refusal(
                "speaker_conflict",
                f"the line is {line.speaker}'s but this master is {actor}'s",
                line.occurrence_id, line.ordinal))
    if refusals:
        return AlignmentResult(False, mode, rate, frames,
                               refusals=tuple(refusals))

    script_tokens: list[str] = []
    owner: list[int] = []
    for index, line in enumerate(lines):
        tokens = normalize_tokens(line.text)
        if not tokens:
            refusals.append(Refusal("empty_line", REFUSAL_CODES["empty_line"],
                                    line.occurrence_id, line.ordinal))
            continue
        script_tokens.extend(tokens)
        owner.extend([index] * len(tokens))
    if refusals:
        return AlignmentResult(False, mode, rate, frames,
                               refusals=tuple(refusals))

    hyps = _explode(words or ())
    if not words:
        return AlignmentResult(
            False, mode, rate, frames,
            refusals=(Refusal("no_recognition", REFUSAL_CODES["no_recognition"]
                              + " - a master with no words in it cannot be cut "
                                "into lines, whatever its silences look like"),))
    if not hyps:
        return AlignmentResult(
            False, mode, rate, frames,
            refusals=(Refusal("silence_only", REFUSAL_CODES["silence_only"]
                              + f" ({len(words)} row(s) of it)"),))

    traceback = _align(script_tokens, [h.token for h in hyps], policy)
    evidence, head, tail = _collect(lines, owner, script_tokens, hyps,
                                    traceback, policy)

    covered = sum(ev.matched + ev.near for ev in evidence)
    global_coverage = covered / len(script_tokens) if script_tokens else 0.0
    stats: dict[str, Any] = {
        "script_tokens": len(script_tokens),
        "recognised_tokens": len(hyps),
        "matched": sum(ev.matched for ev in evidence),
        "near": sum(ev.near for ev in evidence),
        "substituted": sum(ev.substituted for ev in evidence),
        "missing": sum(ev.missing for ev in evidence),
        "inserted": sum(ev.inserted for ev in evidence),
        "head_words": len(head),
        "tail_words": len(tail),
        "global_coverage": round(global_coverage, 4),
        "mode": mode,
    }
    if global_coverage < policy.min_global_coverage:
        return AlignmentResult(
            False, mode, rate, frames, stats=stats,
            refusals=(Refusal(
                "global_coverage_low",
                f"{round(100 * global_coverage)}% of the script's "
                f"{len(script_tokens)} words were heard, floor is "
                f"{round(100 * policy.min_global_coverage)}% - this master is "
                "not a reading of this script"),))

    # --- per-line faults ---------------------------------------------------
    for ev in evidence:
        line = ev.line
        oid, ordinal = line.occurrence_id, line.ordinal
        if not ev.anchors:
            refusals.append(Refusal(
                "no_speech_for_occurrence",
                f"none of its {len(ev.tokens)} word(s) were heard anywhere in "
                "the master", oid, ordinal))
            continue
        if ev.coverage < policy.min_coverage:
            refusals.append(Refusal(
                "coverage_low",
                f"{ev.matched + ev.near} of {len(ev.tokens)} word(s) heard "
                f"({round(100 * ev.coverage)}%), floor is "
                f"{round(100 * policy.min_coverage)}%", oid, ordinal))
        if ev.worst_missing_run > policy.max_missing_run:
            refusals.append(Refusal(
                "missing_speech",
                f"{ev.worst_missing_run} of its words in a row are absent "
                f"(most allowed {policy.max_missing_run})", oid, ordinal))
        if ev.repeated:
            refusals.append(Refusal(
                "repeated_speech",
                "heard again inside this line: "
                + " ".join(ev.repeated[:8]), oid, ordinal))
        if ev.worst_unexpected_run > policy.max_insert_run:
            refusals.append(Refusal(
                "extra_speech",
                f"{ev.worst_unexpected_run} unscripted word(s) in a row "
                "inside it: "
                + " ".join(ev.unexpected[:8]), oid, ordinal))
        if ev.substituted and ev.substituted > max(
                1, int(0.1 * len(ev.tokens))):
            refusals.append(Refusal(
                "mismatched_speech",
                f"{ev.substituted} of {len(ev.tokens)} word(s) came back as "
                "something else", oid, ordinal))
        confidence = ev.confidence
        if confidence is not None and confidence < policy.min_confidence:
            refusals.append(Refusal(
                "low_confidence",
                f"mean recogniser confidence {round(confidence, 3)} is under "
                f"{policy.min_confidence}", oid, ordinal))

    if len(head) > policy.max_unscripted_head_words:
        refusals.append(Refusal(
            "unscripted_head",
            f"{len(head)} word(s) before the script begins: "
            + " ".join(head[:8]),
            lines[0].occurrence_id, lines[0].ordinal))
    if len(tail) > policy.max_unscripted_tail_words:
        refusals.append(Refusal(
            "unscripted_tail",
            f"{len(tail)} word(s) after the last scripted word: "
            + " ".join(tail[:8])
            + " - a tail is not a separator and not a line (app.py:32685)",
            lines[-1].occurrence_id, lines[-1].ordinal))

    # --- spans, order, boundaries -----------------------------------------
    spans: list[tuple[float, float]] = []
    for ev in evidence:
        if not ev.anchors:
            spans.append((0.0, 0.0))
            continue
        first, last = min(ev.anchors), max(ev.anchors)
        spans.append((hyps[first].start, hyps[last].end))

    for index in range(1, len(spans)):
        if not evidence[index].anchors or not evidence[index - 1].anchors:
            continue
        previous, current = spans[index - 1], spans[index]
        line = lines[index]
        if current[0] < previous[0]:
            refusals.append(Refusal(
                "out_of_order",
                f"its speech starts at {round(current[0], 3)}s, before line "
                f"{lines[index - 1].ordinal} at {round(previous[0], 3)}s",
                line.occurrence_id, line.ordinal))
        elif current[0] < previous[1]:
            refusals.append(Refusal(
                "ambiguous_boundary",
                f"it begins at {round(current[0], 3)}s while line "
                f"{lines[index - 1].ordinal} is still speaking until "
                f"{round(previous[1], 3)}s - there is no boundary between them",
                line.occurrence_id, line.ordinal))

    if refusals:
        return AlignmentResult(False, mode, rate, frames, stats=stats,
                               refusals=tuple(refusals))

    edge = policy.edge_pad_ms / 1000.0
    gap_cap = policy.max_gap_pad_ms / 1000.0
    cuts: list[LineCut] = []
    for index, ev in enumerate(evidence):
        start, end = spans[index]
        line = ev.line
        # The EVIDENCE must lie inside the master, and this is checked before
        # any padding. Checking afterwards hid the fault: the last cut's pad
        # is clamped to the end of the file, so a master shorter than its own
        # speech came back as a 75 ms "short cut" instead of a recording that
        # does not contain what the recogniser says it does.
        if int(round(end * rate)) > frames + policy.bounds_slack_samples                 or start < 0:
            refusals.append(Refusal(
                "bounds_outside_master",
                f"its speech runs to {round(end, 3)}s but the master holds "
                f"{round(frames / float(rate), 3)}s",
                line.occurrence_id, line.ordinal))
            continue
        methods = ["word_span"]
        if index == 0:
            claimed = min(edge, start)
            if claimed > 0:
                start -= claimed
                methods.append("edge_pad")
        else:
            gap = start - spans[index - 1][1]
            pad = min(gap_cap, gap / 2.0)
            if pad > 0:
                start -= pad
                methods.append("gap_split")
        if index == len(evidence) - 1:
            # The tail of the master is NOT this line. Pad by the fixed edge
            # only, never out to the end of the file.
            end = min(end + edge, frames / float(rate))
            methods.append("edge_pad")
        else:
            gap = spans[index + 1][0] - end
            pad = min(gap_cap, gap / 2.0)
            if pad > 0:
                end += pad
                methods.append("gap_split")
        start_sample = int(round(max(0.0, start) * rate))
        end_sample = int(round(max(0.0, end) * rate))
        if end_sample <= start_sample:
            refusals.append(Refusal(
                "degenerate_cut",
                f"start {start_sample} is not before end {end_sample}",
                line.occurrence_id, line.ordinal))
            continue
        if end_sample > frames + policy.bounds_slack_samples:
            refusals.append(Refusal(
                "bounds_outside_master",
                f"ends at sample {end_sample} but the master holds {frames}",
                line.occurrence_id, line.ordinal))
            continue
        end_sample = min(end_sample, frames)
        length_ms = 1000.0 * (end_sample - start_sample) / rate
        if length_ms < policy.min_line_ms:
            refusals.append(Refusal(
                "short_cut",
                f"{round(length_ms)}ms is under the {policy.min_line_ms}ms "
                "floor for a spoken line", line.occurrence_id, line.ordinal))
            continue
        confidence = ev.confidence
        cuts.append(LineCut(
            occurrence_id=line.occurrence_id,
            ordinal=line.ordinal,
            speaker=line.speaker,
            start_sample=start_sample,
            end_sample=end_sample,
            sample_rate=rate,
            boundary_method="+".join(dict.fromkeys(methods)),
            verification={
                "words": len(ev.tokens),
                "matched": ev.matched,
                "near": ev.near,
                "substituted": ev.substituted,
                "missing": ev.missing,
                "inserted": ev.inserted,
                "coverage": round(ev.coverage, 4),
                "confidence": None if confidence is None
                else round(confidence, 4),
                "speech_start_sample": int(round(spans[index][0] * rate)),
                "speech_end_sample": int(round(spans[index][1] * rate)),
                "verdict": "verified",
            },
            mode=mode,
            master_hash=master_hash,
        ))

    if refusals:
        return AlignmentResult(False, mode, rate, frames, stats=stats,
                               refusals=tuple(refusals))
    stats["cuts"] = len(cuts)
    stats["cut_seconds"] = round(sum(c.seconds for c in cuts), 3)
    return AlignmentResult(True, mode, rate, frames, tuple(cuts), (), stats)


def result_to_json(result: AlignmentResult) -> dict[str, Any]:
    """A plain-dict rendering, which is what crosses HTTP and what a manifest
    store persists. Refusals keep their code AND their sentence: the code is
    for a caller to branch on, the sentence is for the operator to read."""
    return {
        "ok": bool(result.ok),
        "mode": result.mode,
        "sample_rate": result.sample_rate,
        "master_frames": result.master_frames,
        "stats": dict(result.stats or {}),
        "cuts": [{
            "occurrence_id": c.occurrence_id,
            "ordinal": c.ordinal,
            "speaker": c.speaker,
            "start_sample": c.start_sample,
            "end_sample": c.end_sample,
            "frames": c.frames,
            "sample_rate": c.sample_rate,
            "seconds": round(c.seconds, 4),
            "boundary_method": c.boundary_method,
            "verification": dict(c.verification),
            "mode": c.mode,
            "master_hash": c.master_hash,
        } for c in result.cuts],
        "refusals": [{
            "code": r.code,
            "occurrence_id": r.occurrence_id,
            "ordinal": r.ordinal,
            "detail": r.detail,
            "says": str(r),
        } for r in result.refusals],
    }
