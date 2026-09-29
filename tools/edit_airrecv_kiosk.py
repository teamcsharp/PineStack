#!/usr/bin/env python3
"""[airplayers] the tablet's native drawer: Playing it becomes the receivers
switch, and every button answers the thumb before the station does.

TARGET (kiosk project root, e.g. C:/_tools/pinebox-android/PineBoxKiosk, or the
mainline repo root - both carry app/src/main/...):
  app/src/main/java/com/pinebox/kiosk/rail/RailController.kt  (edits)
  app/src/main/res/values/strings.xml                         (edits)
  app/src/main/java/com/pinebox/kiosk/rail/AirReceivers.kt     (new)
  app/src/main/res/layout/rail_player.xml                      (replaced)
  app/src/main/res/drawable/player_row.xml                     (new)
  app/src/main/res/drawable/player_badge.xml                   (new)
  app/src/test/java/com/pinebox/kiosk/AirReceiversTest.kt      (new)
usage: edit_airrecv_kiosk.py --check|--apply <root>
"""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from patchlib_air import run  # noqa: E402

RC = "app/src/main/java/com/pinebox/kiosk/rail/RailController.kt"

FIELDS_ANCHOR = '''    private var roster = AirOwners.Roster()
'''
FIELDS = '''
    /* [airplayers:fields] the receivers switch, when the station has it
     * (GET/POST /api/air/receivers); null on a station that predates it,
     * and the old roster rows are drawn instead. */
    private var receivers: AirReceivers.State? = null

    /** Receiver ids with a write in flight: no read may repaint them. */
    private val receiversPending = mutableSetOf<String>()

    /** A refusal or a failure, said on the row it belongs to. */
    private var receiversFault: Pair<String, String>? = null

    /** The BROADCAST chip tapped and not yet confirmed by the station. */
    private var destinationPending = ""
'''

READ_ANCHOR = '''    private fun readPlayers() {
'''
READ = '''        /* [airplayers:read] the receivers switch first; the old roster
         * only for a station that does not have it yet. */
        scope.launch {
            val got = try {
                AirReceivers.read(JSONObject(client.get(AirReceivers.ROUTE)))
            } catch (err: Exception) {
                null
            }
            if (got != null) adoptReceivers(got, fromWrite = false) else readRoster()
        }
    }

    private fun readRoster() {
'''

RECONCILE_ANCHOR = '''    private fun reconcileAir(settings: JSONObject?) {
'''
RECONCILE = '''        /* [airplayers:reconcile] the station resolves the air itself now
         * that several receivers may be on; a tablet re-pointing the
         * exclusive at the table's one device would undo the operator. */
        if (receivers != null) return
'''

PAINT_PLAYERS_ANCHOR = '''    private fun paintPlayers() {
'''
PAINT_PLAYERS = '''        if (receivers != null) {           // [airplayers:paint]
            paintReceivers()
            return
        }
'''

