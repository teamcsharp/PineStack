package com.pinebox.kiosk

import com.pinebox.kiosk.rail.BroadcastDoctor
import com.pinebox.kiosk.rail.BroadcastDoctor.Hint
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * [smart-reinit] "Get the broadcast back": name the fault, cure only that,
 * ask, and only then climb - and never touch the operator's levels, volume or
 * switches, and never restart the app as the first thing.
 */
class BroadcastDoctorTest {

    private fun station(vararg findings: JSONObject, snapshot: JSONObject = snap()) =
        JSONObject().put("findings", JSONArray(findings.toList())).put("snapshot", snapshot)

    private fun snap(playing: Boolean = true) = JSONObject().put("on", true).put("paused", false)
        .put("playing", playing).put("music_here", true).put("owner", "pbtab")
        .put("routing", JSONObject().put("music", "here").put("voice", "here"))

    private fun stationFinding(key: String, cure: String, kind: String = "fault", consent: Boolean = false) =
        JSONObject().put("key", key).put("kind", kind).put("say", key + " said").put("cure", cure)
            .put("where", "station").put("consent", consent).put("seen_before", 2)

    private fun el(paused: Boolean, t: Double) =
        JSONObject().put("paused", paused).put("ready", 4).put("net", 1).put("t", t).put("err", 0)

    private fun page(
        musicT: Pair<Double, Double> = 10.0 to 11.5, musicPaused: Boolean = false,
        voicePaused: Boolean = true, overdue: Int = 0,
        levels: JSONObject = JSONObject().put("music", 0.3).put("voice", 1.0).put("sfx", 1.0).put("video", 1.0),
        net: String = "web-ok", ctx: String = "running",
    ): BroadcastDoctor.Page {
        fun one(t: Double, voiceT: Double) = JSONObject()
            .put("music", el(musicPaused, t)).put("v0", el(voicePaused, voiceT)).put("v1", el(true, 0.0))
            .put("levels", levels).put("ctx", ctx).put("listener", "pbtab").put("gagged", false)
            .put("pausedFlag", false).put("stateAge", 900).put("overdue", overdue)
            .put("pageAge", 60000).put("gate", JSONObject().put("open", true))
        return BroadcastDoctor.Page(one(musicT.first, 1.0), one(musicT.second, 2.5), net)
    }

    private val ok = BroadcastDoctor.Device(verdict = "RENDERING", route = "the aux cable", musicIndex = 17)

    private fun keys(found: List<BroadcastDoctor.Finding>) = found.map { it.key }

    @Test
    fun aHealthyBroadcastNamesNothingAndTouchesNothing() {
        val found = BroadcastDoctor.diagnose(station(), page(), ok, Hint.NONE)
        assertEquals(emptyList<String>(), keys(found))
        val plan = BroadcastDoctor.plan(found, emptySet(), Hint.NONE, answered = false, nextRung = 0)
        assertTrue(plan.cures.isEmpty())
        assertNull("a first press never climbs the ladder", plan.rung)
    }

    @Test
    fun djsSilentButMusicFineRunsOnlyTheDjRoad() {
        val found = BroadcastDoctor.diagnose(station(stationFinding("dj_silent", "stock")),
            page(), ok, Hint.NONE)
        assertEquals(listOf("dj_silent"), keys(found))
        assertEquals(2, found[0].seenBefore)
        val plan = BroadcastDoctor.plan(found, emptySet(), Hint.NONE, false, 0)
        assertEquals(listOf("stock"), plan.cures.map { it.second })
        // not a page reload, not an app restart
        assertTrue(plan.cures.none { it.second in setOf("reload_page", "restart_app") })
    }

    @Test
    fun capturedNotRenderedReopensTheCaptureThenReleasesIt() {
        val bad = ok.copy(verdict = "CAPTURED_NOT_RENDERED")
        var found = BroadcastDoctor.diagnose(station(), page(), bad, Hint.NONE)
        assertEquals(listOf("captured_not_rendered"), keys(found))
        assertEquals("reopen_capture", found[0].cure)
        assertTrue(found[0].say.contains("the aux cable"))
        found = BroadcastDoctor.diagnose(station(), page(), bad.copy(captureReopened = true), Hint.NOTHING)
        assertEquals("release_capture", found[0].cure)
        val plan = BroadcastDoctor.plan(found, setOf("reopen_capture"), Hint.NOTHING, true, 0)
        assertEquals(listOf("release_capture"), plan.cures.map { it.second })
    }

    @Test
    fun nothingRenderedTakesFocusBack() {
        val found = BroadcastDoctor.diagnose(station(), page(), ok.copy(verdict = "NOT_RENDERED"), Hint.NONE)
        assertEquals(listOf("not_rendered"), keys(found))
        assertEquals("refocus", found[0].cure)
    }

    @Test
    fun volumeAndLevelsAreReportedNeverCured() {
        val found = BroadcastDoctor.diagnose(station(),
            page(levels = JSONObject().put("music", 0.0).put("voice", 1.0).put("sfx", 0.0).put("video", 1.0)),
            ok.copy(musicIndex = 0), Hint.NO_MUSIC)
        assertEquals(setOf("volume_zero", "level_music", "level_sfx"), keys(found).toSet())
        assertTrue(found.all { it.kind == "note" && it.cure.isEmpty() })
        assertTrue(found.first { it.key == "level_music" }.say.contains("Left as you set it"))
        assertTrue(found.first { it.key == "volume_zero" }.say.contains("I will not change it"))
        val plan = BroadcastDoctor.plan(found, emptySet(), Hint.NO_MUSIC, false, 0)
        assertTrue(plan.cures.isEmpty() && plan.offers.isEmpty())
    }

