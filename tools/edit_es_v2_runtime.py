"""[es-v2] system3_runtime.py gains the ONE-SHOT move of the stored ES tables to
ES1's second edition (system3_tables.ES1_V2: recalibrated voices, actor
directions - emotion engine steps 3 + 7), and the door the operator opens it by.

    POST /api/system3/es-v2?dry=1   what would move, and what is kept as edited
    POST /api/system3/es-v2         do it (once; remembered as ES_V2 in defaults_added)

On every ES-family table, a category or item whose id matches ES1 moves to its v2
voice / direction ONLY while it still holds exactly its v1 default (a voice block
equal to v1's after the station's own clean; a text equal to the v1 default
direction). A row the operator edited, cleared or removed stays as the operator
left it and is listed as kept. One config version, with a note. Not run at boot:
the stored defaults every existing test and golden pins stay v1 until the door is
opened (default_config and its hash are untouched), and nothing reaches the air
until the operator (or the deploy step) asks for it.

Marker-idempotent: --check exits 0 ready / 2 applied / 1 anchors missing;
--apply is atomic, LF only. Needs tools/edit_es_v2_tables.py applied first.

    python3 tools/edit_es_v2_runtime.py [--apply] [system3_runtime.py]
"""
import os
import sys
import tempfile
from pathlib import Path

MARKER = "[es-v2]"

