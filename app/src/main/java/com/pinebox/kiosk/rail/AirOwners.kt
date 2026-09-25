package com.pinebox.kiosk.rail

import org.json.JSONArray
import org.json.JSONObject

/**
 * WHO IS PLAYING THE SHOW, AND WHO SHOULD BE.
 *
 * The operator's ask: "I want to see every application that's currently
 * having the audio broadcasted to it... and I wanna be able to check and
 * uncheck that from this Pine Box tab on the mobile device in order to set
 * what device is picking it up. Because my goal is to have audio play out of
 * only the Pine tab, but I still wanna be able to adjust the Pine Box app on
 * the computer."
 *
 * THE STATION ALREADY DOES THE HARD HALF, and it must not be reimplemented
 * here. #1008 (app.py:25001) gives ONE listener the air; every other page
 * gags itself in pineSoloGate (app.py:154557), and an owner that stops
 * polling releases it after AUDIO_OWNER_LIFE (90s) so the house can never be
 * left silent. The routes are:
 *
 *   GET  /api/radio/listeners  93230  the roster + who holds the air
 *   POST /api/radio/solo       93246  {"listener": id} | {"clear": true}
 *
 * So this class is not a muting engine. It turns that roster into rows a
 * thumb can read, and turns a tap into one of those two posts.
 *
 * WHAT IT ADDS. The roster identifies a player by a listener id that is
 * minted fresh on every page load - so "the tablet has the air" survives
 * until the tablet reloads, and then quietly does not. The station's
 * settings carry a `terminals` table keyed by DEVICE, each row holding an
 * `addr`, a name and that device's own volumes. Matching the roster against
 * that table by address is what lets a row say "PineTab" rather than
 * "pbnvgdtefn", lets the desktop set the tablet's levels, and lets the air
 * be re-claimed for the tablet after a reload without anyone touching it.
 */
object AirOwners {

    /** One player on the broadcast, ready to paint. */
    data class Player(
        /** The listener id - what /api/radio/solo wants. */
        val listener: String,
        /** The device row this matched in `terminals`, or "". */
        val device: String,
        /** What to show: the device's name, else the address. */
        val label: String,
        /** "a browser tab", "10.89.1.154", "4s ago" - the identifying detail. */
        val detail: String,
        val addr: String,
        /** Holds the air right now: every other page is gagged. */
        val owns: Boolean,
        /** Seconds since it last polled. */
        val seen: Double,
    )

    data class Roster(
        val players: List<Player> = emptyList(),
        /** The listener holding the air, or "" when everybody may play. */
        val owner: String = "",
        /** The station's own sentence about the situation. */
        val say: String = "",
    ) {
        val soloed: Boolean get() = owner.isNotBlank()
        fun of(listener: String): Player? = players.firstOrNull { it.listener == listener }
    }

    /**
     * Read the roster, naming players from the terminals table where the
     * address matches.
     *
     * @param listeners the body of GET /api/radio/listeners
     * @param settings the station settings, for `terminals` (may be null)
     */
    fun read(listeners: JSONObject?, settings: JSONObject? = null): Roster {
        if (listeners == null) return Roster()
        val owner = listeners.optString("audio_owner", "")
        val rows = listeners.optJSONArray("listeners") ?: JSONArray()
        val table = settings?.optJSONObject("terminals")
        val out = ArrayList<Player>(rows.length())
        for (i in 0 until rows.length()) {
            val row = rows.optJSONObject(i) ?: continue
            val listener = row.optString("listener")
            if (listener.isBlank()) continue
            val addr = row.optString("addr")
            /* [#1185] THE STATION DECIDES WHAT A PLAYER IS, NOT THIS SIDE.
             *
             * It can see the three things that settle it and this side
             * cannot: the listener id prefix the Electron shell mints, the
             * `PineBoxKiosk/<ver>` marker in the kiosk WebView's own user
             * agent, and the x-pinebox-public header that says the poll
             * came through the public listener door. Matching an ADDRESS
             * against the terminals table - which is what this used to do -
             * cannot tell two surfaces on one machine apart, and drew a
             * browser window on the desk as "This app" beside the real one.
             *
             * `deviceFor` stays as the fallback so a tablet running ahead of
             * a station restart still paints something sensible. */
            val device = row.optString("device")
                .ifBlank { deviceFor(table, addr, listener) }
            val name = row.optString("name")
                .ifBlank { table?.optJSONObject(device)?.optString("name").orEmpty() }
            val seen = row.optDouble("seen", -1.0)
            val label = name.ifBlank { addr.ifBlank { listener } }
            out.add(
                Player(
                    listener = listener,
                    device = device,
                    label = label,
                    detail = detailOf(row, addr, name.isNotBlank(), seen, device, label),
                    addr = addr,
                    owns = listener == owner && owner.isNotBlank(),
                    seen = seen,
                )
            )
        }
        /* The one making the noise first, then by name, so the list does not
         * reshuffle under a thumb every time a poll lands. */
        out.sortWith(compareByDescending<Player> { it.owns }.thenBy { it.label })
        return Roster(out, owner, listeners.optString("say", ""))
    }

