"""[s3-account-p2] system3_origin.py: a line keeps its origin across a restart.

Measured 2026-09-29 (6 h of air, 3,129 items): every rogue item (24 of 24) was
a System 3 line republished by boot recovery (page_recovery_chat_rows <
page_recovery_start). The preserved page delivery carries the row's id, who,
kind and words but NOT its System 3 stamp; after the restart the ledger's
in-memory joins (script rows noted since boot, _S3_LINE_BY_ID) are empty, so
the rebuilt record said "no System 3 stamp" and OVERWROTE the line's traced
record. 22 of the 24 are in System 3's own line register (lines table); the
manager page is the opening of chapter bb939c0c (its stamp lived on the ring
row the restart dropped).

Fix, in the ledger that owns the verdict (no gate, no new road):
  - _durable_origin(): an unstamped row reads its origin back from the two
    durable records that outlive the process - System 3's line register, then
    this ledger's own record of the same id when that one was traced (rolled:
    its stamp; forced: its named reason). Memoised per id; a miss is re-read
    after 60 s. Nothing known: the row stays what it is (rogue, alarmed).
  - a republished row's record says so ("republished": boot recovery).
  - build(): an observation whose "lines" is a count, not a list, no longer
    raises (it crashed tools/s3_origin_replay.py; live it would drop the item
    from the ledger silently - the tick swallows its error).

  python tools/p2_origin_patch.py --check system3_origin.py   (0 ready, 2 applied, 1 anchor missing)
  python tools/p2_origin_patch.py --apply system3_origin.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from s3_account_p2_lib import Edit, run  # noqa: E402

MARKER = "[s3-account-p2]"

EDITS = [
    Edit("obs-lines-int",
         '        "observations": [o for o in obs if isinstance(o, dict) and lid and lid in (o.get("lines") or [])][:8],\n',
         replace=(
             '        "observations": [o for o in obs if isinstance(o, dict) and lid   # [s3-account-p2] "lines" may be a count\n'
             '                         and lid in (o.get("lines") if isinstance(o.get("lines"), (list, tuple)) else ())][:8],\n')),
    Edit("compact-via",
         '                                      ("config_hash", s.get("config_hash")),\n',
         '                                      ("via", s.get("via")),   # [s3-account-p2] how the stamp was known\n'),
    Edit("init-recovered",
         "        self._shared: dict[str, int] = {}    # turns / conversations written, by what was known\n",
         "        self._recovered: \"collections.OrderedDict[str, tuple]\" = collections.OrderedDict()   # [s3-account-p2]\n"),
    Edit("build-live-durable",
         "        if stamp is None and m:\n            stamp, pforced = self._parent_stamp(e, m.group(1))\n",
         "        if stamp is None and not m and not e.get(\"origin_forced\"):   # [s3-account-p2] a row that lost its stamp\n"
         "            stamp, e = self._durable_origin(e, lid)\n",
         where="before"),
    Edit("build-live-republished",
         "        rec = build(e, led, stamp, conv, context)\n",
         "        if e.get(\"recovery\"):                    # [s3-account-p2] boot recovery put it back on the air\n"
         "            rec[\"compact\"][\"republished\"] = \"after a restart, by boot recovery (page_recovery_start)\"\n"
         "            if e.get(\"recovered_from\"):\n"
         "                rec[\"compact\"][\"recovered_from\"] = str(e[\"recovered_from\"])[:48]\n"),
    Edit("durable-origin-method",
         "    def _parent_stamp(self, e: dict[str, Any], parent_id: str) -> tuple[Any, Any]:\n",
         '''    def _durable_origin(self, e: dict[str, Any], lid: str) -> tuple[Any, dict[str, Any]]:
        """[s3-account-p2] A row that reaches the ring WITHOUT its stamp (a
        preserved delivery republished after a restart, page_recovery_chat_rows;
        a ring row restored at boot) is still the line System 3 made. Its
        origin is read back from the two durable records that outlive the
        process - never guessed: (1) System 3's own line register (the lines
        table: line -> conversation, turn); (2) this ledger's record of the
        same line id from before, when that one was traced (rolled: its stamp;
        forced: its named reason). Neither: the row stands as it is. Returns
        (stamp or None, the row - with origin_forced when a forced reason came
        back). Memoised per id; a miss is looked up again after 60 s."""
        now = time.time()
        got = self._recovered.get(lid)
        if got is None or (not got[1] and not got[2] and now - got[0] > 60.0):
            stamp: dict[str, Any] = {}
            forced: dict[str, Any] | None = None
            # the line itself, then the heard line a recovered replay stands in for
            ids = [lid] + [str(x) for x in (e.get("recovered_from"),) if x and str(x) != lid]
            s3 = self._s3db()
            for key in ids:
                if stamp or s3 is None:
                    break
                try:
                    r = s3.execute("SELECT conversation_id, turn_id FROM lines WHERE line_id=?", (key,)).fetchone()
                except Exception:  # noqa: BLE001  (an older store with no line register)
                    r = None
                if r and r[0]:
                    stamp = {"conversation_id": str(r[0]), "turn_id": str(r[1] or ""),
                             "via": "System 3's line register" + ("" if key == lid else " (the line it replays, %s)" % key)}
            for key in ids:
                if stamp or forced:
                    break
                try:
                    prior = self.get(key)
                except Exception:  # noqa: BLE001
                    prior = None
                via = ("its origin record from before the restart" if key == lid
                       else "the origin record of the line it replays (%s)" % key)
                if isinstance(prior, dict) and not prior.get("announces"):
                    ps = prior.get("system3") or {}
                    pf = prior.get("forced") if isinstance(prior.get("forced"), dict) else None
                    if prior.get("verdict") == "rolled" and ps.get("conversation_id"):
                        stamp = {"conversation_id": str(ps["conversation_id"]), "turn_id": str(ps.get("turn_id") or ""),
                                 "via": via}
                    elif prior.get("verdict") == "forced" and pf and pf.get("road") != "desk label":
                        forced = dict(pf, how=via)
            got = (now, stamp, forced)
            self._recovered[lid] = got
            self._recovered.move_to_end(lid)
            while len(self._recovered) > 5000:
                self._recovered.popitem(last=False)
        stamp, forced = got[1], got[2]
        if forced and not e.get("origin_forced"):
            e = dict(e, origin_forced=dict(forced))
        return (dict(stamp) if stamp else None), e

''',
         where="before"),
]

if __name__ == "__main__":
    raise SystemExit(run(EDITS, MARKER))
