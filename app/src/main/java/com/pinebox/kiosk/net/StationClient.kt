package com.pinebox.kiosk.net

import com.pinebox.kiosk.config.Config
import com.pinebox.kiosk.config.ConfigStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlin.coroutines.suspendCoroutine

/** What the station said when it refused. Carries the HTTP code so a caller
 *  can tell "wrong key" from "the box is down". */
class StationException(
    val code: Int,
    message: String,
) : IOException(message)

/**
 * The one HTTP client in the app.
 *
 * Mirrors desktop/main.js:422 `fetchJson` exactly - same headers, same
 * error extraction (`detail` then `error` then the raw text, which is the
 * order FastAPI's own error shapes come in) - so that a panel calling
 * pineDesktop.get sees the same failures it sees under Electron.
 *
 * The bearer goes on EVERY request even though most read routes on this
 * station answer without one today. Two reasons: the write routes need it,
 * and a route that quietly gains auth later should not take the terminal
 * down with it.
 */
class StationClient(private val configStore: ConfigStore) {

    private val json = "application/json; charset=utf-8".toMediaType()

    /* THE PROBE'S OWN CLIENT, and it is impatient on purpose.
     *
     * Reach asks up to three addresses in a row before the panel can load, so
     * every second a dead road costs is a second of blank screen. Measured
     * with the LAN road pointed at a host that is not there: 15 seconds
     * passed before the tailnet road was even tried, because `http` below
     * retries a failed connection and a 3s connect timeout becomes three of
     * them.
     *
     * A road that cannot answer /healthz in two seconds is not a road worth
     * waiting for - not on a LAN, and not over WireGuard either, where the
     * measured round trip to the same station was 76ms. Real requests keep
     * the patient client; only the question "are you there?" uses this one.
     */
    private val probe: OkHttpClient = OkHttpClient.Builder()
        /* FOUR SECONDS, NOT TWO. Two was measured and was too tight: the
         * first probe pass reported "no station on any road" and the tailnet
         * only answered 5.5s later on the banner's own retry. A tunnel that
         * has just woken has a WireGuard handshake to do before the first
         * byte, and the probe was timing out inside it. Four is still well
         * short of the fifteen seconds the retrying client took, and it
         * leaves room for the handshake that the steady-state 76ms round
         * trip does not show. */
        .connectTimeout(4, TimeUnit.SECONDS)
        .readTimeout(4, TimeUnit.SECONDS)
        .callTimeout(6, TimeUnit.SECONDS)
        /* No retries: Reach is already trying several roads, and a retry
         * here multiplies the wait by roads x attempts. */
        .retryOnConnectionFailure(false)
        .build()

    private val http: OkHttpClient = OkHttpClient.Builder()
        /* Short connect timeout: the station is one hop away on the LAN. If
         * it has not accepted a socket in three seconds it is not there, and
         * the terminal wants to say so rather than hang on a blank screen. */
        .connectTimeout(3, TimeUnit.SECONDS)
        /* Generous read timeout: /api/dj is a large object and some of the
         * station's roads do real work before answering. */
        .readTimeout(20, TimeUnit.SECONDS)
        .writeTimeout(20, TimeUnit.SECONDS)
        .callTimeout(30, TimeUnit.SECONDS)
        /* ONE connection pool, small. This station has a documented history
         * of being starved by chatty clients (desktop/renderer/sampler-feed.js
         * header); a terminal that opens a fresh connection per poll is
         * exactly that kind of client. */
        .connectionPool(okhttp3.ConnectionPool(4, 5, TimeUnit.MINUTES))
        .retryOnConnectionFailure(true)
        .build()

