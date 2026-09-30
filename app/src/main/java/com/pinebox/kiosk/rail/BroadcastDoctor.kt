package com.pinebox.kiosk.rail

import org.json.JSONArray
import org.json.JSONObject

/**
 * [smart-reinit] GET THE BROADCAST BACK - DIAGNOSIS FIRST, THEN THE SMALLEST
 * CURE, THEN ASK, THEN ESCALATE.
 *
 * The operator, 2026-09-30: "Whenever I bring up the broadcast and I can't
 * hear the music or the DJs, I just click this button. So I need this button
 * to intelligently be able to tell what's needing to be done so it does that
 * and doesn't reinitialize things that don't need to be reinitialized because
 * if I just need to DJs to play it, then it should just be able to
 * intelligently run fixes to get the broadcast back and then query me and ask
 * me if the broadcast is working suitably and then from there into
 * troubleshooting before advancing to more advanced and intense of steps."
 *
 * The button used to run every rung whatever the symptom, and one of them
 * restarted this app - which restarts the audio. This is the pure half: it
 * takes what the station named (GET /api/broadcast/diagnose), what the page
 * reported about its own players (two samples, [PAGE_PROBE]) and what the
 * tablet measured about its own audio (AudioHealth), and returns findings in
 * plain words, most specific first, each with the one cure for it. The
 * station's ladder (POST /api/broadcast/fix/{step}) is still all there, as
 * [RUNGS], behind the diagnosis, in increasing intensity.
 *
 * Rules it keeps, and the tests pin: the operator's levels, the Android
 * volume and his routing are REPORTED, never changed; a cure that changes
 * something he set (his out-loud switch) is only OFFERED; restarting this app
 * is never the first thing done.
 */
object BroadcastDoctor {

    enum class Hint(val key: String, val label: String) {
        NONE("", "just pressed"),
        NO_MUSIC("no_music", "No music"),
        NO_DJS("no_djs", "No DJs"),
        NOTHING("nothing", "No sound at all"),
        OTHER("other", "Other");

        companion object {
            fun of(key: String?): Hint = values().firstOrNull { it.key == key } ?: NONE
        }
    }

    /** What a finding is about, so the operator's answer can steer. */
    enum class About { MUSIC, DJS, ALL }

    data class Finding(
        val key: String,
        /** "fault" stops sound; "note" is reported and never touched. */
        val kind: String,
        val say: String,
        /** A cure key - see [CURES] - or "" when nothing here can help. */
        val cure: String,
        val where: String,
        /** The cure changes something the operator set: offer, never run. */
        val consent: Boolean = false,
        val about: About = About.ALL,
        val seenBefore: Int = 0,
    ) {
        val fault: Boolean get() = kind == "fault"
    }

    /** Every cure the doctor may run, with the words for what it did. */
    val CURES: Map<String, String> = linkedMapOf(
        // the station's roads: POST /api/broadcast/fix/{step}
        "onair" to "put the station back on air",
        "relieve" to "stood the station's writing rooms down so its loop can serve the air",
        "stock" to "asked the station to air a round that is ready (the owed-air road)",
        "bank" to "asked the station to finish a round now",
        "flush" to "had the station drop the clips this page could not start",
        // POST /api/radio/solo
        "solo" to "gave this tablet the air",
        // on this tablet
        "reopen_capture" to "re-opened the replay ring's sound capture so the tablet renders again",
        "release_capture" to "released the replay ring's sound capture (it comes back when the app next resumes)",
        "refocus" to "took media focus back so the page's sound is rendered",
        "leave_standby" to "brought the tablet out of standby",
        "resume_ctx" to "resumed the page's audio engine",
        "catch_up" to "had the page re-read the station clock and the DJ feed",
        "ungag" to "cleared the page's own stuck flags and restarted its DJ queue",
        "lift_duck" to "lifted a duck that never released",
        "resume_music" to "resumed the music player",
        "reload_page" to "reloaded this page",
        "reopen_page" to "opened the station page again",
        // offered only
        "make_radio" to "made this tablet the radio (its out-loud switch on)",
        "restart_app" to "restarted this app (the sound restarts with it)",
    )

