"""[s3-mgrtopics] app.py half of the manager's topic roulette.

The operator, 2026-09-28: "have the manager rolling the roulette for saying any
topic from the topics list at random in his message to the DJs downstairs ...
I dont want him saying the same things over and over ... a topics database of
his own ... a sub message based on the topic that he uses to further
intimidate / ingratiate / horrify / attempt to discuss with."

  helpers          _s3_manager_topic(road) asks System 3 (system3_manager_topic)
                   for the roll - None when System 3 is off or faults: the road
                   as it was; _s3_manager_topic_react(page) for the studio.
  page-topic       dj_upstairs_write: the page's subject is System 3's MGRTOPIC
                   roll; the gripe book's draw (s3_unrepeated) runs only when
                   there is no roll (the original line is kept, re-indented under
                   `if not gripe:` - system3_dice_segments_patch still finds it).
  page-direction   the rolled topic, approach and sub message reach his writer as
                   binding direction (the three draws also land on his line's
                   node, and the running order the studio's replies are written
                   from names them - system3_mgrtopics_runtime_patch).
  page-keeps       the page row keeps what it was rolled (mgr_topic), so a page
                   recorded now and aired later still carries it.
  update-keeps     upstairs_update stores mgr_topic.
  page-react       the studio's fallback reaction (no chapter) is told the topic.
  memo-*           the memo road's gripe branch (the manager.gripe chance, its
                   desk dial manager_gripe_pct) takes the rolled topic instead of
                   the gripe book's least-used row, and the pair are told the
                   approach and the sub message; the three draws land on the
                   memo's round (the next plan on the task).

Anchors cut from HEAD cd976c2 (re-verified on 713c1b1), each unique; no edit changes text another tool
stored (static scan of tools/*.py: the gripe line keeps its words as a
substring; the page-keeps insert lands before system3_split_patch's block, not
inside it; update-keeps appends after its elif). --check exits 0 ready / 2
applied / 1 anchors missing; --apply is idempotent, asserts every anchor,
writes LF atomically. Needs system3_mgrtopics_runtime_patch for the roll
(without it every helper answers None and both roads run as before).
TARGET: app.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

EDITS = [
    ('helpers',
     'async def dj_upstairs_write() -> dict[str, Any]:\n',
     '# --- [s3-mgrtopics] THE MANAGER\'S TOPIC ROULETTE -------------------------------\n'
     '#\n'
     '# The operator, 2026-09-28: "have the manager rolling the roulette for saying any\n'
     '# topic from the topics list at random in his message to the DJs downstairs ... I\n'
     '# dont want him saying the same things over and over ... a topics database of his\n'
     '# own ... a sub message based on the topic that he uses to further intimidate /\n'
     '# ingratiate / horrify / attempt to discuss with." System 3 rolls it\n'
     '# (system3_mgrtopics: MGRTOPIC1 his topics + the station\'s topics board, MGRSUB1\n'
     '# the sub messages by approach, both in the Tables tab); the three draws land on\n'
     '# the round planned next on this task - his page\'s node, or the memo\'s round.\n'
     'def _s3_manager_topic(road: str) -> dict[str, Any] | None:\n'
     '    """The manager\'s topic, approach and sub message, rolled - or None (System\n'
     '    3 off, nothing to draw, a fault): the road as it was."""\n'
     '    fn = globals().get("system3_manager_topic")\n'
     '    if not callable(fn):\n'
     '        return None\n'
     '    try:\n'
     '        got = fn(road=road)\n'
     '    except Exception as exc:  # noqa: BLE001\n'
     '        pipeline_log("system3", "[s3-mgrtopics] the manager\'s topic roll failed - the road as it was",\n'
     '                     extra=("%s: %s" % (type(exc).__name__, exc))[:200])\n'
     '        return None\n'
     '    if not isinstance(got, dict) or not got.get("topic_text"):\n'
     '        return None\n'
     '    pipeline_log("system3", "[s3-mgrtopics] the manager\'s %s: %s (%s)"\n'
     '                 % ("memo" if road == "memo" else "page", str(got["topic_text"])[:90],\n'
     '                    str((got.get("approach") or {}).get("id") or "no approach")))\n'
     '    return got\n'
     '\n'
     '\n'
     'def _s3_manager_topic_react(made: dict[str, Any]) -> str:\n'
     '    """The studio\'s answer to a page knows what it was about, and how he came at them."""\n'
     '    mt = made.get("mgr_topic") if isinstance(made.get("mgr_topic"), dict) else {}\n'
     '    if not mt.get("topic_text"):\n'
     '        return ""\n'
     '    ap = mt.get("approach") if isinstance(mt.get("approach"), dict) else {}\n'
     '    return ("(System 3 rolled his message: the topic was %s%s - answer THAT, by name.) "\n'
     '            % (str(mt["topic_text"])[:240],\n'
     '               ("; he came at you to %s" % str(ap.get("label") or "").lower()) if ap.get("label") else ""))\n'
     '\n'
     '\n'
     'async def dj_upstairs_write() -> dict[str, Any]:\n',
     1),
    ('page-topic',
     '    gripe = s3_unrepeated("manager.page_gripe", list(UPSTAIRS_GRIPES), "upstairs-gripe", "what the page from upstairs is on about")   # [s3-dice-door]\n',
     '    # [s3-mgrtopics] the main topic, the approach and the sub message are System\n'
     '    # 3\'s roll (MGRTOPIC1 + the topics board, MGRSUB1); the gripe book only\n'
     '    # when there is no roll\n'
     '    _mgr = _s3_manager_topic("upstairs")\n'
     '    gripe = str((_mgr or {}).get("topic_text") or "")[:300]\n'
     '    if not gripe:\n'
     '        gripe = s3_unrepeated("manager.page_gripe", list(UPSTAIRS_GRIPES), "upstairs-gripe", "what the page from upstairs is on about")   # [s3-dice-door]\n',
     1),
    ('page-direction',
     '        f"What you are on about this time: {gripe}.\\n"\n',
     '        f"What you are on about this time: {gripe}.\\n"\n'
     '        + str((_mgr or {}).get("direction") or "")               # [s3-mgrtopics] binding\n',
     1),
    ('page-keeps',
     '    if _s3l is not None and _s3l.active and isinstance(row, dict) and row.get("id"):   # [s3-split] the page, shared out\n',
     '    if _mgr and isinstance(row, dict) and row.get("id"):                 # [s3-mgrtopics] what it was rolled\n'
     '        _mgr_keep = {k: _mgr[k] for k in ("key", "topic_text", "topic", "group", "approach", "sub", "dice")\n'
     '                     if _mgr.get(k) is not None}\n'
     '        try:\n'
     '            upstairs_update(str(row.get("id") or ""), mgr_topic=_mgr_keep)\n'
     '            row["mgr_topic"] = _mgr_keep\n'
     '        except Exception:  # noqa: BLE001\n'
     '            pass\n'
     '    if _s3l is not None and _s3l.active and isinstance(row, dict) and row.get("id"):   # [s3-split] the page, shared out\n',
     1),
    ('update-keeps',
     '                    row[key] = copy.deepcopy(value)\n'
     '            _upstairs_write(rows)\n',
     '                    row[key] = copy.deepcopy(value)\n'
     '                elif key == "mgr_topic" and isinstance(value, dict):   # [s3-mgrtopics] what the page was rolled\n'
     '                    row[key] = copy.deepcopy(value)\n'
     '            _upstairs_write(rows)\n',
     1),
    ('page-react',
     '            f"for word, was: \\"{spoken[:900]}\\" "\n',
     '            f"for word, was: \\"{spoken[:900]}\\" "\n'
     '            + _s3_manager_topic_react(made) +                          # [s3-mgrtopics]\n',
     1),
    ('memo-init',
     '    _gripe = ""\n'
     '    try:\n'
     '        if s3_chance("manager.gripe", float(dj_settings().get(\n',
     '    _mgr_memo: dict[str, Any] = {}          # [s3-mgrtopics] the memo\'s topic, when System 3 rolls it\n'
     '    _gripe = ""\n'
     '    try:\n'
     '        if s3_chance("manager.gripe", float(dj_settings().get(\n',
     1),
    ('memo-topic',
     '            _rows = [r for r in upstairs_list()\n'
     '                     if str(r.get("gripe") or "").strip()]\n'
     '            if _rows:\n',
     '            _rows = [r for r in upstairs_list()\n'
     '                     if str(r.get("gripe") or "").strip()]\n'
     '            _mgr_memo = _s3_manager_topic("memo") or {}          # [s3-mgrtopics] his topic, rolled\n'
     '            if _mgr_memo:\n'
     '                _gripe, _rows = str(_mgr_memo.get("topic_text") or "")[:200], []\n'
     '            if _rows:\n',
     1),
    ('memo-direction',
     '                "been listening.\\n") if _topic else "")\n'
     '            +\n',
     '                "been listening.\\n") if _topic else "")\n'
     '            + str(_mgr_memo.get("memo_direction") or "") +       # [s3-mgrtopics] the approach, the sub message\n',
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
    target = next((a for a in argv if not a.startswith("--")), "app.py")
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
