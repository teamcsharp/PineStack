"""[s3-mgrtopics] system3_runtime.py half of the manager's topic roulette.

  import         system3_mgrtopics (the tables and the draw), guarded: a host
                 without the module runs exactly as before.
  seed-tables    add_missing_default_tables adds MGRTOPIC1 / MGRSUB1 to a stored
                 config once (remembered in defaults_added, so a table the
                 operator deletes stays deleted). default_config() is untouched.
  manager-topic  Runtime.manager_topic(road): the three draws on the road's own
                 dice (the task's roll buffer, like every station roll), his
                 history (data/system3_mgrtopics.json: topics, sub messages,
                 approaches, newest first) read and written, the station's
                 topics board read through host.read_bombshells. The roll goes
                 on the task's buffer (kind "mgrtopic"), the Audit feed and GET
                 /api/system3/station; returns the rolled topic, approach, sub
                 message and the writer's direction - None when System 3 is off.
  absorb         _absorb_rolls turns a "mgrtopic" roll into its three decision
                 events (MGRTOPIC, MGRAPPROACH, MGRSUB - candidates, weights,
                 why, dice) on the round that is planned next on the task, and
                 conv["mgr_topic"].
  line-sheet     direct_line: the draws ride the manager's own turn (the
                 opener), and the running order the chapter's replies are
                 written from names the topic and the approach.
  export         namespace["system3_manager_topic"].

Anchors cut from HEAD cd976c2 (re-verified on 713c1b1), each unique (none inside another tool's stored
text). --check exits 0 ready / 2 applied / 1 anchors missing; --apply is
idempotent, asserts every anchor, writes LF atomically.
TARGET: system3_runtime.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

EDITS = [
    ('import',
     'from system3_store import System3Store\n',
     'from system3_store import System3Store\n'
     'try:                                      # [s3-mgrtopics] the manager\'s topic roulette\n'
     '    import system3_mgrtopics\n'
     'except ImportError:  # pragma: no cover - a host without the module runs as before\n'
     '    system3_mgrtopics = None\n',
     1),
    ('seed-tables',
     '                   if t["id"] not in have and t["id"] not in seen]\n',
     '                   if t["id"] not in have and t["id"] not in seen]\n'
     '        if system3_mgrtopics is not None:                                   # [s3-mgrtopics] his two tables, once\n'
     '            missing += [t for t in system3_mgrtopics.default_tables() if t["id"] not in have and t["id"] not in seen]\n',
     1),
    ('manager-topic',
     '    def _absorb_rolls(self, conv):\n',
     '    # --- [s3-mgrtopics] the station manager\'s topic roulette ------------------------\n'
     '    def _mgr_path(self):\n'
     '        return self.host.data_path("system3_mgrtopics.json")\n'
     '\n'
     '    def _mgr_hist(self):\n'
     '        """His history, newest first: {topics, subs, approaches} (read once)."""\n'
     '        hist = self.__dict__.get("mgr_hist")\n'
     '        if hist is None:\n'
     '            got = {}\n'
     '            try:\n'
     '                got = json.loads(Path(self._mgr_path()).read_text(encoding="utf-8"))\n'
     '            except (OSError, ValueError, TypeError, AttributeError):\n'
     '                got = {}\n'
     '            hist = system3_mgrtopics.history_note(got if isinstance(got, dict) else {}, None)\n'
     '            self.__dict__["mgr_hist"] = hist\n'
     '        return hist\n'
     '\n'
     '    def _mgr_save(self, hist):\n'
     '        snap = json.loads(json.dumps(hist))\n'
     '\n'
     '        def job():\n'
     '            try:\n'
     '                path = Path(self._mgr_path())\n'
     '                tmp = path.with_suffix(".json.tmp")\n'
     '                tmp.write_text(json.dumps(snap), encoding="utf-8")\n'
     '                tmp.replace(path)\n'
     '            except Exception as exc:  # noqa: BLE001\n'
     '                self.fail("manager topics history", exc)\n'
     '        if threading.current_thread().name.startswith("system3-store"):\n'
     '            job()\n'
     '        else:\n'
     '            _STORE_POOL.submit(job)\n'
     '\n'
     '    def _mgr_board(self):\n'
     '        """The station\'s topics board (the Topics board list), as the manager\'s\n'
     '        roll sees it: id, words, times sprung."""\n'
     '        try:\n'
     '            rows = self.host.read_bombshells() or []\n'
     '        except Exception:  # noqa: BLE001\n'
     '            return []\n'
     '        out = []\n'
     '        for r in rows:\n'
     '            if not isinstance(r, dict) or not r.get("id"):\n'
     '                continue\n'
     '            text = " ".join(str(r.get("text") or "").split())\n'
     '            if 12 <= len(text) <= 400:\n'
     '                out.append({"id": str(r["id"]), "text": text, "used": int(r.get("used") or 0)})\n'
     '        out.sort(key=lambda r: r["used"])\n'
     '        return out[:system3_mgrtopics.BOARD_MOST]\n'
     '\n'
     '    def manager_topic(self, road="upstairs"):\n'
     '        """[s3-mgrtopics] The manager is writing a message downstairs: System 3\n'
     '        rolls its main topic (his MGRTOPIC tables and the station\'s topics\n'
     '        board, his recent topics held out or rested), his approach and the\n'
     '        sub message (MGRSUB). Rolled on the task\'s dice and recorded: the\n'
     '        round planned next on this task takes the three draws as its events.\n'
     '        Returns what the writer is told, or None (System 3 off, nothing to\n'
     '        draw, a fault - the road as it was)."""\n'
     '        if system3_mgrtopics is None or not self._dice_live():\n'
     '            return None\n'
     '        try:\n'
     '            with self.lock:\n'
     '                hist = copy.deepcopy(self._mgr_hist())\n'
     '            buf = self._roll_buffer()\n'
     '            res = system3_mgrtopics.roll(self.config, buf["stream"], self._mgr_board(), hist["topics"],\n'
     '                                         hist["subs"], hist["approaches"][0] if hist["approaches"] else "")\n'
     '            if not res:\n'
     '                return None\n'
     '            new = system3_mgrtopics.history_note(hist, res)\n'
     '            with self.lock:\n'
     '                self.__dict__["mgr_hist"] = new\n'
     '            self._mgr_save(new)\n'
     '            last = dict(res["events"][-1]["rng"])\n'
     '            small = {"kind": "mgrtopic", "key": system3_mgrtopics.ROLL_KEY, "road": str(road or ""),\n'
     '                     "label": ("the manager\'s message: " + res["topic_text"])[:90],\n'
     '                     "u": last["u"], "dice": last["dice"], "at": time.time(),\n'
     '                     "picked": " / ".join(x for x in (res["topic_text"], (res.get("approach") or {}).get("id", ""),\n'
     '                                                      (res.get("sub") or {}).get("text", "")) if x)[:160],\n'
     '                     "draws": [{"family": e["family"], "selected": (e.get("selected") or {}).get("id"),\n'
     '                                "dice": (e.get("rng") or {}).get("dice"), "u": (e.get("rng") or {}).get("u"),\n'
     '                                "of": (e.get("selected") or {}).get("of")} for e in res["events"]]}\n'
     '            buf["rolls"] = (buf["rolls"] + [dict(small, result=res)])[-ROLLS_KEPT:]\n'
     '            self.station_rolls.append(small)\n'
     '            by_key = getattr(_S3_LAST, "by_key", None)\n'
     '            if by_key is None:\n'
     '                by_key = _S3_LAST.by_key = {}\n'
     '            by_key[small["key"]] = small\n'
     '            self.observe_later("station:" + time.strftime("%Y%m%d%H", time.gmtime()), "STATION", small)\n'
     '            out = system3_mgrtopics.public(res)\n'
     '            out["dice"] = [d["dice"] for d in small["draws"]]\n'
     '            return out\n'
     '        except Exception as exc:  # noqa: BLE001\n'
     '            self.fail("manager topic", exc)\n'
     '            return None\n'
     '\n'
     '    def _absorb_rolls(self, conv):\n',
     1),
    ('absorb',
     '        for r in rolls:\n'
     '            before = system3._snapshot(conv, (conv.get("cursor") or {}).get("initiator"))\n',
     '        for r in rolls:\n'
     '            before = system3._snapshot(conv, (conv.get("cursor") or {}).get("initiator"))\n'
     '            if r.get("kind") == "mgrtopic" and system3_mgrtopics is not None:   # [s3-mgrtopics] three draws\n'
     '                system3_mgrtopics.absorb(conv, r, before, ctx0)\n'
     '                continue\n',
     1),
    ('line-sheet',
     '            handle.sheet = system3.render_legs_sheet(conv) if handle.active else ""\n',
     '            handle.sheet = system3.render_legs_sheet(conv) if handle.active else ""\n'
     '            if system3_mgrtopics is not None and conv.get("mgr_topic"):     # [s3-mgrtopics]\n'
     '                system3_mgrtopics.attach(conv)                            # his turn wears the draws\n'
     '                if handle.active:                                          # the replies answer the topic\n'
     '                    handle.sheet += system3_mgrtopics.sheet_line(conv)\n',
     1),
    ('export',
     '    namespace["system3_event_facts"] = rt.event_facts_text             # [s3-live-event]\n',
     '    namespace["system3_event_facts"] = rt.event_facts_text             # [s3-live-event]\n'
     '    namespace["system3_manager_topic"] = rt.manager_topic              # [s3-mgrtopics]\n',
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
    target = next((a for a in argv if not a.startswith("--")), "system3_runtime.py")
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
