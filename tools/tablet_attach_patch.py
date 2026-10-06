#!/usr/bin/env python3
"""[tablet-attach] The desk says WHY the tablet is not attached, and clears a dead link. 2026-10-05, #1589.

"The tablet is definitely online. Check and see why the application is unable
to correspond with and connect to the tablet."

What was found on 10-05. The tablet was online and healthy (awake, good Wi-Fi,
adb answering in about a second). The desk decides "attached" with its own adb
on this computer (terminal-host.cjs, glassSerial): it looks for the remembered
address in `adb devices`, and if it is not ready it tries one `adb connect`
with six seconds to answer. Every way that could fail ended in the same empty
answer, shown as "no tablet is attached" - with no reason. adb's own log for
the day shows the link to the tablet dropped three times.

Two changes, both in the place that owns the decision:

  the reason   glassSerial keeps why it came back empty, in adb's own words,
               and the two places that print the verdict print that instead.
  the trap     a network tablet whose link has died stays in adb's list as
               "offline"; `adb connect` answers "already connected" to it and
               changes nothing. The dead entry is dropped before reconnecting,
               and the connect gets twelve seconds instead of six.

Both files are the desktop's main process: they take effect at its next launch.

Usage:  tablet_attach_patch.py --check [ROOT]   0 ready, 2 already applied, 1 anchors missing
        tablet_attach_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HOST_OLD = r'''    const tools = this.tools();
    try {
      const list = parseDevices(await runner(tools.adb, 20000)(['devices', '-l'])) || [];
      const saved = String((this.readConfig() || {}).tabletSerial || '');
      const ready = list.find((entry) => entry.authorized && entry.serial === saved);
      if (ready) return ready.serial;
      /* Once a tablet has been selected, losing the local ADB transport
       * must not make the mirror impossible to open again. */
      if (/^[^\s:]+:\d+$/.test(saved)) {
        try {
          await runner(tools.adb, 6000)(['connect', saved]);
          const again = parseDevices(await runner(tools.adb, 6000)(['devices', '-l'])) || [];
          if (again.some((entry) => entry.authorized && entry.serial === saved)) return saved;
        } catch (error) { /* let the caller consult the station's current address */ }
        return '';
      }
      const other = list.find((entry) => entry.authorized);
      return other ? other.serial : '';
    } catch (error) {
      return '';
'''
HOST_NEW = r'''    const tools = this.tools();
    /* [tablet-attach] WHY NOT, IN ADB'S OWN WORDS.
     *
     * "The tablet is definitely online. Check and see why the application
     *  is unable to correspond with and connect to the tablet."
     *
     * Every way this could fail ended in the same empty answer, and the desk
     * printed "no tablet is attached" for all of them: a tablet that was
     * never chosen, one that refused the connection, one adb still listed
     * but could no longer talk to, a missing adb. glassWhy keeps the reason
     * for whoever shows the verdict.
     *
     * One of those was a trap. A network tablet whose link has died stays in
     * adb's list as "offline", and `adb connect` answers "already connected"
     * to it and changes nothing - so the desk could say "not attached" for
     * as long as adb kept the dead entry. The dead entry is dropped first. */
    this.glassWhy = '';
    const words = (text) => String(text || '').trim().split(/\r?\n/).filter(Boolean).pop() || '';
    const failed = (error) => (error && error.killed ? 'no answer in time' : words(error && error.message) || 'no answer').slice(0, 140);
    try {
      const list = parseDevices(await runner(tools.adb, 20000)(['devices', '-l'])) || [];
      const saved = String((this.readConfig() || {}).tabletSerial || '');
      const ready = list.find((entry) => entry.authorized && entry.serial === saved);
      if (ready) return ready.serial;
      /* Once a tablet has been selected, losing the local ADB transport
       * must not make the mirror impossible to open again. */
      if (/^[^\s:]+:\d+$/.test(saved)) {
        try {
          const listed = list.find((entry) => entry.serial === saved);
          if (listed && listed.state !== 'unauthorized') await runner(tools.adb, 6000)(['disconnect', saved]).catch(() => '');
          const said = await runner(tools.adb, 12000)(['connect', saved]);
          const again = parseDevices(await runner(tools.adb, 6000)(['devices', '-l'])) || [];
          if (again.some((entry) => entry.authorized && entry.serial === saved)) return saved;
          const now = again.find((entry) => entry.serial === saved);
          this.glassWhy = now && now.state === 'unauthorized'
            ? 'the tablet at ' + saved + ' has not allowed this computer yet - accept the debugging prompt on its screen'
            : 'the tablet at ' + saved + ' did not take the connection (' + (words(said) || 'adb said nothing').slice(0, 140) + ')';
        } catch (error) {
          /* let the caller consult the station's current address */
          this.glassWhy = 'adb could not reach the tablet at ' + saved + ' (' + failed(error) + ')';
        }
        return '';
      }
      const other = list.find((entry) => entry.authorized);
      if (!other && list.length) this.glassWhy = 'adb lists ' + list[0].serial + ' as ' + list[0].state + ', which is not ready';
      return other ? other.serial : '';
    } catch (error) {
      this.glassWhy = tools.found === false
        ? 'adb was not found on this computer - set the platform-tools folder'
        : 'adb did not answer (' + failed(error) + ')';
      return '';
'''

VITALS_OLD = r'''      vitalsHeld = null;
      return { ok: false, why: "no tablet is attached" };
'''
VITALS_NEW = r'''      vitalsHeld = null;
      return { ok: false, why: terminalHost.glassWhy || "no tablet is attached" };   /* [tablet-attach] the reason, when there is one */
'''
POKE_OLD = r'''      if (!serial) return { ok: false, why: "no tablet is attached" };
      if (!lease.isCurrent()) return { ok: false, cancelled: true, why: "the mirror was closed" };
      poke = new TabletInput({ adb: tools.adb, serial });
'''
POKE_NEW = r'''      if (!serial) return { ok: false, why: terminalHost.glassWhy || "no tablet is attached" };   /* [tablet-attach] */
      if (!lease.isCurrent()) return { ok: false, cancelled: true, why: "the mirror was closed" };
      poke = new TabletInput({ adb: tools.adb, serial });
'''

EDITS = {
    "desktop/terminal-host.cjs": [
        ("the attach check keeps its reason", HOST_OLD, HOST_NEW, "    this.glassWhy = '';\n", 1),
    ],
    "desktop/main.js": [
        ("the tablet row prints the reason", VITALS_OLD, VITALS_NEW, "/* [tablet-attach] the reason, when there is one */", 1),
        ("the mirror's touch prints it too", POKE_OLD, POKE_NEW, 'why: terminalHost.glassWhy || "no tablet is attached" };   /* [tablet-attach] */', 1),
    ],
}


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    ready = missing = False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        raw = path.read_bytes()
        text = raw.decode("utf-8")      # endings are left exactly as they are: this file mixes them
        changed = False
        for label, old, new, probe, count in edits:
            forms = [(old, new, probe), (old.replace("\n", "\r\n"), new.replace("\n", "\r\n"), probe.replace("\n", "\r\n"))]
            state = ""
            for old_, new_, probe_ in forms:
                have = text.count(probe_)
                if have == count:
                    state = "applied"
                    break
                if not have and text.count(old_) == count:
                    text = text.replace(old_, new_)
                    assert text.count(probe_) == count, (name, label, "probe after the edit")
                    state, changed = "ready", True
                    break
            if not state:
                state = "missing (anchor found %d, probe %d)" % (text.count(old), text.count(probe))
            print("%-28s %-36s %s" % (name, label, state))
            if state == "ready":
                ready = True
            elif state != "applied":
                missing = True
        plans.append((path, text, changed))
    if missing:
        print("ANCHORS MISSING - nothing written")
        return 1
    if not ready:
        print("already applied")
        return 2
    if argv[1] == "--check":
        print("ready")
        return 0
    for path, text, changed in plans:
        if changed:
            tmp = path.with_name(path.name + ".attach.tmp")
            tmp.write_bytes(text.encode("utf-8"))
            os.replace(tmp, path)
            print("wrote %s" % path)
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
