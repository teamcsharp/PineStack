"""Resting the SFX Guy's topic lines is ONE save, off the event loop.

tools/rng_topics_patch.py's _sfxguy_topics_rest suspended each board line
with its own SfxSpeechBank.put(), and put() rewrites the whole ledger
(1.5-2 MB of JSON) every time - on the event loop, from sfxguy_ready_prepare.
Measured on the first run after the 08:51Z restart: one 14.31 s stall, past
the host watchdog's 8 s probe (/api/pulse: "mostly _sfxguy_topics_rest").

Now: SfxSpeechBank.restate(pick, update) changes every matching row in ONE
replaced ledger and ONE save, under the bank's own lock, and the caller runs
it in a worker thread (asyncio.to_thread), so neither resting the lines nor
putting them back (`topics:auto`) can hold the loop.

Idempotent: --check exits 0 when every edit can apply, 2 when already
applied, 1 when an anchor is missing; --apply writes the files. ON THE HOST.
"""
import sys
from pathlib import Path

EDITS = [
    ("sfx_speech_bank.py",
     "    def protected_files(self):\n",
     "    def restate(self, pick, update):\n"
     "        \"\"\"[rng-topics] Change every row `pick(row)` accepts with `update(row)`\n"
     "        in ONE replaced ledger and ONE save - put() saves the whole ledger per\n"
     "        row, which is 1.5-2 MB of JSON each time. Reservation and play fields\n"
     "        are left as they are. Returns how many rows changed.\"\"\"\n"
     "        with self.lock:\n"
     "            rows = dict(self._load())\n"
     "            changed = 0\n"
     "            for key, row in rows.items():\n"
     "                if not pick(row):\n"
     "                    continue\n"
     "                fresh = dict(row)\n"
     "                update(fresh)\n"
     "                for held in (\"reservation\", \"reserved_until\", \"last_played\", \"plays\",\n"
     "                             \"voice\", \"profile\", \"text_plain\", \"who\"):\n"
     "                    if held in row:\n"
     "                        fresh[held] = row[held]\n"
     "                rows[key] = fresh\n"
     "                changed += 1\n"
     "            if changed:\n"
     "                self._save(rows)\n"
     "            return changed\n"
     "\n"
     "    def protected_files(self):\n"),
    ("app.py",
     "        moved = 0\n"
     "        for row in _SFX_READY_BANK.rows(voice, profile, deep=False):\n"
     "            if rest:\n"
     "                text = \" \".join(str(row.get(\"text_plain\") or \"\").split())\n"
     "                if text not in board or row.get(\"state\") == \"suspended\":\n"
     "                    continue\n"
     "                row.update(state=\"suspended\", why=SFXGUY_TOPIC_REST_WHY,\n"
     "                           rested_from=str(row.get(\"state\") or \"\"))\n"
     "            else:\n"
     "                if row.get(\"why\") != SFXGUY_TOPIC_REST_WHY:\n"
     "                    continue\n"
     "                row.update(state=str(row.pop(\"rested_from\", \"\") or \"waiting\"), why=\"\")\n"
     "            _SFX_READY_BANK.put(row)\n"
     "            moved += 1\n",
     "        # [rng-topics] ONE save for all of them (SfxSpeechBank.restate): put()\n"
     "        # rewrites the whole ledger per row, and that was a 14 s stall.\n"
     "        mine = lambda row: row.get(\"voice\") == voice and row.get(\"profile\") == profile\n"
     "        if rest:\n"
     "            def _rest(row):\n"
     "                row.update(state=\"suspended\", why=SFXGUY_TOPIC_REST_WHY,\n"
     "                           rested_from=str(row.get(\"state\") or \"\"))\n"
     "            moved = _SFX_READY_BANK.restate(\n"
     "                lambda row: (mine(row) and row.get(\"state\") != \"suspended\"\n"
     "                             and \" \".join(str(row.get(\"text_plain\") or \"\").split()) in board),\n"
     "                _rest)\n"
     "        else:\n"
     "            def _back(row):\n"
     "                row.update(state=str(row.pop(\"rested_from\", \"\") or \"waiting\"), why=\"\")\n"
     "            moved = _SFX_READY_BANK.restate(\n"
     "                lambda row: mine(row) and row.get(\"why\") == SFXGUY_TOPIC_REST_WHY, _back)\n"),
    ("app.py",
     "            _sfxguy_topics_rest(voice, profile, rest=False)\n",
     "            await asyncio.to_thread(_sfxguy_topics_rest, voice, profile, False)   # off the loop\n"),
    ("app.py",
     "            _sfxguy_topics_rest(voice, profile, rest=True)\n",
     "            await asyncio.to_thread(_sfxguy_topics_rest, voice, profile, True)    # off the loop\n"),
]


def main(argv):
    apply = "--apply" in argv
    texts, todo = {}, 0
    for name, old, new in EDITS:
        text = texts.get(name)
        if text is None:
            text = texts[name] = Path(name).read_text(encoding="utf-8").replace("\r\n", "\n")
        if new in text:
            continue
        if text.count(old) != 1:
            print("MISSING (%d) in %s: %r" % (text.count(old), name, old[:80]))
            return 1
        texts[name] = text.replace(old, new)
        todo += 1
    if not todo:
        print("already applied")
        return 2
    if not apply:
        print("can apply: %d edit(s)" % todo)
        return 0
    for name, text in texts.items():
        Path(name).write_text(text, encoding="utf-8", newline="\n")
    print("applied: %d edit(s)" % todo)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
