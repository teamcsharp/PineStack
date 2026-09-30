package com.pinebox.kiosk.rail

import org.json.JSONObject

/**
 * [airplayers] PLAYING IT: WHICH RECEIVERS SOUND THE STATION - A SET.
 *
 * The operator, 2026-09-29: "i want the buttons to redirect audio to be
 * responsive. i want to be able to enable and disable streams from there as
 * well by enabling them from receiving a broadcast. For example the nabu is
 * broadcasting. If it were listed, I would uncheck it from being audible and
 * enable the pinetab to be the active radio. Also I would turn off the pine
 * app audio for now since i am listening throuhg the pinetablet".
 *
 * The station owns the set: GET/POST /api/air/receivers (app.py, the
 * `[airplayers]` block). Every receiver - the PineTab, this app, web pages,
 * the car's tune-in link, the Nabu, the Pine Box speaker - has its own
 * "audible" switch; {"only": id} makes one the only one sounding in the
 * house. A page receiver switched off mutes ITSELF (the clock says
 * `hushed`); a speaker switched off is simply not sent to. Nothing here
 * changes a volume.
 *
 * Pure Kotlin, no android.*: the reading, the optimistic step and the
 * words are what must be testable without a device.
 */
object AirReceivers {

    const val ROUTE = "/api/air/receivers"

    data class Receiver(
        val id: String,
        val label: String,
        /** "page" (mutes itself) or "speaker" (not sent to). */
        val kind: String,
        /** The switch: may this receiver sound the station. */
        val audible: Boolean,
        /** Switched on AND actually able to sound right now. */
        val sounding: Boolean,
        val present: Boolean,
        /** The active radio - the one the air belongs to. */
        val active: Boolean,
        val ownsAir: Boolean,
        val detail: String,
        /** Seconds since it last reported hearing the station, or null. */
        val heardAgo: Double?,
    )

    data class State(
        val receivers: List<Receiver> = emptyList(),
        val active: String = "",
        val say: String = "",
        /** Set when the station refused the last write. */
        val refused: String = "",
        val why: String = "",
    ) {
        fun of(id: String): Receiver? = receivers.firstOrNull { it.id == id }
    }

    fun read(body: JSONObject?): State? {
        val rows = body?.optJSONArray("receivers") ?: return null
        val out = ArrayList<Receiver>(rows.length())
        for (i in 0 until rows.length()) {
            val row = rows.optJSONObject(i) ?: continue
            val id = row.optString("id")
            if (id.isBlank()) continue
            out.add(
                Receiver(
                    id = id,
                    label = row.optString("label").ifBlank { id },
                    kind = row.optString("kind", "page"),
                    audible = row.optBoolean("audible", false),
                    sounding = row.optBoolean("sounding", false),
                    present = row.optBoolean("present", false),
                    active = row.optBoolean("active", false),
                    ownsAir = row.optBoolean("owns_air", false),
                    detail = row.optString("detail"),
                    heardAgo = if (row.isNull("heard_ago") || !row.has("heard_ago")) null
                    else row.optDouble("heard_ago"),
                )
            )
        }
        return State(
            receivers = out,
            active = body.optString("active"),
            say = body.optString("say"),
            refused = body.optString("refused"),
            why = body.optString("why"),
        )
    }

    /** The body for one switch. */
    fun flip(id: String, audible: Boolean): String =
        JSONObject().put("id", id).put("audible", audible).toString()

    /** The body for "only this one". */
    fun only(id: String): String = JSONObject().put("only", id).toString()

    /** [radio-tap] The row tap: this one on AND the radio, nothing else off. */
    fun radio(id: String): String =
        JSONObject().put("id", id).put("audible", true).put("radio", true).toString()

    /**
     * What a tap looks like THE MOMENT it lands, before the station answers:
     * the switch moved and the row marked pending. The station's answer then
     * replaces it wholesale.
     */
    fun optimistic(state: State, id: String, audible: Boolean): State =
        state.copy(receivers = state.receivers.map {
            if (it.id == id) it.copy(audible = audible) else it
        })

    /** "only" - the car keeps its own switch; it is not in the room (#1253). */
    fun optimisticOnly(state: State, id: String): State =
        state.copy(active = id, receivers = state.receivers.map {
            when {
                it.id == id -> it.copy(audible = true, active = true)
                it.id == "car" -> it.copy(active = false)
                else -> it.copy(audible = false, active = false)
            }
        })

    /** [radio-tap] the row tap: on and the active radio; the others keep
     *  their switches, only the badge moves. */
    fun optimisticRadio(state: State, id: String): State =
        state.copy(active = id, receivers = state.receivers.map {
            if (it.id == id) it.copy(audible = true, active = true)
            else it.copy(active = false)
        })

    /** The ids a write is waiting on, so no poll repaints them meanwhile. */
    fun touched(state: State, id: String, only: Boolean): Set<String> =
        if (!only) setOf(id)
        else state.receivers.map { it.id }.filter { it != "car" }.toSet()

    /** The second line of a row. */
    fun detail(r: Receiver, pending: Boolean): String {
        val bits = ArrayList<String>(4)
        if (pending) bits.add(if (r.audible) "switching on…" else "switching off…")
        else if (r.kind == "page" && r.audible && r.present && !r.sounding) {
            bits.add("on - another page holds the air")
        }
        if (r.detail.isNotBlank()) bits.add(r.detail)
        r.heardAgo?.let { bits.add("heard " + ago(it)) }
        return bits.joinToString(" · ")
    }

    fun ago(seconds: Double): String {
        val s = Math.round(seconds)
        return if (s < 90) s.toString() + "s ago" else Math.round(s / 60.0).toString() + "m ago"
    }

    /** The line under the list: the refusal in words, else the station's. */
    fun note(state: State): String = when {
        state.refused.isNotBlank() -> "refused: " + state.why.ifBlank { "the station said no" }
        state.say.isNotBlank() -> state.say
        state.receivers.isEmpty() -> "nothing is listening"
        else -> ""
    }

    /** For tests and logs: the switches as one short string. */
    fun summary(state: State): String = state.receivers.joinToString(" ") {
        it.id + (if (it.audible) "+" else "-") + (if (it.active) "*" else "")
    }
}
