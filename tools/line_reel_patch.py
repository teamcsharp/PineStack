"""The document a speaker-box passage came from, in the lines it was cut from.

Operator, 2026-09-27, on the decision card: "After showing the roll of the
speaker box, show another line of the sentences rolling through the
document. Show the document that it comes up with, and then show the line
scrolling in that document, scrolling like a roll to the result."

A passage is a swath of the lines the station HARVESTED from a document
(speakbox_gems - or speakbox_lines(speakbox_body()) when no harvest is
kept), not of the file's own lines: a transcript's line is a paragraph of
a thousand characters and a passage is two sentences out of it, sometimes
across a paragraph break. System 3's "passage 18/43" counted file lines
and matched the first 40 characters of the passage inside one, so a
passage that began across a break was never found - two of the four
recorded in the harness read {"index": None}.

Two edits:
  app.py              GET /api/speakbox/{name}?lines=1 returns the document
                      as those lines: {"lines", "source": "harvest"|"sentences"}
  system3_runtime.py  _passage_position counts in the same lines, exact
                      line first, so the number is the line the reel lands
                      on. A host without the harvest functions (the tests'
                      stand-in station) keeps the file's own lines.

Idempotent: --check exits 0 when every edit can apply, 2 when already
applied, 1 when an anchor is missing; --apply writes the files. Run it ON
THE HOST:

    cat tools/line_reel_patch.py | ssh HOST 'cd ~/pinevoice-stack/spark-agent && python3 - --apply'
"""
import sys
from pathlib import Path

EDITS = [
    ("app.py",
     "    name: str,\n"
     "    mind: str = \"\",\n"
     "    preview: int = 0,\n"
     "    authorization: str | None = Header(default=None),\n"
     ") -> dict[str, Any]:\n"
     "    \"\"\"One document, as it stands on disk.\n",
     "    name: str,\n"
     "    mind: str = \"\",\n"
     "    preview: int = 0,\n"
     "    lines: int = 0,\n"
     "    authorization: str | None = Header(default=None),\n"
     ") -> dict[str, Any]:\n"
     "    \"\"\"One document, as it stands on disk.\n"),
    ("app.py",
     "        raise HTTPException(status_code=404, detail=f\"No {name} in the speakbox\")\n"
     "    if preview > 0:\n",
     "        raise HTTPException(status_code=404, detail=f\"No {name} in the speakbox\")\n"
     "    if lines:\n"
     "        # [line-reel] THE DOCUMENT AS THE DRAW SEES IT: the lines the\n"
     "        # station harvested from it - what speakbox_quote cuts a swath\n"
     "        # from - or its sentences when no harvest is kept. The Messenger's\n"
     "        # line reel rolls through these and lands on the passage. In a\n"
     "        # thread: the gem cache is one JSON file per mind.\n"
     "        def _said_lines() -> dict[str, Any]:\n"
     "            gems = speakbox_gems(path, used)\n"
     "            if gems:\n"
     "                return {\"lines\": gems, \"source\": \"harvest\"}\n"
     "            return {\"lines\": speakbox_lines(speakbox_body(path)), \"source\": \"sentences\"}\n"
     "        return {\"name\": name, \"mind\": used, **(await asyncio.to_thread(_said_lines))}\n"
     "    if preview > 0:\n"),
    ("system3_runtime.py",
     "    async def _passage_position(self, material):\n"
     "        \"\"\"\"passage 18/43\": where in its document the drawn passage sits.\"\"\"\n"
     "        def work():\n"
     "            try:\n"
     "                files = [p for p in self.host.speakbox_all(material.get(\"mind\", \"\")) if p.name == material[\"file\"]]\n"
     "                if not files:\n"
     "                    return None\n"
     "                text = files[0].read_text(errors=\"replace\")\n"
     "                lines = [ln.strip() for ln in text.splitlines() if ln.strip()]\n"
     "                first = (material.get(\"lines\") or [material[\"text\"]])[0][:60].strip()\n"
     "                for i, ln in enumerate(lines):\n"
     "                    if first and first[:40] in ln:\n"
     "                        return {\"index\": i + 1, \"of\": len(lines)}\n"
     "                return {\"index\": None, \"of\": len(lines)}\n",
     "    async def _passage_position(self, material):\n"
     "        \"\"\"\"passage 18/43\": where in its document the drawn passage sits -\n"
     "        counted in the lines the draw was cut from (the station's harvest\n"
     "        of the document, or its sentences when none is kept; GET\n"
     "        /api/speakbox/{name}?lines=1 serves the same list), so the number\n"
     "        is the line the Messenger's line reel lands on. [line-reel]\"\"\"\n"
     "        def work():\n"
     "            try:\n"
     "                mind = material.get(\"mind\", \"\")\n"
     "                files = [p for p in self.host.speakbox_all(mind) if p.name == material[\"file\"]]\n"
     "                if not files:\n"
     "                    return None\n"
     "                gems = getattr(self.host, \"speakbox_gems\", None)\n"
     "                split = getattr(self.host, \"speakbox_lines\", None)\n"
     "                body = getattr(self.host, \"speakbox_body\", None)\n"
     "                lines = list(gems(files[0], mind) or []) if gems else []\n"
     "                if not lines and split and body:\n"
     "                    lines = list(split(body(files[0])) or [])\n"
     "                if not lines:\n"
     "                    text = files[0].read_text(errors=\"replace\")\n"
     "                    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]\n"
     "                first = str((material.get(\"lines\") or [material[\"text\"]])[0]).strip()\n"
     "                for i, ln in enumerate(lines):\n"
     "                    if first and str(ln).strip() == first:\n"
     "                        return {\"index\": i + 1, \"of\": len(lines)}\n"
     "                probe = first[:60].strip()[:40]\n"
     "                for i, ln in enumerate(lines):\n"
     "                    if probe and probe in str(ln):\n"
     "                        return {\"index\": i + 1, \"of\": len(lines)}\n"
     "                return {\"index\": None, \"of\": len(lines)}\n"),
]


def main(argv):
    apply = "--apply" in argv
    texts, state = {}, []
    for name, old, new in EDITS:
        path = Path(name)
        text = texts.get(name)
        if text is None:
            text = texts[name] = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        if new in text:
            state.append("done")
            continue
        count = text.count(old)
        if count != 1:
            print("MISSING (%d) in %s: %r" % (count, name, old[:80]))
            return 1
        texts[name] = text.replace(old, new)
        state.append("todo")
    if all(s == "done" for s in state):
        print("already applied")
        return 2
    if not apply:
        print("can apply: %d edit(s)" % state.count("todo"))
        return 0
    for name, text in texts.items():
        Path(name).write_text(text, encoding="utf-8", newline="\n")
    print("applied: %d edit(s)" % state.count("todo"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