    /** A rung behind the diagnosis: the existing ladder, gentlest first. */
    data class Rung(
        val key: String,
        val say: String,
        /** Station steps (POST /api/broadcast/fix/{step}), in order. */
        val station: List<String> = emptyList(),
        /** Local cures run before the station steps. */
        val local: List<String> = emptyList(),
        /** Skipped when the operator's answer is about something else. */
        val about: About = About.ALL,
    )

    val RUNGS: List<Rung> = listOf(
        Rung("page", "catch this page up: its own flags, any duck, the clock and the DJ feed",
            local = listOf("ungag", "lift_duck", "catch_up")),
        Rung("air", "nudge the station's air: stand the writing rooms down, take the floor " +
            "back, drain held clips, air a ready round",
            station = listOf("relieve", "floor", "drain", "stock"), about = About.DJS),
        Rung("feed", "drop what the pages are stuck on and hand the air to a device that is on",
            station = listOf("flush", "handover", "release")),
        Rung("reload", "reload every page in the house (this one too)",
            station = listOf("reload_pages")),
        Rung("terminal", "restart this app - the sound restarts with it",
            local = listOf("restart_app")),
        Rung("services", "repair the station's services: the stream, the voice engines, " +
            "the deep ladder, the steward, the disk",
            station = listOf("stream", "engines", "deep", "steward", "disk")),
        Rung("restart", "restart the station process - about twenty seconds of silence",
            station = listOf("restart")),
    )

    private val DJ_KEYS = setOf("dj_silent", "dj_nothing_ready", "voice_routed_away",
        "voice_stalled", "level_voice")
    private val MUSIC_KEYS = setOf("music_routed_away", "music_on_box", "no_record",
        "music_stalled", "level_music")

    private fun aboutOf(key: String): About = when (key) {
        in DJ_KEYS -> About.DJS
        in MUSIC_KEYS -> About.MUSIC
        else -> About.ALL
    }

    fun relevant(about: About, hint: Hint): Boolean = when (hint) {
        Hint.NO_MUSIC -> about != About.DJS
        Hint.NO_DJS -> about != About.MUSIC
        else -> true
    }

    /* ------------------------------------------------------------------ */

    /** The page's own answer to [PAGE_PROBE], or null when it gave none. */
    data class Page(val a: JSONObject?, val b: JSONObject?, val net: String)

    /** What the tablet itself measured. */
    data class Device(
        /** AudioHealth.Verdict name, or "" when it could not be read. */
        val verdict: String = "",
        val verdictSay: String = "",
        val route: String = "",
        val musicIndex: Int = -1,
        val musicMuted: Boolean = false,
        val focusHeld: Boolean = true,
        val standby: Boolean = false,
        /** The replay capture was already re-opened this run and did not help. */
        val captureReopened: Boolean = false,
    )

    /** The station's findings, from GET /api/broadcast/diagnose. */
    fun stationFindings(answer: JSONObject?): List<Finding> {
        val rows = answer?.optJSONArray("findings") ?: return emptyList()
        val out = mutableListOf<Finding>()
        for (i in 0 until rows.length()) {
            val f = rows.optJSONObject(i) ?: continue
            val key = f.optString("key")
            if (key.isBlank()) continue
            out.add(Finding(key, f.optString("kind", "fault"), f.optString("say"),
                f.optString("cure"), f.optString("where", "station"),
                f.optBoolean("consent", false), aboutOf(key), f.optInt("seen_before", 0)))
        }
        return out
    }

    private fun el(o: JSONObject?, name: String): JSONObject? = o?.optJSONObject(name)

    /** Moving between the two samples. Either way: measured on the tablet,
     *  a record change reads 358.5 s then 2.8 s, a second and a half apart. */
    private fun advancing(a: JSONObject?, b: JSONObject?): Boolean {
        if (a == null || b == null) return false
        return !b.optBoolean("paused", true) &&
            Math.abs(b.optDouble("t", 0.0) - a.optDouble("t", 0.0)) > 0.25
    }