ROWS_ANCHOR = '''    /** The names from the roster we already have, so a repaint after a solo
'''
ROWS = '''    /* ---- [airplayers:rows] Playing it: the receivers switch ----------------
     *
     * "i want the buttons to redirect audio to be responsive. i want to be
     * able to enable and disable streams from there as well by enabling them
     * from receiving a broadcast."
     *
     * The old rows felt dead for four measured reasons: the row holding the
     * air was never drawn differently (chip.xml has no selected state); a
     * REFUSED hand-over (/api/radio/solo answers 200 with `refused`) was
     * painted as a success and the tick bounced back; what a tap did was
     * written in the BROADCAST card, not here; and the list was read only
     * when the drawer opened. Now: the row is pressed on touch, switched
     * and marked "switching..." in the same frame as the tap, repainted from
     * the station's answer, and a refusal or failure is said ON THE ROW. */

    private fun adoptReceivers(next: AirReceivers.State, fromWrite: Boolean) {
        val was = receivers
        receivers = if (fromWrite || was == null || receiversPending.isEmpty()) next
        else next.copy(receivers = next.receivers.map { r ->
            if (r.id in receiversPending) was.of(r.id) ?: r else r
        })
        paintReceivers()
    }

    private fun paintReceivers() {
        val st = receivers ?: return
        val inflater = android.view.LayoutInflater.from(rail.context)
        /* ROWS ARE UPDATED IN PLACE when the list is the same receivers in
         * the same order - which is every paint but the first. Rebuilding
         * detached the row under a finger that was already down (the drawer
         * open fires a read, and the old code a solo answer, ~100-300 ms
         * apart), so the release landed on a new view and the tap was lost.
         * Measured the same way in the web harness: one tap in a few. */
        val same = playerList.childCount == st.receivers.size &&
            st.receivers.indices.all { playerList.getChildAt(it).tag == st.receivers[it].id }
        if (!same) playerList.removeAllViews()
        val fault = receiversFault
        for ((index, r) in st.receivers.withIndex()) {
            val row = if (same) playerList.getChildAt(index)
            else inflater.inflate(R.layout.rail_player, playerList, false)
            row.tag = r.id
            val pending = r.id in receiversPending
            row.findViewById<View>(R.id.playerTick).visibility = View.GONE
            val sw = row.findViewById<SwitchCompat>(R.id.playerSwitch)
            sw.visibility = View.VISIBLE
            sw.isChecked = r.audible
            row.findViewById<TextView>(R.id.playerName).text = r.label
            row.findViewById<View>(R.id.playerBadge).visibility =
                if (r.active) View.VISIBLE else View.GONE
            val err = if (fault != null && fault.first == r.id) fault.second else ""
            val detail = row.findViewById<TextView>(R.id.playerDetail)
            detail.text = listOf(AirReceivers.detail(r, pending), err)
                .filter { it.isNotBlank() }.joinToString(NEWLINE)
            detail.setTextColor(rail.resources.getColor(when {
                err.isNotBlank() -> R.color.pine_bad
                pending -> R.color.pine_amber
                else -> R.color.pine_dim
            }, null))
            row.isSelected = r.active
            row.alpha = if (r.kind == "page" && !r.present) 0.62f else 1f
            row.contentDescription = r.label + if (r.audible)
                " is audible - tap to switch it off" else " is off - tap to let it sound"
            row.setOnClickListener { flipReceiver(r) }
            val only = row.findViewById<Button>(R.id.playerOnly)
            only.visibility = View.VISIBLE
            only.contentDescription = "Make " + r.label + " the only one sounding in the house"
            only.tooltipText = only.contentDescription
            only.setOnClickListener { onlyReceiver(r) }
            if (!same) playerList.addView(row)
        }
        playerNote.text = fault?.second ?: AirReceivers.note(st)
        playerNote.setTextColor(rail.resources.getColor(
            if (fault != null || st.refused.isNotBlank()) R.color.pine_bad else R.color.pine_dim,
            null,
        ))
    }

    private fun flipReceiver(r: AirReceivers.Receiver) {
        if (r.id in receiversPending) return
        val want = !r.audible
        writeReceivers(setOf(r.id), AirReceivers.flip(r.id, want),
            "switching " + r.label + if (want) " on" else " off") {
            AirReceivers.optimistic(it, r.id, want)
        }
    }

    private fun onlyReceiver(r: AirReceivers.Receiver) {
        val st = receivers ?: return
        if (receiversPending.isNotEmpty()) return
        writeReceivers(AirReceivers.touched(st, r.id, true), AirReceivers.only(r.id),
            "only " + r.label) { AirReceivers.optimisticOnly(it, r.id) }
    }

    /** One write: painted before the network, repainted from the answer. */
    private fun writeReceivers(
        ids: Set<String>, body: String, saying: String,
        guess: (AirReceivers.State) -> AirReceivers.State,
    ) {
        val was = receivers ?: return
        receiversFault = null
        receiversPending.addAll(ids)
        receivers = guess(was)
        paintReceivers()
        playerNote.text = saying + "…"
        val t0 = android.os.SystemClock.uptimeMillis()
        scope.launch {
            try {
                val answer = AirReceivers.read(JSONObject(client.post(AirReceivers.ROUTE, body)))
                    ?: throw IllegalStateException("the station gave no answer")
                receiversPending.removeAll(ids)
                if (answer.refused.isNotBlank()) {
                    receiversFault = ids.first() to AirReceivers.note(answer)
                }
                adoptReceivers(answer, fromWrite = true)
                Log.i(TAG, "playing it: " + saying + " confirmed in "
                    + (android.os.SystemClock.uptimeMillis() - t0) + " ms: "
                    + AirReceivers.summary(answer))
            } catch (err: Exception) {
                receiversPending.removeAll(ids)
                receivers = was
                receiversFault = ids.first() to ("not changed - could not reach the station: "
                    + (err.message ?: err.javaClass.simpleName))
                paintReceivers()
                Log.w(TAG, "playing it: $saying failed", err)
            }
        }
    }

'''

CHIP_FIRST_ANCHOR = '''        val preset = DjOutput.PRESETS[key] ?: return
'''
CHIP_FIRST = '''        /* [airplayers:chip] ANSWER THE THUMB FIRST. This used to light
         * nothing and say nothing until six round trips had finished (two
         * reads, the solo, the routes, a 21 KB settings PUT and another
         * read) - and a feed paint in between repainted the old chip. The
         * chip lights now and the line says "sending"; the station's answer
         * (or its refusal, in words) replaces both. */
        destinationPending = key
        for ((k, chip) in presetChips) chip.isActivated = k == key
        paintNote()
'''

