#!/usr/bin/env python3
"""[h3-speak] ad-viewer.js (desk desktop/renderer + kiosk pine-views): the Prompts used sheet shows the
H3SPEAK dice in Hourly rolls and the node's record as 'Dialogue (H3SPEAK)'."""

# ---- the patch contract (marker-idempotent) --------------------------------
# --check PATH  exit 0 ready (every edit ready or applied, at least one ready),
#               2 applied (every edit applied), 1 missing (an anchor is gone).
# --apply PATH  applies the ready edits in order, writes LF atomically; exit 0
#               on success, 2 when there was nothing to do, 1 when missing.
# An edit is APPLIED when its marker (a line only its inserted text has) is in
# the file, READY when its anchor occurs exactly once, else MISSING.
import os
import sys
import tempfile


def state_of(text, edit):
    if edit["marker"] in text:
        return "applied"
    n = text.count(edit["anchor"])
    return "ready" if n == 1 else ("missing (anchor x%d)" % n)


def apply_one(text, edit):
    if edit["kind"] == "replace":
        return text.replace(edit["anchor"], edit["text"], 1)
    if edit["kind"] == "before":
        return text.replace(edit["anchor"], edit["text"] + edit["anchor"], 1)
    if edit["kind"] == "after":
        return text.replace(edit["anchor"], edit["anchor"] + edit["text"], 1)
    raise ValueError(edit["kind"])


def run(edits, argv):
    if len(argv) != 3 or argv[1] not in ("--check", "--apply"):
        print("usage: %s --check|--apply PATH" % argv[0])
        return 1
    mode, path = argv[1], argv[2]
    with open(path, "r", encoding="utf-8", newline="") as fh:
        text = fh.read()
    text = text.replace("\r\n", "\n")
    states = []
    work = text
    for e in edits:                     # sequential: a later anchor may sit in an earlier edit's text
        st = state_of(work, e)
        states.append(st)
        print("  %-10s %s" % (st.split(" ")[0], e["name"]) + ("" if st in ("ready", "applied") else "  <- " + st))
        if st == "ready":
            work = apply_one(work, e)
    if any(s not in ("ready", "applied") for s in states):
        print("MISSING: %d of %d edits" % (sum(1 for s in states if s not in ("ready", "applied")), len(edits)))
        return 1
    if all(s == "applied" for s in states):
        print("APPLIED: all %d edits" % len(edits))
        return 2
    if mode == "--check":
        print("READY: %d to apply, %d applied" % (states.count("ready"), states.count("applied")))
        return 0
    for e in edits:
        if e["marker"] not in work:
            print("apply failed: %s did not land" % e["name"])
            return 1
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".h3speak.")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(work)
    try:
        os.chmod(tmp, os.stat(path).st_mode & 0o7777)
    except OSError:
        pass
    os.replace(tmp, path)
    print("applied %d edits -> %s" % (states.count("ready"), path))
    return 0


EDITS = [{'anchor': "    one('fresh pick', rolls.fresh); one('window marker', rolls.marker);\n"
            "    return bits.join('  -  ');\n",
  'kind': 'replace',
  'marker': "    one('dialogue kind', rolls.speak_lean);",
  'name': 'usedRolls: the H3SPEAK dice',
  'text': "    one('fresh pick', rolls.fresh); one('window marker', rolls.marker);\n"
          '    /* [h3-speak] the H3SPEAK node: what kind of aired talk, which line, the\n'
          '       Speakerbox document (no aired line passed), how many sentences, which ones */\n'
          "    one('dialogue kind', rolls.speak_lean); one('line said on air', rolls.speak_line);\n"
          "    one('speakerbox document', rolls.speak_doc); one('sentences to take', rolls.speak_count);\n"
          "    one('sentences', rolls.speak_sentences); one('forced line', rolls.speak_forced);\n"
          "    return bits.join('  -  ');\n"},
 {'anchor': "      add('Hourly rolls', usedRolls(rec.rolls), 'rolls');   /* [s3-visuals] the door's dice, "
            'when they rolled */\n',
  'kind': 'replace',
  'marker': "      add('Dialogue (H3SPEAK)', usedSpeak(rec.speak), 'speak');",
  'name': 'usedWords: the Dialogue node line',
  'text': "      add('Hourly rolls', usedRolls(rec.rolls), 'rolls');   /* [s3-visuals] the door's dice, when "
          'they rolled */\n'
          "      add('Dialogue (H3SPEAK)', usedSpeak(rec.speak), 'speak');   /* [h3-speak] where the words "
          'came from */\n'},
 {'anchor': '  function usedWords(row) {\n',
  'kind': 'before',
  'marker': '  function usedSpeak(sp) {',
  'name': 'usedSpeak()',
  'text': '  function usedSpeak(sp) {\n'
          "    /* [h3-speak] the H3SPEAK node's record: rolled from a line a person was\n"
          '       heard saying (who, when, the feeling System 3 rolled for it), from a\n'
          '       Speakerbox document, or FORCED and why. */\n'
          "    if (!sp || typeof sp !== 'object') return '';\n"
          "    var took = sp.count && sp.count.took ? sp.count.took + ' of ' + (sp.count.rolled || "
          'sp.count.took)\n'
          "      + ' sentence' + (sp.count.took === 1 ? '' : 's') : '';\n"
          "    if (sp.verdict === 'forced') {\n"
          "      return 'FORCED - ' + String(sp.forced_by || 'the forced line') + (sp.why ? ' (' + sp.why + "
          "')' : '');\n"
          '    }\n'
          "    if (sp.source === 'speakerbox') {\n"
          "      return 'rolled from the Speakerbox document ' + String(sp.doc || '?') + (took ? ': ' + took "
          ": '')\n"
          "        + (sp.why ? ' - no aired line passed' : '');\n"
          '    }\n'
          '    var s = sp.said || {};\n'
          '    var at = s.at ? new Date(Number(s.at) * 1000) : null;\n'
          "    var when = at && !isNaN(at) ? ' at ' + String(at.getHours()).padStart(2, '0') + ':'\n"
          "      + String(at.getMinutes()).padStart(2, '0') : '';\n"
          "    var feel = s.emotion ? ', feeling ' + s.emotion + (s.intensity != null ? ' ' + "
          "Number(s.intensity).toFixed(2) : '') : '';\n"
          "    return 'rolled from what ' + String(s.name || s.who || 'a voice') + ' said on air' + when\n"
          "      + (s.round ? ' (' + s.round + (s.turns > 1 ? ', a monologue of ' + s.turns + ' turns' : '') "
          "+ ')' : '')\n"
          "      + feel + (took ? ': ' + took : '');\n"
          '  }\n'}]

if __name__ == "__main__":
    sys.exit(run(EDITS, sys.argv))