    /** Everything wrong on this side of the glass, most specific first. */
    fun tabletFindings(page: Page?, device: Device?, station: JSONObject?): List<Finding> {
        val out = mutableListOf<Finding>()
        val snap = station?.optJSONObject("snapshot")
        val stationUp = snap != null && snap.optBoolean("on", false) && !snap.optBoolean("paused", false)

        // --- the tablet's own audio: the faults no page reading can see ---
        if (device != null) {
            if (device.standby) out.add(Finding("standby", "fault",
                "The tablet is in standby, which relaxes the radio.", "leave_standby", "tablet"))
            when (device.verdict) {
                "CAPTURED_NOT_RENDERED" -> out.add(Finding("captured_not_rendered", "fault",
                    "The tablet's sound is being captured but not rendered: the replay ring's " +
                        "playback capture is holding it on the remote submix, so nothing reaches " +
                        device.route.ifBlank { "the output" } + ".",
                    if (device.captureReopened) "release_capture" else "reopen_capture", "tablet"))
                "NOT_RENDERED" -> out.add(Finding("not_rendered", "fault",
                    "This app is playing but every output on the tablet is idle - nothing is " +
                        "being rendered.", "refocus", "tablet"))
            }
            if (!device.focusHeld && out.none { it.cure == "refocus" }) out.add(Finding("no_focus",
                "fault", "This app does not hold media focus, so the page's sound may not be " +
                    "rendered.", "refocus", "tablet"))
            if (device.musicIndex == 0 || device.musicMuted) out.add(Finding("volume_zero", "note",
                "The tablet's media volume is " + (if (device.musicMuted) "muted" else "at 0") +
                    " on " + device.route.ifBlank { "this output" } +
                    ". Turn it up with the volume keys - I will not change it.", "", "you"))
        }

        // --- the page -------------------------------------------------------
        if (page == null || page.a == null) {
            out.add(Finding("page_unreachable", "fault",
                "The station page did not answer - it is wedged.", "reload_page", "tablet"))
            return out
        }
        val a = page.a
        val b = page.b ?: a
        if (page.net == "web-dead" || page.net == "web-timeout" || page.net == "web-threw") {
            out.add(Finding("webview_deaf", "fault",
                "This page cannot reach the station while the app can - the WebView's network " +
                    "has died. Only restarting this app cures that, and it restarts the sound.",
                "restart_app", "you", consent = true))
        }
        val stateAge = b.optLong("stateAge", -1)
        if (stateAge > 30_000) out.add(Finding("page_stopped_polling", "fault",
            "The page stopped reading the station " + stateAge / 1000 + " s ago.", "catch_up", "tablet"))
        if (b.optString("ctx") == "suspended") out.add(Finding("ctx_suspended", "fault",
            "The page's audio engine is suspended, so nothing it plays is heard.", "resume_ctx", "tablet"))
        val gate = b.optJSONObject("gate")
        if (gate != null && !gate.optBoolean("open", true) && b.optLong("pageAge", 0) > 10_000) {
            out.add(Finding("level_gate_shut", "fault",
                "The page's level gate never opened, so every player is held at zero.",
                "reload_page", "tablet"))
        }
        if (stationUp && b.optBoolean("pausedFlag", false)) out.add(Finding("page_paused_flag", "fault",
            "This page still thinks the station is paused.", "ungag", "tablet"))
        val owner = snap?.optString("owner").orEmpty()
        val me = b.optString("listener")
        if (stationUp && b.optBoolean("gagged", false) && (owner.isBlank() || owner == me)
            && !(snap?.optBoolean("hushed", false) ?: false)) {
            out.add(Finding("page_gagged_self", "fault",
                "This page has muted itself although nothing on the station asks it to.",
                "catch_up", "tablet"))
        }
        val duck = b.optJSONObject("duck")
        val duckA = a.optJSONObject("duck")
        if (duck != null && duckA != null && (duck.optBoolean("padMuted") && duckA.optBoolean("padMuted"))) {
            out.add(Finding("duck_stuck", "fault",
                "A sampler duck is holding the broadcast down and never released.", "lift_duck", "tablet"))
        }

        // --- the players, against what the station is sending ---------------
        val routing = snap?.optJSONObject("routing")
        val musicHere = stationUp && snap!!.optBoolean("playing", false)
            && snap.optBoolean("music_here", true)
            && (routing == null || routing.optString("music", "here") in setOf("here", "both"))
        val mA = el(a, "music")
        val mB = el(b, "music")
        if (musicHere && !advancing(mA, mB)) {
            val why = when {
                mB == null -> "there is no music player on the page"
                mB.optInt("err", 0) != 0 -> "the music player failed (error " + mB.optInt("err") + ")"
                mB.optBoolean("paused", true) -> "the music player is paused"
                else -> "the music player is not moving (ready " + mB.optInt("ready") +
                    ", network " + mB.optInt("net") + ")"
            }
            out.add(Finding("music_stalled", "fault",
                "The station is playing a record and " + why + ".", "resume_music", "tablet",
                about = About.MUSIC))
        }
        val voiceMoving = advancing(el(a, "v0"), el(b, "v0")) || advancing(el(a, "v1"), el(b, "v1"))
        val overdue = b.optInt("overdue", 0)
        if (stationUp && !voiceMoving && overdue > 0) {
            out.add(Finding("voice_stalled", "fault",
                "The page holds " + overdue + " DJ line(s) that were due over 15 s ago and " +
                    "neither DJ player is moving.", "ungag", "tablet", about = About.DJS))
        }

        // --- the operator's levels: REPORTED, never changed ----------------
        val levels = b.optJSONObject("levels")
        if (levels != null) {
            for ((key, name) in listOf("music" to "Music", "voice" to "DJs",
                    "sfx" to "Replies (SFX)", "video" to "Video")) {
                if (levels.has(key) && levels.optDouble(key, 1.0) <= 0.0) {
                    out.add(Finding("level_$key", "note",
                        "The $name level is at 0 (this drawer, Streams: the $name slider). " +
                            "Left as you set it.", "", "you",
                        about = if (key == "music") About.MUSIC else if (key == "voice") About.DJS else About.ALL))
                }
            }
        }
        return out
    }

