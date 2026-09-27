"""[s3-line-link] A line is linked to its System 3 node the moment it is
spoken - and so is a line the deck withdrew.

Measured 2026-09-27 (tools: dice_latency_probe.py, a ledger census): since
[s3-line-fix] the feed's dice door answers for an aired single line within a
second, from the stamp dj_speak remembers in memory (_S3_LINE_BY_ID) until the
script ledger commits the row about five seconds later. Two holes were left:

  1. A line the deck WITHDREW (a record-bound intro whose record moved on)
     never reaches the ledger, and its feed row was minted by
     record_bound_withdraw without the stamp the road passed in - so the
     row showed no dice and the tapped-line tabs said "not directed by
     System 3" about a line System 3 had planned (the probe: "Glada by
     Future Islands has a heavy, pulsating bassline", NEVER linked).
  2. The memory stamp dies with a restart; a line spoken seconds before one
     lost its link for good when its ledger commit never came.

So the station tells System 3's store at speak time (system3_link_line ->
LineLinker.link_spoken: an INSERT that never overwrites the ledger's own row,
on the store pool), and a withdrawn row carries its node's stamp and is
linked the same way. The ledger's commit still replaces the row with its
block and order.

Two files: system3_runtime.py (the method + its namespace name) and app.py
(_s3_line_remember links; record_bound_withdraw takes and carries the stamp;
its two callers pass it). --check exits 0 ready / 2 applied / 1 missing;
--apply writes both, LF, atomically. ON THE HOST, from fresh copies.
"""
import os
import sys
import tempfile
from pathlib import Path

RUNTIME_EDITS = [
    ("the-runtime-links-a-spoken-line",
     "    def bind_line(self, handle, text):\n",
     '''    def link_spoken(self, line_id, stamp, who="", text=""):
        """[s3-line-link] A line spoken with a System 3 stamp is linked in the
        lines table the moment it is spoken - not only when the script ledger
        commits it seconds later, and not never, as for a line the deck
        withdrew before it aired. The ledger's own row, when it comes, replaces
        this one with its block and order; this never overwrites it."""
        try:
            if not line_id or not isinstance(stamp, dict) or not stamp.get("conversation_id"):
                return
            row = {"line_id": str(line_id), "conversation_id": str(stamp["conversation_id"]),
                   "turn_id": str(stamp.get("turn_id") or "") or None, "block": None, "ord": None,
                   "sid": "", "who": str(who or ""), "text": str(text or "")[:2000], "at": time.time()}
            with self.lock:
                if self.pending >= WRITE_BACKLOG:
                    self.metrics["writes_dropped"] += 1
                    return
                self.pending += 1
                self.metrics["lines_linked_live"] = self.metrics.get("lines_linked_live", 0) + 1

            def job():
                try:
                    if not self.store.line(row["line_id"]):
                        self.store.add_lines([row])
                finally:
                    with self.lock:
                        self.pending -= 1
            _STORE_POOL.submit(job)
        except Exception as exc:  # noqa: BLE001
            self.fail("line link", exc)

    def bind_line(self, handle, text):
''', 1),
    ("the-station-can-ask-for-it",
     '    namespace["system3_bind_line"] = rt.bind_line\n',
     '    namespace["system3_bind_line"] = rt.bind_line\n'
     '    namespace["system3_link_line"] = rt.link_spoken                  # [s3-line-link]\n', 1),
]

