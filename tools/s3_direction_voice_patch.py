#!/usr/bin/env python3
"""[s3-direction] The rolled feeling reaches the take on the two roads that lost it.

MEASURED 2026-09-29 (tools/es_coverage.py --n 400, and 770 aired lines over 3 h):
  R1  app.py _s3_chapter_voice renders a chapter's reply rows with
      _s3_split_render(text, role, voice) and NO stamp, so the take is cut with
      the seat's plain delivery: every Mode B beat and chapter-repair line aired
      "intended, not baked" (180 of 770; es_coverage's dj_speak/stamp road 0%).
      The row already carries its own stamp (system3_runtime.line_chapter).
  R2  system3_runtime perf_state/perf_voice find the chunk's turn by its EXACT
      words in the round's script; a chunk the air path reworded (tint, a
      disfluency, a repeat swap) finds none and renders flat: 15% of the
      speak_turns/coalesced takes ("the round's turn carried no ES voice").
      The fallback is the seat's turn whose words the chunk shares most (>= 60%),
      for the voice only - the ledger link keeps its exact match.

Targets: app.py, system3_runtime.py and the chapter suite's render fake
(tests/test_system3_exchange_chain_app.py, which had no `stamp`) under the repo root given (default ".").
--check 0 ready / 2 applied / 1 missing or partial; --apply idempotent (markers),
atomic, keeps each file's line endings. ON THE HOST.
"""
import sys

APP = "app.py"
RT = "system3_runtime.py"
FAKE = "tests/test_system3_exchange_chain_app.py"   # its chapter render fake, to the real signature

EDITS = [
    (APP, "chapter-voice-stamp",
     '            clip = await _s3_split_render(str(row.get("text") or ""), role, voice)\n',
     '            clip = await _s3_split_render(str(row.get("text") or ""), role, voice,\n'
     '                                          stamp=row.get("stamp"))   # [s3-direction] the row\'s own feeling\n',
     '# [s3-direction] the row\'s own feeling\n'),

    (FAKE, "chapter-fake-takes-the-stamp",
     '    async def render(self, text, who, voice):\n'
     '        self.renders += 1\n',
     '    async def render(self, text, who, voice, stamp=None):   # [s3-direction] as the real one: the row\'s stamp\n'
     '        self.renders += 1\n',
     '# [s3-direction] as the real one: the row\'s stamp\n'),

    (RT, "loose-turn",
     '    def turn_id_for(self, meta, text, who=""):\n',
     '    def _turn_of_loose(self, meta, text, who=""):\n'
     '        """[s3-direction] The script index of a chunk whose exact words are not in\n'
     '        the round\'s script (the air path reworded it): the seat\'s turn whose words\n'
     '        it shares most, at least 60% of the chunk\'s words, else None. For the\n'
     '        voice only - the ledger link keeps the exact match."""\n'
     '        try:\n'
     '            s3 = (meta or {}).get("system3") or {}\n'
     '            cid = s3.get("conversation_id")\n'
     '            if not cid:\n'
     '                return None\n'
     '            script = str(meta.get("script") or "")\n'
     '            key = cid + ":" + hashlib.md5(script.encode("utf-8")).hexdigest()[:10]\n'
     '            if self.turns_cache.get(key) is None:\n'
     '                self._turn_of(meta, text, who)                                # it fills the cache\n'
     '            turns = self.turns_cache.get(key) or []\n'
     '            words = re.findall(r"[a-z0-9\']+", str(text or "").lower())\n'
     '            if len(words) < 3:\n'
     '                return None\n'
     '            seat = _SEAT_OF.get(str(who or ""), "")\n'
     '            best, best_i = 0.0, None\n'
     '            for i, (m, said) in enumerate(turns):\n'
     '                if seat and str(m)[:1] != seat:\n'
     '                    continue\n'
     '                have = set(re.findall(r"[a-z0-9\']+", str(said or "").lower()))\n'
     '                share = sum(1 for w in words if w in have) / float(len(words))\n'
     '                if share > best:\n'
     '                    best, best_i = share, i\n'
     '            return best_i if best >= 0.6 else None\n'
     '        except Exception as exc:  # noqa: BLE001\n'
     '            self.fail("loose turn", exc)\n'
     '            return None\n'
     '\n'
     '    def turn_id_for(self, meta, text, who=""):\n',
     '    def _turn_of_loose(self, meta, text, who=""):\n'),

    (RT, "perf-state-loose",
     '            _cid, i = self._turn_of(entry, text, who)\n'
     '            if i is None:\n'
     '                return None\n'
     '            stamp = (((entry.get("turn_dice") or {}).get(str(i)) or {}).get("s3") or {})\n'
     '            dims = (stamp.get("perf") or {}).get("dims")\n',
     '            _cid, i = self._turn_of(entry, text, who)\n'
     '            if i is None:\n'
     '                i = self._turn_of_loose(entry, text, who)                     # [s3-direction] reworded on the way\n'
     '            if i is None:\n'
     '                return None\n'
     '            stamp = (((entry.get("turn_dice") or {}).get(str(i)) or {}).get("s3") or {})\n'
     '            dims = (stamp.get("perf") or {}).get("dims")\n',
     '# [s3-direction] reworded on the way\n'),

    (RT, "perf-voice-loose",
     '            _cid, i = self._turn_of(entry, text, who)\n'
     '            if i is None:\n'
     '                return None\n'
     '            stamp = (((entry.get("turn_dice") or {}).get(str(i)) or {}).get("s3") or {})\n'
     '            got = (stamp.get("perf") or {}).get("voice")\n',
     '            _cid, i = self._turn_of(entry, text, who)\n'
     '            if i is None:\n'
     '                i = self._turn_of_loose(entry, text, who)                     # [s3-direction] its voice too\n'
     '            if i is None:\n'
     '                return None\n'
     '            stamp = (((entry.get("turn_dice") or {}).get(str(i)) or {}).get("s3") or {})\n'
     '            got = (stamp.get("perf") or {}).get("voice")\n',
     '# [s3-direction] its voice too\n'),
]