CHIP_OK_ANCHOR = '''                destination = key
'''
CHIP_OK = '''                destinationPending = ""          // [airplayers:chip-ok]
'''

CHIP_FAIL_ANCHOR = '''                Log.w(TAG, "could not select broadcast destination", err)
'''
CHIP_FAIL = '''                destinationPending = ""          // [airplayers:chip-fail]
                paint()
'''

CHIP_DONE_ANCHOR = '''                noteOk("broadcast -> " + preset.label)
'''
CHIP_DONE = '''                readPlayers()                    // [airplayers:chip-done] Playing it follows
'''

PAINT_CHIPS_OLD = '''            chip.isActivated = if (destination in presetChips) {
'''
PAINT_CHIPS_NEW = '''            chip.isActivated = if (destinationPending.isNotBlank()) {
                key == destinationPending        // [airplayers:pending] the tap, until answered
            } else if (destination in presetChips) {
'''

NOTE_ANCHOR = '''    private fun paintNote() {
'''
NOTE = '''        if (destinationPending.isNotBlank()) {          // [airplayers:note]
            routeNote.text = "sending: broadcast -> " +
                (DjOutput.PRESETS[destinationPending]?.label ?: destinationPending) + "…"
            routeNote.setTextColor(rail.resources.getColor(R.color.pine_amber, null))
            return
        }
'''

STR_ANCHOR = '''    <string name="rail_players_waiting">asking the station who is listening…</string>
'''
STR = '''    <!-- [airplayers:strings] -->
    <string name="rail_active_radio">active radio</string>
    <string name="rail_only">only</string>
'''

NEW_FILES = {
    "app/src/main/java/com/pinebox/kiosk/rail/AirReceivers.kt": "kiosk/app/src/main/java/com/pinebox/kiosk/rail/AirReceivers.kt",
    "app/src/main/res/layout/rail_player.xml": "kiosk/app/src/main/res/layout/rail_player.xml",
    "app/src/main/res/drawable/player_row.xml": "kiosk/app/src/main/res/drawable/player_row.xml",
    "app/src/main/res/drawable/player_badge.xml": "kiosk/app/src/main/res/drawable/player_badge.xml",
    "app/src/test/java/com/pinebox/kiosk/AirReceiversTest.kt": "kiosk/app/src/test/java/com/pinebox/kiosk/AirReceiversTest.kt",
}


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha1(fh.read().replace(b"\r\n", b"\n")).hexdigest()


def main(argv):
    if len(argv) != 2 or argv[0] not in ("--check", "--apply"):
        print("usage: --check|--apply <root>")
        return 64
    mode, root = argv
    codes = [
        run(RC, [
            ("[airplayers:fields]", FIELDS_ANCHOR, FIELDS, "after", 1),
            ("[airplayers:read]", READ_ANCHOR, READ, "after", 1),
            ("[airplayers:reconcile]", RECONCILE_ANCHOR, RECONCILE, "after", 1),
            ("[airplayers:paint]", PAINT_PLAYERS_ANCHOR, PAINT_PLAYERS, "after", 1),
            ("[airplayers:rows]", ROWS_ANCHOR, ROWS, "before", 1),
            ("[airplayers:chip]", CHIP_FIRST_ANCHOR, CHIP_FIRST, "after", 1),
            ("[airplayers:chip-ok]", CHIP_OK_ANCHOR, CHIP_OK, "after", 1),
            ("[airplayers:chip-fail]", CHIP_FAIL_ANCHOR, CHIP_FAIL, "after", 1),
            ("[airplayers:chip-done]", CHIP_DONE_ANCHOR, CHIP_DONE, "after", 1),
            ("[airplayers:pending]", PAINT_CHIPS_OLD, PAINT_CHIPS_NEW, "replace", 1),
            ("[airplayers:note]", NOTE_ANCHOR, NOTE, "after", 1),
        ], argv),
        run("app/src/main/res/values/strings.xml",
            [("[airplayers:strings]", STR_ANCHOR, STR, "after", 1)], argv),
    ]
    for rel, src_rel in NEW_FILES.items():
        src = os.path.join(HERE, src_rel)
        dst = os.path.join(root, rel)
        if os.path.exists(dst) and sha(dst) == sha(src):
            print("%s: APPLIED" % rel)
            codes.append(2)
            continue
        if os.path.exists(dst) and not rel.endswith("rail_player.xml"):
            print("%s: MISSING (a different file is there)" % rel)
            codes.append(1)
            continue
        if mode == "--check":
            print("%s: READY" % rel)
            codes.append(0)
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(src, "rb") as fh:
            data = fh.read().replace(b"\r\n", b"\n")
        with open(dst, "wb") as fh:
            fh.write(data)
        print("%s: APPLIED" % rel)
        codes.append(0)
    if 1 in codes or 64 in codes:
        return 1
    return 2 if all(c == 2 for c in codes) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