APP_EDITS = [
    ("remember-also-links",
     'def _s3_line_remember(line_id: Any, stamp: Any) -> None:\n'
     '    if isinstance(stamp, dict) and stamp.get("conversation_id") and line_id:\n'
     '        _S3_LINE_BY_ID[str(line_id)] = dict(stamp)\n'
     '        while len(_S3_LINE_BY_ID) > 600:\n'
     '            _S3_LINE_BY_ID.pop(next(iter(_S3_LINE_BY_ID)))\n',
     'def _s3_line_remember(line_id: Any, stamp: Any, who: str = "", text: str = "") -> None:\n'
     '    if isinstance(stamp, dict) and stamp.get("conversation_id") and line_id:\n'
     '        _S3_LINE_BY_ID[str(line_id)] = dict(stamp)\n'
     '        while len(_S3_LINE_BY_ID) > 600:\n'
     '            _S3_LINE_BY_ID.pop(next(iter(_S3_LINE_BY_ID)))\n'
     '        # [s3-line-link] and linked in System 3\'s store now, not only when\n'
     '        # the ledger commits it - a withdrawn line never is committed\n'
     '        _link = globals().get("system3_link_line")\n'
     '        if _link:\n'
     '            try:\n'
     '                _link(str(line_id), stamp, str(who or ""), str(text or ""))\n'
     '            except Exception:  # noqa: BLE001\n'
     '                pass\n', 1),
    ("the-speaker-says-who-and-what",
     '    _s3_line_remember(line_id, system3)                      # [s3-roads]\n',
     '    _s3_line_remember(line_id, system3, who, spoken)         # [s3-roads][s3-line-link]\n', 1),
    ("a-withdrawn-row-takes-the-stamp",
     'def record_bound_withdraw(bound: Any, part: Any, who: str, kind: str,\n'
     '                          text: str, why: str,\n'
     '                          clip: dict[str, Any] | None = None) -> str:\n',
     'def record_bound_withdraw(bound: Any, part: Any, who: str, kind: str,\n'
     '                          text: str, why: str,\n'
     '                          clip: dict[str, Any] | None = None,\n'
     '                          system3: dict[str, Any] | None = None) -> str:   # [s3-line-link]\n', 1),
    ("a-withdrawn-row-carries-it",
     '            "bound": record_binding.snapshot(bound),\n'
     '            "bound_part": str(part or ""),\n'
     '        }\n'
     '        _RADIO["chat"].append(entry)\n',
     '            "bound": record_binding.snapshot(bound),\n'
     '            "bound_part": str(part or ""),\n'
     '        }\n'
     '        # [s3-line-link] the node the road planned for it: the feed shows its\n'
     '        # dice and the tapped-line tabs its story, withdrawn or not\n'
     '        if isinstance(system3, dict) and system3.get("conversation_id"):\n'
     '            entry["system3"] = dict(system3)\n'
     '            _s3_line_remember(rid, system3, str(who or ""), said)\n'
     '        _RADIO["chat"].append(entry)\n', 1),
    ("withdrawn-before-the-render-passes-it",
     '                record_bound_withdraw(bound, bound_part, who, kind,\n'
     '                                      line, _bound_why)\n',
     '                record_bound_withdraw(bound, bound_part, who, kind,\n'
     '                                      line, _bound_why, system3=system3)\n', 1),
    ("withdrawn-before-the-air-passes-it",
     '            record_bound_withdraw(bound, bound_part, who, kind, spoken,\n'
     '                                  _bound_why, clip)\n',
     '            record_bound_withdraw(bound, bound_part, who, kind, spoken,\n'
     '                                  _bound_why, clip, system3=system3)\n', 1),
]

FILES = {"system3_runtime.py": RUNTIME_EDITS, "app.py": APP_EDITS}


def plan(text, fname="app.py"):
    return list(FILES[fname])


def state_of(text, old, new, count):
    n_new, n_old = text.count(new), text.count(old)
    if n_new >= 1 and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and n_old == count:
        return "ready"
    return "anchor found %d times, wanted %d; replacement found %d times" % (n_old, count, n_new)


def check(text, fname="app.py"):
    applied, missing = 0, []
    for name, old, new, count in plan(text, fname):
        state = state_of(text, old, new, count)
        if state == "applied":
            applied += 1
        elif state != "ready":
            missing.append("%s: %s (%s)" % (fname, name, state))
    return applied, missing


def _read(path):
    return Path(path).read_bytes().decode("utf-8").replace("\r\n", "\n")


def apply(root):
    texts = {f: _read(os.path.join(root, f)) for f in FILES}
    total, done, missing = 0, 0, []
    for f, text in texts.items():
        a, m = check(text, f)
        done += a
        total += len(FILES[f])
        missing += m
    if done == total:
        return 2
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    for f, text in texts.items():
        for name, old, new, count in FILES[f]:
            if state_of(text, old, new, count) == "applied":
                continue
            text = text.replace(old, new)
        path = Path(root) / f
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
        with os.fdopen(fd, "wb") as fh:
            fh.write(text.encode("utf-8"))
        os.replace(tmp, path)
    return 0


def main(argv):
    root = next((a for a in argv if not a.startswith("--")), ".")
    if os.path.isfile(root):
        root = os.path.dirname(os.path.abspath(root)) or "."
    if "--apply" in argv:
        code = apply(root)
        print({0: "APPLIED", 1: "ANCHORS MISSING - nothing written", 2: "already applied"}[code])
        return code
    total, done, missing = 0, 0, []
    for f in FILES:
        a, m = check(_read(os.path.join(root, f)), f)
        done += a
        total += len(FILES[f])
        missing += m
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    if done == total:
        print("already applied")
        return 2
    print("ready")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
