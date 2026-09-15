package com.pinebox.kiosk.config

import com.pinebox.kiosk.replay.ScreenReplay
import org.json.JSONObject

/**
 * THE HOT CORNERS - one door for the bridge and the drawer.
 *
 * "If I swipe into the tablet from the top left of the screen down to the
 *  center, I want to take a screenshot of the screen and I want to be able
 *  to draw on the screen and outline things with my finger in red and be
 *  able to submit that image along with the report into the Pine box inbox.
 *  If I swipe in from the right side, I want to save a recording and save it
 *  out to the Pine Box recordings folder that I have specified ... If I swipe
 *  from the left corner up to the center, I want to basically bring up a
 *  dialogue window of what just happened ... If I go to the bottom right
 *  corner and I swipe up to the center, I basically want to replay the last
 *  sound effects clip that was played. I also want preferences in the swipe
 *  out on the pine box tablet where I can specify what these behaviors are
 *  for the gestures for each of the hot corners ... be able to also change
 *  these and set these and disable these if I want in the sidebar that
 *  swipes out on the left side for the pine box tablet."
 *
 * The GESTURE lives in the page (pine-views/hot-corners.js): it watches the
 * WebView's own touches, draws the red ink, runs the inspector and the SFX
 * replay. What lives HERE is the part the page cannot do for itself: the
 * preferences, persisted with the rest of the config so they survive a
 * restart, and the one function that changes them - used by the bridge's
 * `hotCornersSet` and by the drawer's switch and spinners alike, so the two
 * roads can never disagree about what was saved or forget to tell the page.
 *
 * THE PAGE IS TOLD, NEVER ASKED. Every change, and every page load, pushes
 * `PineHotCorners.configure({...})` into the WebView. The page may still ask
 * through `pineDesktop.hotCorners()` if it boots late; the answer is the
 * same object.
 */
object HotCorners {

    /** The corners, in the order the drawer lists them. */
    val CORNERS = listOf("tl", "tr", "bl", "br")

    /**
     * What a corner can do, paired with the words the drawer shows for it.
     * The keys are the contract with hot-corners.js; the labels are the
     * operator's own descriptions, in the order they appear in the spinner.
     */
    val CHOICES: List<Pair<String, String>> = listOf(
        "off" to "Off",
        "shot" to "Screenshot and draw",
        "export" to "Export the screen video",
        "inspect" to "Inspect the last line",
        "sfx" to "Replay the last SFX clip",
        "report" to "File a Pine report",
    )

    /**
     * THE COPY THE TOUCH ROAD READS. MainActivity.dispatchTouchEvent runs on
     * every finger-down and cannot suspend on the DataStore; it reads this.
     * Set from the store at start-up and on every change, so it is only
     * ever stale for the few milliseconds between a write and its return.
     */
    @Volatile
    var live: HotCornerPrefs = HotCornerPrefs()
        private set

    /** The object the page receives and the bridge settles with. */
    fun json(prefs: HotCornerPrefs): JSONObject = prefs.toJson()
        /* The ring's hold, in seconds, so the export sheet can offer a
         * slider that ends where the history does. Informational: the
         * ring is sized in ScreenReplay and nothing here can change it. */
        .put("ring", ScreenReplay.HOLD_SECONDS)

    /**
     * The push. `__pineHotCornersConfig` is set FIRST so a hot-corners.js
     * that has not finished defining itself when this lands can still pick
     * the object up when it does, instead of asking the bridge again.
     */
    fun script(prefs: HotCornerPrefs): String =
        "window.__pineHotCornersConfig=" + json(prefs).toString() + ";" +
            "window.PineHotCorners&&PineHotCorners.configure&&" +
            "PineHotCorners.configure(window.__pineHotCornersConfig);"

    /** Read from the store, refresh [live], answer with the page's object. */
    suspend fun read(store: ConfigStore): JSONObject {
        val prefs = store.read().hotCorners
        live = prefs
        return json(prefs)
    }

    /**
     * THE ONE FUNCTION THAT CHANGES THEM.
     *
     * Merges [patch] - any subset of {enabled, tl, tr, bl, br} - into the
     * stored preferences, persists the result, refreshes [live], hands the
     * push script to [push] (the caller owns the WebView and its thread),
     * and returns the merged object for the caller to settle or paint with.
     */
    suspend fun set(store: ConfigStore, patch: JSONObject?, push: (String) -> Unit): JSONObject {
        val cfg = store.write(JSONObject().put("hotCorners", patch ?: JSONObject()))
        live = cfg.hotCorners
        push(script(cfg.hotCorners))
        return json(cfg.hotCorners)
    }

    fun labelOf(action: String): String =
        CHOICES.firstOrNull { it.first == action }?.second ?: action

    fun indexOf(action: String): Int =
        CHOICES.indexOfFirst { it.first == action }.coerceAtLeast(0)
}