    private fun detailOf(
        row: JSONObject, addr: String, named: Boolean, seen: Double, device: String,
        label: String = "",
    ): String {
        val bits = ArrayList<String>(4)
        if (named && addr.isNotBlank()) bits.add(addr)
        /* [#1185] the station's own word for this surface when it has one,
         * and never repeated when it is already the row's name. */
        val what = row.optString("what")
            .ifBlank { kindOf(row.optString("listener"), device) }
        if (what.isNotBlank() && !what.equals(label, ignoreCase = true)) bits.add(what)
        /* [#1185] several listener ids collapsed into this one row: a page
         * that reloaded, or two tabs of the same thing. One device. */
        val surfaces = row.optInt("surfaces", 1)
        if (surfaces > 1) bits.add(surfaces.toString() + " tabs")
        if (seen >= 0) bits.add(Math.round(seen).toString() + "s ago")
        return bits.joinToString(" · ")
    }

    /**
     * WHAT a player is, not just where it is.
     *
     * "Also refer to an application instance in the list of instances that's
     * running. So that way I know that a page is a web page or that someone's
     * running the Electron Pine Box app."
     *
     * The station says "a browser tab" for all of them, because from its side
     * that is all they are - a page polling /api/dj. They are not the same
     * thing to operate, and telling them apart is the difference between
     * handing the air to the right room and guessing. The Electron app mints
     * `desktop-<rand>` (renderer.js desktopListenerId), so it names itself.
     */
    fun kindOf(listener: String, device: String): String = when {
        listener.startsWith("desktop-") -> "the Pine Box app"
        device == "pinetab" -> "the PineTab"
        device.isNotBlank() -> "a Pine Box terminal"
        else -> "a web page"
    }

    /**
     * Which `terminals` row this player is.
     *
     * The id wins over the address, and a row that NAMES a listener will not
     * be matched by address to anything else. Two tabs on one machine share
     * an address - the desktop app and a browser window both sat on
     * 10.89.1.13 when this was written - so without that rule, pinning a row
     * to one of them would quietly claim the other as well, and the operator
     * would be setting the levels of a tab he wasn't listening to.
     */
    fun deviceFor(table: JSONObject?, addr: String, listener: String): String {
        if (table == null) return ""
        val keys = table.keys()
        var byAddr = ""
        while (keys.hasNext()) {
            val key = keys.next()
            val row = table.optJSONObject(key) ?: continue
            val pinned = row.optString("listener")
            if (pinned.isNotBlank()) {
                if (pinned == listener) return key
                continue                     /* spoken for, not by this one */
            }
            if (addr.isNotBlank() && row.optString("addr") == addr && byAddr.isBlank()) {
                byAddr = key
            }
        }
        return byAddr
    }

    /**
     * The body for a tap on a player.
     *
     * Checking a player hands it the air. Unchecking the one that HAS it
     * clears the owner, which does not silence anything - it lets every page
     * play again, which is the station's own default. There is deliberately
     * no way from here to leave nothing playing: a tablet that silences the
     * whole house with one tap and gives no clue why is worse than one that
     * plays in two rooms.
     */
    fun tap(player: Player): String =
        if (player.owns) JSONObject().put("clear", true).toString()
        else JSONObject().put("listener", player.listener).toString()

    /**
     * The line under the list. It says what is true, not what was asked for.
     */
    fun note(roster: Roster): String {
        if (roster.players.isEmpty()) return "nothing is listening"
        val owner = roster.players.firstOrNull { it.owns }
        if (owner != null) {
            return "only " + owner.label + " is sounding — every other page is muted"
        }
        if (roster.players.size == 1) return "one player, no overlap possible"
        return roster.players.size.toString() +
            " players, all sounding at once — tap one to give it the air"
    }

    /**
     * Which player SHOULD hold the air, from the terminals table, or "" for
     * no opinion.
     *
     * This is what makes the air survive a reload: the table names a device,
     * the roster says which listener id that device is using right now. A
     * device switched on but not in the roster has nothing to hand the air
     * to, so the row marked `fallback` gets it instead - which is the
     * operator's rule, "when i turn the tablet off or switch it's broadcast
     * off".
     */
    fun shouldOwn(roster: Roster, settings: JSONObject?): String {
        val table = settings?.optJSONObject("terminals") ?: return ""
        val wanted = ArrayList<String>()
        val fallbacks = ArrayList<String>()
        val keys = table.keys()
        while (keys.hasNext()) {
            val key = keys.next()
            val row = table.optJSONObject(key) ?: continue
            if (row.optBoolean("play", false)) wanted.add(key)
            if (row.optBoolean("fallback", false)) fallbacks.add(key)
        }
        /* ONE PLACE, NEVER TWO.
         *
         * This used to abstain when more than one device was switched on,
         * on the reasoning that "the box and the tablet" was a legitimate
         * thing to want. The operator has since ruled that out in as many
         * words: "singularly the PineTab or the Pine Box or the Nabu
         * device, the app instance or the application loaded on PC.
         * Individually but never at the same time."
         *
         * So more than one switched on is a fault to be RESOLVED, not a
         * preference to be honoured - and abstaining was the worst of the
         * three options, because it left the air wherever it happened to
         * be while two rooms played a half-second apart. Resolved by id
         * order, which is the same rule terminal-audio.cjs uses, so the
         * tablet and the desktop reach the same answer without talking to
         * each other.
         */
        if (wanted.isEmpty()) {
            if (fallbacks.size == 1) {
                return roster.players.firstOrNull { it.device == fallbacks[0] }?.listener ?: ""
            }
            return ""
        }
        wanted.sort()
        val here = roster.players.firstOrNull { it.device == wanted[0] }
        if (here != null) return here.listener
        /* The device that should be playing is not here. Hand it over. */
        for (key in fallbacks.sorted()) {
            val taker = roster.players.firstOrNull { it.device == key }
            if (taker != null) return taker.listener
        }
        return ""
    }
}