    @Test
    fun theOperatorsSwitchIsOfferedNotFlipped() {
        val found = BroadcastDoctor.diagnose(
            station(stationFinding("play_off", "make_radio", consent = true)), page(), ok, Hint.NONE)
        val plan = BroadcastDoctor.plan(found, emptySet(), Hint.NONE, false, 0)
        assertTrue(plan.cures.isEmpty())
        assertEquals(listOf("make_radio"), plan.offers.map { it.cure })
    }

    @Test
    fun aDeafWebViewOffersTheRestartAndNeverRunsIt() {
        val found = BroadcastDoctor.diagnose(station(), page(net = "web-dead"), ok, Hint.NONE)
        assertTrue("webview_deaf" in keys(found))
        val plan = BroadcastDoctor.plan(found, emptySet(), Hint.NONE, false, 0)
        assertTrue(plan.cures.none { it.second == "restart_app" })
        assertEquals(listOf("restart_app"), plan.offers.map { it.cure })
    }

    @Test
    fun aStalledMusicPlayerIsResumedAndOnlyWhenARecordIsOn() {
        var found = BroadcastDoctor.diagnose(station(), page(musicT = 42.0 to 42.0, musicPaused = true),
            ok, Hint.NONE)
        assertEquals(listOf("music_stalled"), keys(found))
        assertEquals("resume_music", found[0].cure)
        found = BroadcastDoctor.diagnose(station(snapshot = snap(playing = false)),
            page(musicT = 42.0 to 42.0, musicPaused = true), ok, Hint.NONE)
        assertTrue(found.isEmpty())
        // a record change between the samples is moving, not stalled (measured: 358.5 s -> 2.8 s)
        assertTrue(BroadcastDoctor.diagnose(station(), page(musicT = 358.5 to 2.8), ok, Hint.NONE).isEmpty())
        // "No DJs" is not about the music player
        found = BroadcastDoctor.diagnose(station(), page(musicT = 42.0 to 42.0, musicPaused = true),
            ok, Hint.NO_DJS)
        assertTrue(found.isEmpty())
    }

    @Test
    fun overdueLinesWithNoDjPlayerMovingUngagTheQueue() {
        val found = BroadcastDoctor.diagnose(station(), page(overdue = 3), ok, Hint.NONE)
        assertEquals(listOf("voice_stalled"), keys(found))
        assertEquals("ungag", found[0].cure)
        assertTrue(BroadcastDoctor.diagnose(station(), page(overdue = 3, voicePaused = false), ok,
            Hint.NONE).isEmpty())
    }

    @Test
    fun aSuspendedAudioEngineIsResumed() {
        val found = BroadcastDoctor.diagnose(station(), page(ctx = "suspended"), ok, Hint.NONE)
        assertEquals("resume_ctx", found.first { it.key == "ctx_suspended" }.cure)
    }

    @Test
    fun theAnswerSteersAndACureIsNeverRepeated() {
        val found = BroadcastDoctor.diagnose(station(stationFinding("dj_silent", "stock")), page(), ok,
            Hint.NO_MUSIC)
        assertFalse("no music hides the DJ fault", "dj_silent" in keys(found))
        val again = BroadcastDoctor.diagnose(station(stationFinding("dj_silent", "stock")), page(), ok,
            Hint.NO_DJS)
        val plan = BroadcastDoctor.plan(again, setOf("stock"), Hint.NO_DJS, true, 0)
        assertTrue(plan.cures.isEmpty())
        assertEquals("page", plan.rung?.key)
    }

    @Test
    fun theLadderClimbsGentlestFirstAndTheAppRestartIsNotEarly() {
        val keysInOrder = BroadcastDoctor.RUNGS.map { it.key }
        assertEquals(listOf("page", "air", "feed", "reload", "terminal", "services", "restart"), keysInOrder)
        val terminal = BroadcastDoctor.RUNGS.indexOfFirst { "restart_app" in it.local }
        assertEquals(4, terminal)
        // every rung of the station's own ladder is still reachable
        val steps = BroadcastDoctor.RUNGS.flatMap { it.station }.toSet()
        for (step in listOf("relieve", "floor", "flush", "drain", "stock", "release", "reload_pages",
                "stream", "engines", "deep", "steward", "disk", "restart")) {
            assertTrue(step, step in steps)
        }
        // "No music" skips the DJ-only rung
        val plan = BroadcastDoctor.plan(emptyList(), emptySet(), Hint.NO_MUSIC, true, 1)
        assertEquals("feed", plan.rung?.key)
        assertEquals(2, plan.rungIndex)
        // and past the top there is nothing left
        assertNull(BroadcastDoctor.plan(emptyList(), emptySet(), Hint.NOTHING, true,
            BroadcastDoctor.RUNGS.size).rung)
    }

    @Test
    fun aWedgedPageIsNamed() {
        val found = BroadcastDoctor.diagnose(station(), BroadcastDoctor.Page(null, null, ""), ok, Hint.NONE)
        assertEquals(listOf("page_unreachable"), keys(found))
        assertEquals("reload_page", found[0].cure)
    }

    @Test
    fun everyCureHasWords() {
        for (cure in listOf("onair", "relieve", "stock", "bank", "flush", "solo", "reopen_capture",
                "release_capture", "refocus", "leave_standby", "resume_ctx", "catch_up", "ungag",
                "lift_duck", "resume_music", "reload_page", "make_radio", "restart_app")) {
            assertTrue(cure, BroadcastDoctor.CURES.containsKey(cure))
        }
    }
}
