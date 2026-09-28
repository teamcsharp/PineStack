"""[s3-dice4] call_scenarios: a random source that can make a weighted pick
itself - `draw(what, labels, weights)` -> index - makes every draw here (which
scenario, the path of each of the six beats, the landing), at the catalog's
own weights. The station hands in System 3's dice (app.py _S3Weighted), which
record what was on offer and where each draw landed; random.Random, the
module and the tests' fixed sources have no draw() and keep the arithmetic,
number for number. The module stays pure: no station import.

Marker-idempotent: a file that already carries [s3-dice4] is left alone (a
second run changes nothing and exits 0). Line endings are kept as found (the
host's working copy is CRLF - git i/lf w/crlf), and the write is atomic.

    python3 edit_call_scenarios.py [call_scenarios.py]
"""
import os
import sys
import tempfile

MARK = "[s3-dice4]"
p = sys.argv[1] if len(sys.argv) > 1 else "call_scenarios.py"
raw = open(p, "rb").read().decode("utf-8")
if MARK in raw:
    print("call_scenarios already carries %s - nothing to do" % MARK)
    sys.exit(0)
crlf = "\r\n" in raw          # the host's working copy is CRLF (git: i/lf w/crlf): keep it
s = raw.replace("\r\n", "\n")


def sub(old, new, count=1):
    global s
    n = s.count(old)
    assert n == count, (old[:70], n)
    s = s.replace(old, new)


sub('''def _draw(options: Sequence[dict[str, Any]], rng: Any) -> dict[str, Any]:
    value = rng.random()
''', '''def _option_label(option: Mapping[str, Any]) -> str:
    """What a recorded draw shows for one option: its id and its words."""
    words = str(option.get("cue") or option.get("text") or option.get("premise") or "")
    return "%s: %s" % (option.get("id"), words) if words else str(option.get("id") or "")


def _draw(options: Sequence[dict[str, Any]], rng: Any, what: str = "") -> dict[str, Any]:
    # [s3-dice4] A source with draw(what, labels, weights) makes the pick
    # itself, at exactly these weights (the station hands in System 3's dice,
    # which record the candidates and where the draw landed). A plain random()
    # source keeps the arithmetic below; so does an answer out of range.
    draw = getattr(rng, "draw", None)
    if callable(draw):
        at = draw(what, [_option_label(option) for option in options],
                  [float(option["weight"]) for option in options])
        if isinstance(at, int) and not isinstance(at, bool) and 0 <= at < len(options):
            return dict(options[at])
    value = rng.random()
''')

sub('''    beats = [{"beat": beat, **_draw(choices[beat], source)} for beat in BEATS]
    conclusion = _draw(clean["conclusion_pool"], source)
''', '''    beats = [{"beat": beat, **_draw(choices[beat], source, beat)} for beat in BEATS]   # [s3-dice4]
    conclusion = _draw(clean["conclusion_pool"], source, "conclusion")
''')

sub('''    The caller supplies a seeded ``random.Random`` when reproducibility is
    required; otherwise the station's usual random stream is used.
''', '''    The caller supplies a seeded ``random.Random`` when reproducibility is
    required; otherwise the station's usual random stream is used. A source
    with ``draw(what, labels, weights)`` (the station's System 3 dice) makes
    each weighted pick itself - ``what`` is the beat, or "conclusion".
''')

sub('''    ``target_heat`` uses the 0..1 scale. A catalog with no compatible enabled
    row yields None, so an existing case is not forced into the wrong tone.
''', '''    ``target_heat`` uses the 0..1 scale. A catalog with no compatible enabled
    row yields None, so an existing case is not forced into the wrong tone.
    An ``rng`` with ``draw(what, labels, weights)`` makes the pick itself.
''')

assert "\r" not in s
assert s.count(MARK) == 2, "the marker is on the two draw edits"
fd, tmp = tempfile.mkstemp(prefix=os.path.basename(p) + ".", dir=os.path.dirname(os.path.abspath(p)))
with os.fdopen(fd, "wb") as fh:
    fh.write((s.replace("\n", "\r\n") if crlf else s).encode("utf-8"))
os.chmod(tmp, os.stat(p).st_mode & 0o777)      # the module keeps its own mode (mkstemp is 0600)
os.replace(tmp, p)
print("call_scenarios edits applied (%s kept)" % ("CRLF" if crlf else "LF"))
