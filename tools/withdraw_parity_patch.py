"""System2's own hand-over test answers the operator's withdraw switch.

tools/cut_switches_patch.py put `withdraw:on|off` (orch_policy
"overrun_withdraw") on app.py's hand-over test, _scheduled_first_handoff_fits.
A System2 round is handed over through a second test of its own - the
store's measured-length check, run inside System2Runtime's validate() with
the air road's grace - and that one still refused what the switch had just
let through: 56 lines in the 24 h before the switch, "the hand-off was
refused: the caller round runs N s, its entry has N s left and N s of
grace, so it overruns".

With the switch off, _grace() hands the store an allowance of an hour -
"a finished round airs even when it runs past its entry; the sheet waits
for it" - and the delivery waits that long for its hand-over instead of
abandoning it at the entry's deadline. With the switch on (or unset)
nothing changes. The store's ceiling on a caller's grace rises from 300 s
to that hour so the allowance can be expressed; every caller that passes
its own grace is unchanged.

Idempotent: --check exits 0 when every edit can apply, 2 when already
applied, 1 when an anchor is missing; --apply writes the files. Run it ON
THE HOST:

    cat tools/withdraw_parity_patch.py | ssh HOST 'cd ~/pinevoice-stack/spark-agent && python3 - --apply'
"""
import sys
from pathlib import Path

EDITS = [
    ("system2.py",
     "        allowance = 0.0 if not grace else _number(grace, 'grace seconds', 0.0, 300.0)   # [#1191]\n",
     "        # [withdraw-parity] up to an hour: with the operator's withdraw\n"
     "        # switch off the caller's allowance is \"the sheet waits for it\".\n"
     "        allowance = 0.0 if not grace else _number(grace, 'grace seconds', 0.0, 3600.0)   # [#1191]\n"),
    ("system2_runtime.py",
     "                def _grace():\n"
     "                    # [#1191] THE AIR ROAD'S OWN ALLOWANCE, handed to the\n",
     "                def _grace():\n"
     "                    # [withdraw-parity] THE OPERATOR'S WITHDRAW SWITCH.\n"
     "                    # Off (orch_policy \"overrun_withdraw\"), app.py's own\n"
     "                    # hand-over test lets a finished round run past its\n"
     "                    # entry and the sheet waits for it; this road gives\n"
     "                    # the same answer, or it refuses what that road has\n"
     "                    # just let through.\n"
     "                    try:\n"
     "                        if h.orch_policy(\"overrun_withdraw\", True) is False:\n"
     "                            return OVERRUN_UNBOUNDED\n"
     "                    except Exception:  # noqa: BLE001\n"
     "                        pass\n"
     "                    # [#1191] THE AIR ROAD'S OWN ALLOWANCE, handed to the\n"),
    ("system2_runtime.py",
     "                    deadline = float(entry[\"_ready_slot\"][\"deadline\"])\n"
     "                    done, _ = await asyncio.wait({delivery}, timeout=max(0.0, deadline - time.time()))\n",
     "                    deadline = float(entry[\"_ready_slot\"][\"deadline\"])\n"
     "                    # [withdraw-parity] with the withdraw switch off the\n"
     "                    # hand-over may come after the entry has ended.\n"
     "                    if _grace() >= OVERRUN_UNBOUNDED:\n"
     "                        deadline += OVERRUN_UNBOUNDED\n"
     "                    done, _ = await asyncio.wait({delivery}, timeout=max(0.0, deadline - time.time()))\n"),
    ("system2_runtime.py",
     "class System2Runtime",
     "# [withdraw-parity] the allowance a round is given past its entry when\n"
     "# the operator has turned the withdraw switch off: an hour, which the\n"
     "# store accepts as a caller's grace (system2.py _validate).\n"
     "OVERRUN_UNBOUNDED = 3600.0\n"
     "\n"
     "\n"
     "class System2Runtime"),
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
