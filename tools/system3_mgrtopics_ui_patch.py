"""[s3-mgrtopics] frontend/system3.js half of the manager's topic roulette.

  families   the Tables tab lists MGRTOPIC (his topics database) and MGRSUB (the
             sub messages by approach) - add / edit / re-weight / switch off /
             remove rows like any table.
  explain    the three draws' colours and what they are, for the Rolodex chips
             and the decision card (MGRTOPIC, MGRAPPROACH, MGRSUB).
  sub-topics an MGRSUB item's "only for topics" field (MGRTOPIC1 row ids; blank:
             any topic).

Anchors cut from HEAD cd976c2 (re-verified on 713c1b1), each unique; none in another tool's stored text.
--check exits 0 ready / 2 applied / 1 anchors missing; --apply is idempotent,
asserts every anchor, writes LF atomically. The page loads system3.js with a
?v= - bump it at deploy (see system3-window).
TARGET: frontend/system3.js
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

EDITS = [
    ('families',
     "  const TABLE_FAMILIES = ['CTS', 'ES', 'RS', 'IRS', 'FL', 'TEMPER', 'SHOCK', 'INTERJECT', 'SPEAKERBOX', 'FAV', 'DIRECTIVE', 'EVENT', 'CHANCE', 'POOL', 'RESOLVE', 'WRAP', 'IL'];   /* [s3-sb-end] SBEND1 */\n",
     "  const TABLE_FAMILIES = ['CTS', 'ES', 'RS', 'IRS', 'FL', 'TEMPER', 'SHOCK', 'INTERJECT', 'SPEAKERBOX', 'FAV', 'DIRECTIVE', 'EVENT', 'CHANCE', 'POOL', 'RESOLVE', 'WRAP', 'IL',\n"
     "    'MGRTOPIC', 'MGRSUB'];   /* [s3-sb-end] SBEND1 - [s3-mgrtopics] the manager's topics and sub messages */\n",
     1),
    ('explain',
     "/* [s3-callend] how a call ends: the caller's wheel and the wrap call */\n",
     "/* [s3-mgrtopics] the manager's message downstairs: its main topic, his approach, the sub message */\n"
     "Object.assign(FAM, {MGRTOPIC: 'var(--topic)', MGRAPPROACH: 'var(--rs)', MGRSUB: 'var(--irs)'});\n"
     "Object.assign(FAMILY_WHAT, {\n"
     "  MGRTOPIC: [\"The manager's topic (MGRTOPIC1 + the topics board)\",\n"
     "    \"The main topic of the station manager's message downstairs. Two stages: a group of his own topics or the station's topics board (each group's weight), then the topic. A topic he said in his last few messages cannot come up and one said a little longer ago weighs less (the 'rest' knobs on MGRTOPIC1); a row switched off never lands. Edited in Tables > MGRTOPIC1 (the board is the Topics board list).\"],\n"
     "  MGRAPPROACH: [\"The manager's approach (MGRSUB1)\",\n"
     "    \"How he comes at them about the topic: intimidate, ingratiate, horrify or discuss - the categories of MGRSUB1, each weight its odds. The approach he used last time weighs half.\"],\n"
     "  MGRSUB: [\"The manager's sub message (MGRSUB1)\",\n"
     "    \"The angle he uses on the topic, inside the approach drawn ({topic} is the topic). A row written for particular topics only comes up for them, and weighs three times as much when it does; one he used in his last few messages is out. Edited in Tables > MGRSUB1.\"],\n"
     "});\n"
     "/* [s3-callend] how a call ends: the caller's wheel and the wrap call */\n",
     1),
    ('sub-topics',
     "  function poolFields(item) {\n",
     "  function mgrSubFields(item) {   /* [s3-mgrtopics] a sub message kept to some of his topics */\n"
     "    return el('div', 's3-row s3-pool', el('label', {class: 's3-muted', text: 'only for topics'}),\n"
     "      el('input', {type: 'text', value: (item.topics || []).join(', '), placeholder: 'MGRTOPIC1 row ids, e.g. consultant (blank = any topic)',\n"
     "        style: 'min-width:16em', 'aria-label': 'only for these topics',\n"
     "        onchange: e => { const got = e.target.value.split(',').map(x => x.trim()).filter(Boolean); if (got.length) item.topics = got; else delete item.topics; }}));\n"
     "  }\n"
     "  function poolFields(item) {\n"
     "    if (draft.family === 'MGRSUB') return mgrSubFields(item);   /* [s3-mgrtopics] */\n",
     1),
]


def plan(text):
    return EDITS


def state_of(text, old, new, count):
    n_new = text.count(new)
    n_old = text.count(old)
    if n_new >= 1 and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and n_old == count:
        return "ready"
    return "anchor found %d times, wanted %d; replacement found %d times" % (n_old, count, n_new)


def check(text):
    applied, missing = 0, []
    for name, old, new, count in plan(text):
        state = state_of(text, old, new, count)
        if state == "applied":
            applied += 1
        elif state != "ready":
            missing.append("%s (%s)" % (name, state))
    return applied, missing


def apply(path):
    path = Path(path)
    text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    edits = plan(text)
    if applied == len(edits):
        return 2
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    for name, old, new, count in edits:
        if state_of(text, old, new, count) == "applied":
            continue
        assert text.count(old) == count, "%s: anchor found %d times" % (name, text.count(old))
        text = text.replace(old, new)
    assert "\r" not in text
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    with os.fdopen(fd, "wb") as fh:
        fh.write(text.encode("utf-8"))
    try:
        shutil.copymode(str(path), tmp)
    except OSError:
        pass
    os.replace(tmp, path)
    return 0


def main(argv):
    do_apply = "--apply" in argv
    target = next((a for a in argv if not a.startswith("--")), "frontend/system3.js")
    if do_apply:
        code = apply(target)
        print({0: "APPLIED", 1: "ANCHORS MISSING - nothing written", 2: "already applied"}[code])
        return code
    text = Path(target).read_bytes().decode("utf-8").replace("\r\n", "\n")
    applied, missing = check(text)
    total = len(plan(text))
    if missing:
        for m in missing:
            print("missing:", m)
        print("%d of %d applied" % (applied, total))
        return 1
    if applied == total:
        print("already applied (%d edits)" % total)
        return 2
    print("ready: %d edits, %d already in" % (total, applied))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
