"""[line-roll] the speakbox rolls the document, then rolls through its lines.

2026-09-30, the operator: "There shouldn't be a single document being
referred to. It should be subjected to the roulette where it rolls through the
documents and then it rolls through the lines."

The document was already a System 3 roll (speakbox.doc through unrepeated's
director, the theme/archive/newest bands). The lines were not: one bare
s3_roll number picked where the swath started and the next `most` lines were
taken verbatim - so a roulette had nothing to show but a float, and a round
read as one document recited in order.

Now the start is a draw over the document's own lines (labelled with their
words, so the rolodex rolls through them), and every line after it is rolled
too: the next line is the likeliest, one or two further on can come up, and
nothing goes backwards - the thought still runs forward through the passage.

Usage (ON THE HOST): python3 tools/line_roll_patch.py --check|--apply app.py
"""
import ast
import shutil
import sys

MARK = "[line-roll]"

OLD = '''    _lo = min(floor, last - 1)          # randrange(_lo, last); 0 at rest   # [s3-dice-door]
    start = min(last - 1, _lo + int(s3_roll("speakbox.swath_start", "where in the document the swath starts")   # [s3-dice-door]
                                    * (last - _lo)))   # [s3-dice-door]
    swath = [pool[start]]
    for line in pool[start + 1:start + most]:
        if len(" ".join(swath)) + len(line) + 1 > cap:
            break
        swath.append(line)
    return swath
'''
NEW = '''    _lo = min(floor, last - 1)          # randrange(_lo, last); 0 at rest   # [s3-dice-door]
    # [line-roll] the start is a roll over the document's own lines
    _starts = list(range(_lo, last))
    if len(_starts) > 120:
        _step = len(_starts) / 120.0
        _starts = [_starts[int(i * _step)] for i in range(120)]
    start = _starts[s3_weighted("speakbox.swath_start",
                                [str(pool[i])[:140] for i in _starts],
                                [1.0] * len(_starts),
                                "which line of the document the swath starts on")]
    swath = [pool[start]]
    at = start
    # [line-roll] ...and so is every line after it: forward only, the next
    # line likeliest, one or two further on now and then
    while len(swath) < max(1, int(most)) and at + 1 < len(pool):
        _ahead = list(range(at + 1, min(len(pool), at + 4)))
        at = _ahead[s3_weighted("speakbox.swath_line",
                                [str(pool[i])[:140] for i in _ahead],
                                [8.0, 2.0, 1.0][:len(_ahead)],
                                "which line the swath rolls on to (the next is likeliest)")]
        line = pool[at]
        if len(" ".join(swath)) + len(line) + 1 > cap:
            break
        swath.append(line)
    return swath
'''


def main() -> None:
    mode, path = sys.argv[1], sys.argv[2]
    src = open(path, encoding="utf-8").read()
    if MARK in src:
        print(path + ": APPLIED")
        return
    assert src.count(OLD) == 1, "anchor %d" % src.count(OLD)
    out = src.replace(OLD, NEW)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready (1 edit)")
        return
    shutil.copy(path, "/tmp/app.py.bak-line-roll")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src, "app.py changed underfoot"
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")


if __name__ == "__main__":
    main()