    /** Station findings then tablet findings, deduplicated, filtered by the
     *  operator's answer. Notes always stay: they are how he learns a level
     *  he set is the reason. */
    fun diagnose(station: JSONObject?, page: Page?, device: Device?, hint: Hint): List<Finding> {
        val all = stationFindings(station) + tabletFindings(page, device, station)
        val seen = mutableSetOf<String>()
        return all.filter { seen.add(it.key) }
            .filter { !it.fault || relevant(it.about, hint) }
    }

    /** What to do now. */
    data class Plan(
        /** Cures to run now, in order. */
        val cures: List<Pair<Finding, String>>,
        /** Cures that need the operator's own tap. */
        val offers: List<Finding>,
        /** The rung to climb when there is no targeted cure left, or null. */
        val rung: Rung?,
        val rungIndex: Int,
    )

    /**
     * The smallest step. A named fault's own cure first - every named fault,
     * each with its own cure, once per run. Only when the diagnosis has no
     * untried cure does the next rung run, and only after the operator has
     * answered (a first press never climbs). Restarting this app is never
     * the first thing done: it is either offered (the deaf WebView) or it is
     * the fifth rung.
     */
    fun plan(found: List<Finding>, tried: Set<String>, hint: Hint,
             answered: Boolean, nextRung: Int): Plan {
        val cures = mutableListOf<Pair<Finding, String>>()
        val offers = mutableListOf<Finding>()
        val taking = mutableSetOf<String>()
        for (f in found) {
            if (!f.fault || f.cure.isBlank()) continue
            if (f.consent || f.cure == "make_radio" || f.cure == "restart_app") {
                if (f.cure !in tried) offers.add(f)
                continue
            }
            if (f.cure in tried || f.cure in taking) continue
            taking.add(f.cure)
            cures.add(f to f.cure)
        }
        if (cures.isNotEmpty() || !answered) return Plan(cures, offers, null, nextRung)
        var i = nextRung
        while (i < RUNGS.size && !relevant(RUNGS[i].about, hint)) i += 1
        return Plan(cures, offers, RUNGS.getOrNull(i), i)
    }

