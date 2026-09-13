package com.pinebox.kiosk.feed

import com.pinebox.kiosk.net.StationClient
import com.pinebox.kiosk.net.StationUrls
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.json.JSONObject

/** What every subscriber sees. */
data class FeedState(
    val station: JSONObject? = null,
    val rows: List<FeedRow> = emptyList(),
    /** The line sounding right now, worked out locally between polls. */
    val now: FeedRow? = null,
    /** The station's clock, not the tablet's. */
    val at: Long = 0L,
    val error: String? = null,
) {
    val connected: Boolean get() = station != null && error == null
}

/**
 * ONE poller of /api/dj for the whole app.
 *
 * THE CADENCE IS NOT A GUESS. app.py:155440 states the contract - "the
 * round clock every 250ms, speaking_now every 4s" - and the desktop's own
 * feed (desktop/renderer/sampler-feed.js) implements it: /api/dj is fetched
 * every FOUR SECONDS, and the playhead inside the round is interpolated
 * LOCALLY at 250ms from stream_now, which carries the whole per-turn
 * timeline for exactly this purpose (#772).
 *
 * Polling /api/dj at 250ms would be sixteen times the traffic for the same
 * answer, against a station with a documented history of being starved by
 * chatty clients. Do not shorten POLL_MS.
 *
 * Refcounting is by SharingStarted.WhileSubscribed: the loops start when
 * the first collector arrives and stop five seconds after the last one
 * leaves. That five-second grace is what stops a configuration change
 * (rotation, though the activity locks landscape) tearing the poll down and
 * standing it back up.
 */
class StationFeed(
    private val client: StationClient,
    private val scope: CoroutineScope,
) {

    companion object {
        /** See the class header. Four seconds, by the station's own contract. */
        const val POLL_MS = 4_000L

        /** The local playhead tick. Costs nothing - no network. */
        const val TICK_MS = 250L
    }

    /**
     * server_ms cancels the network trip AND any drift between the tablet's
     * clock and the box's. Without it a round's playhead is wrong by
     * however far apart the two have wandered - and a tablet with no Play
     * Services has no Google time sync to keep it honest, so this matters
     * more here than it does on the desktop.
     */
    @Volatile
    private var skewMs: Long = 0

    private val latest = MutableStateFlow(FeedState())

    private fun clock(): Long = System.currentTimeMillis() + skewMs

    val state: StateFlow<FeedState> = callbackFlow {
        val poll = launch {
            while (isActive) {
                try {
                    val text = client.request("GET", StationUrls.dj(client.config().baseUrl), null)
                    /* No lean=1: it drops stream_now entirely and cuts chat
                     * to 20 rows, so the playhead and the scrollback both go
                     * with it. */
                    val obj = JSONObject(text)
                    val serverMs = obj.optLong("server_ms", 0L)
                    if (serverMs > 0) skewMs = serverMs - System.currentTimeMillis()
                    val at = clock()
                    val rows = StationRows.of(obj, at)
                    latest.value = FeedState(
                        station = obj,
                        rows = rows,
                        now = rows.firstOrNull { it.isPlaying },
                        at = at,
                        error = null,
                    )
                    trySend(latest.value)
                } catch (err: Exception) {
                    /* Keep the last good station object. A terminal that
                     * blanks the whole panel because one poll timed out is
                     * worse than one showing a four-second-old show with a
                     * quiet banner. */
                    latest.value = latest.value.copy(
                        error = err.message ?: err.javaClass.simpleName,
                    )
                    trySend(latest.value)
                }
                delay(POLL_MS)
            }
        }

        val tick = launch {
            while (isActive) {
                delay(TICK_MS)
                val station = latest.value.station ?: continue
                val at = clock()
                val rows = StationRows.of(station, at)
                latest.value = latest.value.copy(
                    rows = rows,
                    now = rows.firstOrNull { it.isPlaying },
                    at = at,
                )
                trySend(latest.value)
            }
        }

        awaitClose {
            poll.cancel()
            tick.cancel()
        }
    }.stateIn(scope, SharingStarted.WhileSubscribed(5_000), FeedState())

    /** The most recent snapshot without subscribing - for one-shot reads. */
    fun snapshot(): FeedState = latest.value
}