# --- the edit engine (shared by the s3_direction_* tools) ---
import os
import tempfile
from pathlib import Path


def _load(root, rel):
    raw = (Path(root) / rel).read_bytes().decode("utf-8")
    crlf = raw.count("\r\n") > raw.count("\n") // 2 and "\r\n" in raw
    return raw.replace("\r\n", "\n"), crlf


def _state(text, anchor, marker):
    m = text.count(marker)
    if m == 1:
        return "applied", ""
    a = text.count(anchor)
    if m == 0 and a == 1:
        return "ready", ""
    return "missing", "marker %d time(s), anchor %d time(s) (want 1)" % (m, a)


def check(root, edits, quiet=False):
    files = {}
    for e in edits:
        if e[0] not in files:
            files[e[0]] = _load(root, e[0])
    states = []
    for rel, name, anchor, new, marker in edits:
        st, why = _state(files[rel][0], anchor, marker)
        states.append((rel, name, st, why))
        if not quiet:
            print("%-8s %s: %s %s" % (st, rel, name, why))
    return states, files


def verdict(states):
    kinds = {s[2] for s in states}
    if kinds == {"ready"}:
        return 0
    if kinds == {"applied"}:
        return 2
    return 1


def apply(root, edits):
    states, files = check(root, edits, quiet=True)
    if verdict(states) == 2:
        print("already applied (%d edits)" % len(states))
        return 2
    if any(s[2] == "missing" for s in states):
        for s in states:
            print("%-8s %s: %s %s" % (s[2], s[0], s[1], s[3]))
        return 1
    texts = {rel: files[rel][0] for rel in files}
    for (rel, name, anchor, new, marker), (_r, _n, st, _w) in zip(edits, states):
        if st == "applied":
            continue
        assert texts[rel].count(anchor) == 1, name
        texts[rel] = texts[rel].replace(anchor, new, 1)
        assert texts[rel].count(marker) == 1, "%s: marker not unique after the edit" % name
    for rel, text in texts.items():
        path = Path(root) / rel
        out = text.replace("\n", "\r\n") if files[rel][1] else text
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
        with os.fdopen(fd, "wb") as fh:
            fh.write(out.encode("utf-8"))
        try:
            os.chmod(tmp, os.stat(path).st_mode & 0o777)
        except OSError:
            pass
        os.replace(tmp, path)
    states, _f = check(root, edits, quiet=True)
    if verdict(states) != 2:
        print("apply did not leave every edit applied")
        return 1
    print("applied %d edits" % len(edits))
    return 0


def main(argv, edits, doc):
    args = [a for a in argv if not a.startswith("--")]
    root = args[0] if args else "."
    if "--apply" in argv:
        return apply(root, edits)
    if "--check" in argv:
        states, _f = check(root, edits)
        return verdict(states)
    print(doc)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], EDITS, __doc__))