EDITS = [
    ("es-v2-method",
     '    ES_TEXT_MARK = "ES_TEXT"           # [s3-es-dir] in defaults_added: the directions were given once\n',
     '    ES_V2_MARK = "ES_V2"               # [es-v2] in defaults_added: ES1\'s second edition was taken once\n'
     '\n'
     '    @staticmethod\n'
     '    def es_v2_changes(config):\n'
     '        """[es-v2] (new config, moved, kept): `config` with every ES row that still\n'
     '        holds its v1 default moved to system3_tables.ES1_V2 - the voice of a\n'
     '        category or item, the direction of an item. `kept` lists the rows the\n'
     '        operator made their own (edited, cleared or removed), left as they are."""\n'
     '        v1, v2 = system3_tables.ES1, system3_tables.ES1_V2\n'
     '        clean = system3.clean_es_voice\n'
     '        v1_cat = {c["id"]: c.get("voice") for c in v1["categories"]}\n'
     '        v2_cat = {c["id"]: c.get("voice") for c in v2["categories"]}\n'
     '        v1_item = {i["id"]: i for c in v1["categories"] for i in c["items"]}\n'
     '        v2_item = {i["id"]: i for c in v2["categories"] for i in c["items"]}\n'
     '        new = copy.deepcopy(config if isinstance(config, dict) else {})\n'
     '        moved, kept = [], []\n'
     '\n'
     '        def voice(row, was, now, where):\n'
     '            if was is None:                                  # v1 had none: absent is the default\n'
     '                if "voice" not in row and now is not None:\n'
     '                    row["voice"] = copy.deepcopy(now)\n'
     '                    moved.append(where + " voice")\n'
     '                elif "voice" in row and clean(row["voice"]) != clean(now):\n'
     '                    kept.append(where + " voice")\n'
     '                return\n'
     '            if "voice" not in row or clean(row["voice"]) != clean(was):\n'
     '                if clean(row.get("voice")) != clean(now):\n'
     '                    kept.append(where + " voice")\n'
     '                return\n'
     '            if clean(now) != clean(was):\n'
     '                row["voice"] = copy.deepcopy(now)\n'
     '                moved.append(where + " voice")\n'
     '\n'
     '        for t in new.get("tables") or []:\n'
     '            if not isinstance(t, dict) or t.get("family") != "ES":\n'
     '                continue\n'
     '            for c in t.get("categories") or []:\n'
     '                if not isinstance(c, dict):\n'
     '                    continue\n'
     '                cid = str(c.get("id") or "")\n'
     '                if cid in v1_cat:\n'
     '                    voice(c, v1_cat[cid], v2_cat[cid], "%s:%s" % (t.get("id"), cid))\n'
     '                for it in c.get("items") or []:\n'
     '                    iid = str((it or {}).get("id") or "") if isinstance(it, dict) else ""\n'
     '                    if iid not in v1_item:\n'
     '                        continue\n'
     '                    where = "%s:%s" % (t.get("id"), iid)\n'
     '                    voice(it, v1_item[iid].get("voice"), v2_item[iid].get("voice"), where)\n'
     '                    if it.get("text") == v1_item[iid].get("text"):\n'
     '                        if v2_item[iid].get("text") != it.get("text"):\n'
     '                            it["text"] = v2_item[iid]["text"]\n'
     '                            moved.append(where + " direction")\n'
     '                    elif it.get("text") != v2_item[iid].get("text"):\n'
     '                        kept.append(where + " direction")\n'
     '        return new, moved, kept\n'
     '\n'
     '    def upgrade_es_v2(self, apply=True):\n'
     '        """[es-v2] ES1\'s second edition onto the stored config, once (ES_V2_MARK).\n'
     '        apply=False only reports. Returns {moved, kept, done, hash}."""\n'
     '        config = self.config if isinstance(self.config, dict) else {}\n'
     '        seen = {str(x) for x in (config.get("defaults_added") or [])}\n'
     '        new, moved, kept = self.es_v2_changes(config)\n'
     '        out = {"moved": moved, "kept": kept, "done": self.ES_V2_MARK in seen,\n'
     '               "hash": system3.config_hash(config)}\n'
     '        if not apply or out["done"]:\n'
     '            return out\n'
     '        new["defaults_added"] = sorted(seen | {self.ES_V2_MARK})\n'
     '        try:\n'
     '            out["hash"] = self.store.save_config(\n'
     '                new, "ES1 second edition (es-v2): %d rows moved to the recalibrated voices and actor "\n'
     '                     "directions, %d kept as the operator left them" % (len(moved), len(kept)))\n'
     '        except Exception as exc:  # noqa: BLE001\n'
     '            self.fail("ES v2", exc)\n'
     '            return dict(out, error=str(exc))\n'
     '        self.config = new\n'
     '        out["done"] = True\n'
     '        self.log("System 3\'s ES tables took their second edition (es-v2): %d moved, %d kept"\n'
     '                 % (len(moved), len(kept)))\n'
     '        return out\n'
     '\n'
     '    ES_TEXT_MARK = "ES_TEXT"           # [s3-es-dir] in defaults_added: the directions were given once\n', 1),
    ("es-v2-route",
     '    @app.post("/api/system3/config/reset")\n'
     '    async def reset_config(authorization: str | None = Header(default=None)):\n'
     '        host.require_auth(authorization)\n'
     '        return {"hash": await save_config(system3.default_config(), "reset to defaults")}\n',
     '    @app.post("/api/system3/config/reset")\n'
     '    async def reset_config(authorization: str | None = Header(default=None)):\n'
     '        host.require_auth(authorization)\n'
     '        return {"hash": await save_config(system3.default_config(), "reset to defaults")}\n'
     '\n'
     '    @app.post("/api/system3/es-v2")\n'
     '    async def es_v2(dry: int = 0, authorization: str | None = Header(default=None)):\n'
     '        """[es-v2] ES1\'s second edition, once: ?dry=1 lists what would move and\n'
     '        what stays as the operator left it; without it, it is done."""\n'
     '        host.require_auth(authorization)\n'
     '        return await asyncio.get_running_loop().run_in_executor(_STORE_POOL, rt.upgrade_es_v2, not dry)\n', 1),
]


def main(argv):
    do_apply = "--apply" in argv
    target = Path(next((a for a in argv if not a.startswith("--")), "system3_runtime.py"))
    text = target.read_bytes().decode("utf-8")
    if "\r" in text:
        print("system3_runtime.py is expected LF-only")
        return 1
    if MARKER in text:
        print("already applied")
        return 2
    missing = [name for name, old, _new, count in EDITS if text.count(old) != count]
    if missing:
        print("missing: " + ", ".join(missing))
        return 1
    if not do_apply:
        print("ready")
        return 0
    for _name, old, new, _count in EDITS:
        text = text.replace(old, new)
    fd, tmp = tempfile.mkstemp(prefix=target.name + ".", dir=str(target.parent))
    with os.fdopen(fd, "wb") as fh:
        fh.write(text.encode("utf-8"))
    os.replace(tmp, target)
    print("APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