    /* THE SLOW ROADS GET THEIR OWN CLIENT.
     *
     * Twenty seconds is right for /api/dj and wrong for anything that
     * visits a language model. Measured: a spoken "what is playing right
     * now" through /v1/chat/completions came back as
     * "the station refused it: timeout" after twenty seconds, having not
     * failed at all - the station was still writing the answer.
     *
     * These three roads do real generative work before they answer, and
     * each of them is entered from a deliberate operator action, so a long
     * wait is honest rather than a hang: the talk dot is showing "Heard:
     * ..." the whole time. Everything else keeps the short timeout, which
     * is what makes an actually-unreachable station say so quickly. */
    private val patient: OkHttpClient = http.newBuilder()
        .readTimeout(150, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .callTimeout(180, TimeUnit.SECONDS)
        .build()

    /* THE UPLOAD ROAD GETS ITS OWN PATIENCE. A twenty-minute screen replay
     * is tens of megabytes, and the patient client's sixty-second write
     * budget was set for a spoken sentence. Over the tailnet this tablet
     * has been measured well under a megabyte a second; five minutes of
     * writing is room for the worst of those without being forever. */
    private val upload: OkHttpClient = patient.newBuilder()
        .writeTimeout(300, TimeUnit.SECONDS)
        .callTimeout(600, TimeUnit.SECONDS)
        .build()

    private fun clientFor(route: String): OkHttpClient {
        val r = route.lowercase()
        val slow = r.contains("/v1/chat/completions")
            || r.contains("/v1/audio/speech")
            || r.contains("/api/listen/transcribe")
            || r.contains("/api/dj/callin/voice")
        return if (slow) patient else http
    }

    suspend fun config(): Config = configStore.read()

    suspend fun get(route: String): String = request("GET", route, null)

    suspend fun post(route: String, body: String?): String = request("POST", route, body)

    suspend fun put(route: String, body: String?): String = request("PUT", route, body)

    suspend fun delete(route: String, body: String?): String = request("DELETE", route, body)

    /**
     * @param route either a bare route ("/api/dj") or a whole URL. The panel
     *   passes routes; the native feed passes URLs built by [StationUrls].
     * @return the raw response body. Parsing is the caller's business -
     *   the bridge hands the text straight back to JavaScript, which is one
     *   fewer parse/serialise round trip than Electron does.
     */
    suspend fun request(method: String, route: String, body: String?): String {
        val cfg = configStore.read()
        val url = if (route.startsWith("http://") || route.startsWith("https://")) {
            route
        } else {
            Reach.base(cfg) + (if (route.startsWith("/")) route else "/$route")
        }

        val payload: RequestBody? = when {
            body == null && method in setOf("GET", "HEAD") -> null
            // FastAPI routes that take no body still want a JSON object
            // rather than an empty entity on POST/PUT/DELETE.
            body == null -> "{}".toRequestBody(json)
            else -> body.toRequestBody(json)
        }

        val builder = Request.Builder().url(url).method(method, payload)
        builder.header("Accept", "application/json")
        if (payload != null) builder.header("Content-Type", "application/json")
        if (cfg.apiKey.isNotBlank()) builder.header("Authorization", "Bearer " + cfg.apiKey)

        val (code, text) = call(builder.build(), clientFor(url))
        if (code !in 200..299) throw StationException(code, detailOf(text, code))
        return text
    }

    /**
     * POST raw bytes, for the one route whose body is not JSON.
     *
     * `/api/listen/transcribe` takes a WAV as the whole body - audio does
     * not survive a JSON round trip without base64, which would inflate a
     * ten-second clip by a third for no gain. Everything else about the
     * call is identical to [request]: same base, same bearer, same error
     * handling, so a locked-down station refuses this the same way it
     * refuses the rest.
     */
    suspend fun postBytes(route: String, bytes: ByteArray, contentType: String): String {
        val cfg = configStore.read()
        val url = if (route.startsWith("http")) route else {
            Reach.base(cfg) + (if (route.startsWith("/")) route else "/" + route)
        }
        val builder = Request.Builder().url(url)
            .post(bytes.toRequestBody(contentType.toMediaType()))
        builder.header("Accept", "application/json")
        if (cfg.apiKey.isNotBlank()) builder.header("Authorization", "Bearer " + cfg.apiKey)
        val (code, text) = call(builder.build(), clientFor(url))
        if (code !in 200..299) throw StationException(code, detailOf(text, code))
        return text
    }

    /**
     * PUT one FILE as the whole request body, streamed from disk.
     *
     * The export courier's shape. NOT multipart: the station container has
     * no multipart parser, so the file IS the body - Content-Type is the
     * file's own, and anything the station needs to know about it (its
     * name, what it is, how long it runs) rides in the query string. Same
     * base, same bearer, same error extraction as [request]; the body is
     * the difference - `asRequestBody` reads the file as OkHttp writes it,
     * so the bytes are never held on the heap, which is the whole reason a
     * replay is written to a file first.
     *
     * @throws StationException on any non-2xx (a 404 included - the route
     *   may not be built yet), IOException when the box is not there at
     *   all. The caller decides what to tell the operator; see the
     *   bridge's replayExport, where neither may fail the save.
     */
    suspend fun putFile(route: String, file: File, mime: String): String {
        val cfg = configStore.read()
        val url = if (route.startsWith("http")) route else {
            Reach.base(cfg) + (if (route.startsWith("/")) route else "/" + route)
        }
        val builder = Request.Builder().url(url)
            .put(file.asRequestBody(mime.toMediaType()))
        builder.header("Accept", "application/json")
        if (cfg.apiKey.isNotBlank()) builder.header("Authorization", "Bearer " + cfg.apiKey)
        val (code, text) = call(builder.build(), upload)
        if (code !in 200..299) throw StationException(code, detailOf(text, code))
        return text
    }

    /** Stream an editor source without materializing a second copy in the WebView. */
    suspend fun postVideoEditorSource(file: File, audio: JSONObject, name: String): String {
        require(file.length() in 1..VideoEditorContract.SOURCE_LIMIT) { "capture must be between 1 byte and 256 MiB" }
        val cfg = configStore.read()
        val builder = Request.Builder().url(Reach.base(cfg) + VideoEditorContract.SOURCE_ROUTE)
            .post(file.asRequestBody("video/mp4".toMediaType()))
            .header("Accept", "application/json")
            .header("X-Capture-Audio", VideoEditorContract.audioHeader(audio))
            .header("X-Capture-Name", name.replace(Regex("[^ -~]"), " ").take(120))
        if (cfg.apiKey.isNotBlank()) builder.header("Authorization", "Bearer " + cfg.apiKey)
        val (code, text) = call(builder.build(), upload)
        if (code !in 200..299) throw StationException(code, detailOf(text, code))
        return text
    }

    /** Download only a completed editor export, streaming to an owned temporary file. */
    suspend fun getVideoEditorExport(exportId: String, target: File): Long {
        val route = VideoEditorContract.exportFileRoute(exportId)
        val cfg = configStore.read()
        val builder = Request.Builder().url(Reach.base(cfg) + route).get()
        if (cfg.apiKey.isNotBlank()) builder.header("Authorization", "Bearer " + cfg.apiKey)
        return withContext(Dispatchers.IO) {
            upload.newCall(builder.build()).execute().use { answer ->
                if (!answer.isSuccessful) throw StationException(answer.code, "the station said " + answer.code)
                val body = answer.body ?: throw StationException(502, "no edited video came back")
                val limit = 512L * 1024 * 1024
                if (body.contentLength() > limit) throw StationException(413, "edited video exceeds the tablet's 512 MiB download limit")
                var written = 0L
                try {
                    body.byteStream().use { input -> target.outputStream().use { output ->
                        val buffer = ByteArray(64 * 1024)
                        while (true) {
                            val count = input.read(buffer)
                            if (count < 0) break
                            written += count
                            if (written > limit) throw StationException(413, "edited video exceeds the tablet's download limit")
                            output.write(buffer, 0, count)
                        }
                    } }
                    if (written == 0L || (body.contentLength() >= 0 && written != body.contentLength())) {
                        throw StationException(502, "the edited video download was incomplete")
                    }
                    written
                } catch (err: Exception) { target.delete(); throw err }
            }
        }
    }

    /**
     * GET raw bytes - a clip, not JSON.
     *
     * /api/booth/clip answers with audio (mp3 or wav, sniffed from the
     * Content-Type), and the terminal needs the BYTES to put a line on a
     * pad or keep it in a folder. Everything else about the call is the
     * same as [request]: same base, same bearer, so a station that locks
     * its reads refuses this the same way it refuses the rest.
     *
     * @return the bytes and the content type the station declared.
     */
    suspend fun getBytes(route: String): Pair<ByteArray, String> {
        val cfg = configStore.read()
        val url = if (route.startsWith("http")) route else {
            Reach.base(cfg) + (if (route.startsWith("/")) route else "/" + route)
        }
        val builder = Request.Builder().url(url).get()
        if (cfg.apiKey.isNotBlank()) builder.header("Authorization", "Bearer " + cfg.apiKey)
        return withContext(Dispatchers.IO) {
            patient.newCall(builder.build()).execute().use { answer ->
                if (!answer.isSuccessful) {
                    throw StationException(answer.code, "the station said " + answer.code)
                }
                val body = answer.body ?: throw StationException(502, "no clip came back")
                val kind = answer.header("Content-Type") ?: "application/octet-stream"
                Pair(body.bytes(), kind)
            }
        }
    }

    /**
     * Self-provisioning. GET `/` unauthenticated, lift `const SERVER_KEY`
     * out of the panel HTML, save it. Same contract as Electron's
     * discoverAgentKey: `{ok, saved}`.
     */
    suspend fun discoverKey(): JSONObject {
        val cfg = configStore.read()
        val (code, html) = call(Request.Builder().url(Reach.base(cfg) + "/").get().build())
        if (code !in 200..299) throw StationException(code, "$code fetching the panel")
        val key = KeyDiscovery.extract(html)
            ?: return JSONObject().put("ok", false).put("saved", false)
        configStore.putApiKey(key)
        return JSONObject().put("ok", true).put("saved", true)
    }

    /** Does THIS base answer? One short call and no retries: it is asked
     *  about three addresses in a row, and a slow failure on the first would
     *  make the terminal feel broken while it worked its way to the one that
     *  actually works. */
    suspend fun answers(base: String): Boolean = try {
        val (code, body) = call(
            Request.Builder().url(base.trimEnd('/') + "/healthz").get().build(),
            using = probe)
        /* THE STATION'S OWN ANSWER, not merely an answer.
         *
         * This took 200..499 first, inherited from the old reachable() where
         * the question was "is the station I already know about up?" and a
         * 404 from the right box was a fine yes. As a road chooser it is
         * wrong, and the first test proved it: pointed at :8099 - the restart
         * bridge - the terminal announced "station on the LAN" and loaded the
         * panel from a service that only knows /status and /restart.
         *
         * A captive portal is the case that matters: it is what sits between
         * this tablet and the internet on somebody else's wifi, and it
         * answers every request with 200. */
        code == 200 && body.contains("\"status\"") && body.contains("ok")
    } catch (err: Exception) {
        false
    }

    /** Is the station answering at all - on ANY of its roads?
     *
     *  This is the offline banner's question, and it is also where the road
     *  gets chosen. The banner already asks it on a timer and whenever a load
     *  fails, which is exactly when the tablet has moved between the LAN and
     *  the tailnet - so settling here means no second timer and no separate
     *  "the network changed" listener to get wrong. */
    suspend fun reachable(): Boolean {
        val cfg = configStore.read()
        for (road in Reach.candidates(cfg)) {
            if (!answers(road)) continue
            Reach.settle(cfg) { it == road }
            return true
        }
        Reach.forget()
        return false
    }

    private suspend fun call(
        request: Request,
        using: OkHttpClient = http,
    ): Pair<Int, String> =
        withContext(Dispatchers.IO) {
            suspendCoroutine { cont ->
                using.newCall(request).enqueue(object : Callback {
                    override fun onFailure(call: Call, e: IOException) {
                        cont.resumeWithException(e)
                    }

                    override fun onResponse(call: Call, response: Response) {
                        response.use {
                            val text = try {
                                it.body?.string().orEmpty()
                            } catch (err: IOException) {
                                ""
                            }
                            cont.resume(it.code to text)
                        }
                    }
                })
            }
        }

    /** FastAPI's `detail`, the station's `error`, then whatever came back. */
    private fun detailOf(text: String, code: Int): String {
        if (text.isBlank()) return "$code from the station"
        return try {
            val obj = JSONObject(text)
            obj.optString("detail").takeIf { it.isNotBlank() }
                ?: obj.optString("error").takeIf { it.isNotBlank() }
                ?: text.take(300)
        } catch (err: Exception) {
            text.take(300)
        }
    }
}