    /** Asked of the page twice, a second and a half apart. evaluateJavascript
     *  hands the object back as JSON. Reads only - it starts one fetch to
     *  learn whether the WebView's own network is alive, as #1318 did. */
    const val PAGE_PROBE = """
        (function () {
          var o = {at: Date.now()};
          function el(a) {
            if (!a) return null;
            return {paused: !!a.paused, ready: a.readyState | 0, net: a.networkState | 0,
                    t: +a.currentTime || 0, muted: !!a.muted, vol: +a.volume,
                    src: !!(a.currentSrc || a.src), err: a.error ? a.error.code : 0};
          }
          try { o.music = el(musicPlayer); } catch (e) { o.music = null; }
          try { o.v0 = el(djVoiceAudio0); } catch (e) {}
          try { o.v1 = el(djVoiceAudio1); } catch (e) {}
          try { o.levels = window.pineLevels && pineLevels.get ? pineLevels.get() : null; } catch (e) {}
          try { o.gate = typeof pineLevelGateState === 'function' ? pineLevelGateState() : null; } catch (e) {}
          try { o.ctx = window.pineAudioCtx ? String(pineAudioCtx.state) : ''; } catch (e) {}
          try { o.listener = typeof pineListenerId === 'function' ? String(pineListenerId()) : ''; } catch (e) {}
          try { o.gagged = !!window.__pineGagged; } catch (e) {}
          try { o.pausedFlag = typeof pineAirPaused !== 'undefined' && !!pineAirPaused; } catch (e) {}
          try { o.stateAge = (typeof djStateAt !== 'undefined' && djStateAt) ? Date.now() - djStateAt : -1; } catch (e) { o.stateAge = -1; }
          try { o.pageAge = Math.round(performance.now()); } catch (e) {}
          try {
            var q = (typeof djVoiceQueue !== 'undefined' && djVoiceQueue) || [];
            o.queue = q.length;
            o.overdue = q.filter(function (c) {
              return c && Number(c.broadcastAt || 0) > 0 && Date.now() - Number(c.broadcastAt) > 15000;
            }).length;
          } catch (e) {}
          try { o.duck = window.PineAir && PineAir.duckState ? PineAir.duckState() : null; } catch (e) {}
          try {
            o.meter = {};
            ['musicPlayer', 'djVoiceAudio0', 'djVoiceAudio1'].forEach(function (id) {
              var r = window.PineMeters && PineMeters.read ? PineMeters.read(id) : null;
              o.meter[id] = r ? r.peak : -1;
            });
          } catch (e) {}
          try {
            var p = window.__pineDoctorNet;
            if (!p || Date.now() - p.at > 20000) {
              p = window.__pineDoctorNet = {at: Date.now(), state: 'asking'};
              var t = setTimeout(function () { if (p.state === 'asking') p.state = 'web-timeout'; }, 12000);
              fetch('/api/dj/sections', {cache: 'no-store'}).then(function (r) {
                clearTimeout(t); p.state = r.status > 0 ? 'web-ok' : 'web-bad';
              }, function () { clearTimeout(t); p.state = 'web-dead'; });
            }
            o.net = p.state;
          } catch (e) { o.net = 'web-threw'; }
          return o;
        })()
    """

    /** The words for a list of findings. */
    fun describe(found: List<Finding>): List<String> =
        if (found.isEmpty()) listOf("nothing I can measure is wrong: the station is on air and " +
            "sending, and this tablet is playing and rendering it")
        else found.map { f ->
            (if (f.fault) "" else "note: ") + f.say +
                (if (f.seenBefore > 0) " (seen in " + f.seenBefore + " earlier run" +
                    (if (f.seenBefore == 1) "" else "s") + " this week)" else "")
        }

    fun keys(found: List<Finding>, faults: Boolean): JSONArray =
        JSONArray(found.filter { it.fault == faults }.map { it.key })
}
