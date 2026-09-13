package com.pinebox.kiosk.net

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.Log
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import okhttp3.Dispatcher
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.security.MessageDigest
import java.util.concurrent.Executors
import java.util.concurrent.Semaphore
import java.util.concurrent.TimeUnit

/**
 * The panel's network, taken off the WebView's six sockets.
 *
 * WHY THIS EXISTS - measured on the real tablet over the devtools socket,
 * 2026-09-10, before any of this was written:
 *
 *   - The panel renders ~180 <img> elements whose src is
 *     /api/generations/image/<name>.png. Every one of those is the FULL
 *     ComfyUI render: 1024x1024, 1.14-1.39 MB of PNG. Most are drawn at
 *     34-120 CSS px. The first 250 resource-timing entries alone accounted
 *     for 239 MB of image traffic.
 *   - The station is HTTP/1.1 (uvicorn, no h2, no gzip anywhere), so
 *     Chromium opens SIX sockets to it and everything else queues behind
 *     those PNGs. Measured: an 814-byte /api/music/stations took 13.6 s and
 *     /api/dj took 15.2 s, purely from queueing.
 *   - With the panel warm the queue does not drain. A probe watched the
 *     in-flight count climb 23 -> 43 -> 62 -> 83 -> 98 -> 114 -> 131 -> 153
 *     over 55 s, all still awaiting response HEADERS.
 *   - That is why a 3JS view "does not come up". djGraphPanel() and its
 *     siblings need the GLOBAL window.THREE, which only the classic
 *     /vendor/three.min.js defines, so the first click injects a <script>
 *     for it and returns. On the tablet that script tag fired neither
 *     onload nor onerror in THREE MINUTES - it never reached the front of
 *     the queue. The same file fetched from the desktop at the same moment
 *     took 1.26 s. The station was never the problem; the queue was.
 *
 * So: take the two offenders out of Chromium's socket pool entirely.
 *
 *   /vendor/<name>                    -> served from the APK. Zero network, and
 *                                   immune to the queue by construction.
 *   /api/generations/image/<name>     -> fetched on our own bounded lane, then
 *                                   transcoded to 768px WebP and kept on
 *                                   disk. Measured 24-31x smaller
 *                                   (1.20 MB -> 38 kB, 1.44 MB -> 60 kB).
 *
 * Everything else returns null and goes through the WebView untouched.
 * That is deliberate. Media (/media/<key>.wav) needs Range requests for
 * seeking, POSTs carry the operator's actions, and the panel's SSE-ish
 * polls want the WebView's own connection reuse. None of that is worth the
 * risk when the whole measured cost sits in those two prefixes.
 */
object PineNet {

    private const val TAG = "PineNet"

    /** The screen is 1340x800 and the panel lays out at 1000 CSS px. A
     *  lightbox tops out near 510 device px, so 768 is already generous;
     *  it leaves room for a pinch-zoom without carrying 1024x1024. */
    private const val MAX_EDGE = 768
    private const val WEBP_QUALITY = 80

    /** Four at a time. This bounds the wire AND the transcode: a MT6768
     *  decoding a 1024x1024 PNG and re-encoding WebP is ~200 ms of CPU, and
     *  letting 150 of those run at once would trade one stall for another.
     *  The station also stops being hammered by a wall of 180 requests. */
    private const val LANES = 4

    /** 5000-odd transcoded pictures at ~50 kB. /data has 47 GB free, and
     *  the WebView's own HTTP cache had grown to 114 MB against a 240 MB
     *  working set - which is exactly why it never hit. This one is bigger
     *  than the working set, which is the whole point. */
    private const val CACHE_BUDGET_BYTES = 256L * 1024 * 1024

    private val VENDOR = setOf("three.min.js", "three.module.js", "three.core.js")

    @Volatile private var appContext: Context? = null
    @Volatile private var imageDir: File? = null
    @Volatile private var vendorOverrideDir: File? = null

    /** Where the panel actually came from. Taken from the first request we
     *  intercept rather than from BuildConfig, because the bridge's
     *  writeConfig can move the station at runtime and a hard-coded host
     *  would quietly check the wrong box. */
    @Volatile private var origin: String? = null
    @Volatile private var vendorChecked = false

    private val lanes = Semaphore(LANES, true)

    private val http: OkHttpClient by lazy {
        val d = Dispatcher(Executors.newCachedThreadPool())
        /* Higher than Chromium's six on purpose: these requests no longer
         * share a queue with the panel's API calls, so widening the lane
         * only helps the pictures and cannot starve anything else. The real
         * limiter is `lanes` above. */
        d.maxRequests = 16
        d.maxRequestsPerHost = 16
        OkHttpClient.Builder()
            .dispatcher(d)
            .retryOnConnectionFailure(true)
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .callTimeout(90, TimeUnit.SECONDS)
            .build()
    }

    /** Call once, early, from the activity. Cheap: it only makes dirs and
     *  kicks a single background trim + vendor freshness check. */
    fun install(context: Context) {
        if (appContext != null) return
        val ctx = context.applicationContext
        appContext = ctx
        imageDir = File(ctx.cacheDir, "pineimg").apply { mkdirs() }
        vendorOverrideDir = File(ctx.filesDir, "vendor").apply { mkdirs() }
        Thread({
            try { trimCache() } catch (e: Throwable) { Log.w(TAG, "trim: $e") }
        }, "pinenet-housekeeping").apply { isDaemon = true }.start()
    }

    /**
     * The WebViewClient hook. Returns null for everything it does not own,
     * which is the overwhelming majority of requests.
     *
     * NOTE ON THREADING: this must not block. WebView calls it off the
     * request path and a slow answer here delays other requests, so the
     * response it returns carries a LAZY stream - nothing is fetched,
     * decoded or written until WebView actually reads the body, and that
     * read happens on WebView's own reader thread, not this one.
     */
    fun intercept(request: WebResourceRequest): WebResourceResponse? {
        if (appContext == null) return null
        if (!"GET".equals(request.method, ignoreCase = true)) return null
        val url = request.url ?: return null
        val path = url.path ?: return null

        if (origin == null && url.scheme != null && url.authority != null) {
            origin = url.scheme + "://" + url.authority
        }

        if (path.startsWith("/vendor/")) {
            if (!vendorChecked) {
                vendorChecked = true
                Thread({
                    try { refreshVendor() } catch (e: Throwable) { Log.w(TAG, "vendor check: $e") }
                }, "pinenet-vendor").apply { isDaemon = true }.start()
            }
            val name = path.substringAfterLast('/')
            if (name in VENDOR) return vendorResponse(name)
            return null
        }

        if (path.startsWith("/api/generations/image/")) {
            val headers = request.requestHeaders ?: emptyMap()
            return imageResponse(url.toString(), headers)
        }

        return null
    }

    /* ------------------------------------------------------------------ */
    /* /vendor/<name>                                                           */
    /* ------------------------------------------------------------------ */

    private fun vendorResponse(name: String): WebResourceResponse? {
        val ctx = appContext ?: return null
        val stream: InputStream = try {
            val override = File(vendorOverrideDir, name)
            if (override.isFile && override.length() > 0) override.inputStream()
            else ctx.assets.open("vendor/$name")
        } catch (e: IOException) {
            Log.w(TAG, "vendor $name not shipped: $e")
            return null   // let the station serve it after all
        }
        /* three.module.js does `from './three.core.js'`, which resolves to
         * /vendor/three.core.js and comes straight back through here. Both
         * halves are in the APK, so the module graph never touches the
         * network. */
        return WebResourceResponse(
            "text/javascript", "utf-8", 200, "OK",
            mapOf(
                "Cache-Control" to "public, max-age=31536000, immutable",
                "Access-Control-Allow-Origin" to "*",
                "X-Pine-Source" to "apk",
            ),
            stream,
        )
    }

    /**
     * Keep the shipped copies honest.
     *
     * The station can redeploy a different three.js under us, and an APK
     * that silently pins an old one is a debugging trap nobody would find.
     * So once per process: ask the station how big each file is now, and if
     * it disagrees with what we ship, pull it down into filesDir - which
     * vendorResponse prefers from then on. Still no network on the hot
     * path; the check runs on a daemon thread at startup.
     */
    private fun refreshVendor() {
        val ctx = appContext ?: return
        val base = origin ?: return
        for (name in VENDOR) {
            /* Counted, not available(): AGP deflates assets, so
             * available() on an asset stream is the size of what is left in
             * the inflate buffer and not the size of the file. Getting that
             * wrong would make every check report a mismatch and re-pull
             * 2.6 MB on every launch. */
            val shipped = try {
                ctx.assets.open("vendor/$name").use { input ->
                    var n = 0L
                    val buf = ByteArray(64 * 1024)
                    while (true) {
                        val r = input.read(buf)
                        if (r < 0) break
                        n += r
                    }
                    n
                }
            } catch (e: IOException) { -1L }
            val override = File(vendorOverrideDir, name)
            val local = if (override.isFile) override.length() else shipped
            if (local <= 0) continue
            try {
                val head = Request.Builder().url("$base/vendor/$name").head().build()
                val remote = http.newCall(head).execute().use { r ->
                    if (!r.isSuccessful) return@use -1L
                    r.header("content-length")?.toLongOrNull() ?: -1L
                }
                if (remote <= 0 || remote == local) continue
                Log.i(TAG, "vendor $name changed on the station ($local -> $remote); pulling")
                val get = Request.Builder().url("$base/vendor/$name").build()
                http.newCall(get).execute().use { r ->
                    val body = r.body ?: return@use
                    if (!r.isSuccessful) return@use
                    val tmp = File(vendorOverrideDir, "$name.tmp")
                    tmp.outputStream().use { out -> body.byteStream().copyTo(out) }
                    if (tmp.length() > 0) tmp.renameTo(override) else tmp.delete()
                }
            } catch (e: Exception) {
                Log.w(TAG, "vendor $name check failed (keeping the APK copy): $e")
            }
        }
    }

    /* ------------------------------------------------------------------ */
    /* /api/generations/image/<name>                                            */
    /* ------------------------------------------------------------------ */

    private fun imageResponse(url: String, headers: Map<String, String>): WebResourceResponse {
        val key = File(imageDir, sha1(url) + ".webp")
        return WebResourceResponse(
            "image/webp", null, 200, "OK",
            mapOf(
                "Cache-Control" to "private, max-age=86400",
                "Access-Control-Allow-Origin" to "*",
                "X-Pine-Source" to "pinenet",
            ),
            LazyImageStream(url, key, headers),
        )
    }

    /**
     * Nothing happens until WebView reads. On the first read this either
     * hands back the transcoded file it already has, or takes a lane,
     * fetches, shrinks and stores one.
     */
    private class LazyImageStream(
        private val url: String,
        private val key: File,
        private val headers: Map<String, String>,
    ) : InputStream() {

        private var delegate: InputStream? = null

        private fun open(): InputStream {
            delegate?.let { return it }
            val s = produce()
            delegate = s
            return s
        }

        private fun produce(): InputStream {
            if (key.isFile && key.length() > 0) {
                key.setLastModified(System.currentTimeMillis())   // LRU touch
                return key.inputStream()
            }
            lanes.acquire()
            try {
                if (key.isFile && key.length() > 0) return key.inputStream()
                val b = Request.Builder().url(url)
                for ((k, v) in headers) {
                    /* Forward what the page sent - imageURL() carries a
                     * Bearer key - but never the ones that describe a
                     * connection we are not making. */
                    if (k.equals("Accept-Encoding", true)) continue
                    if (k.equals("Connection", true)) continue
                    if (k.equals("Host", true)) continue
                    try { b.header(k, v) } catch (e: IllegalArgumentException) { /* skip junk */ }
                }
                b.header("Accept", "image/png,image/*,*/*")
                val raw: ByteArray = http.newCall(b.build()).execute().use { r ->
                    val body = r.body ?: throw IOException("no body: $url")
                    if (!r.isSuccessful) throw IOException("HTTP ${r.code} for $url")
                    body.bytes()
                }
                val small = shrink(raw)
                if (small == null) {
                    /* Not a picture we can decode (a 404 page, an SVG, a
                     * format the platform does not know). Hand back exactly
                     * what the station said and do not poison the cache. */
                    return ByteArrayInputStream(raw)
                }
                val tmp = File(key.parentFile, key.name + ".tmp")
                try {
                    tmp.writeBytes(small)
                    if (!tmp.renameTo(key)) tmp.delete()
                } catch (e: IOException) {
                    tmp.delete()
                }
                return ByteArrayInputStream(small)
            } finally {
                lanes.release()
            }
        }

        /** 1024x1024 PNG -> 768px WebP. Measured 24-31x on the station's
         *  own renders. Returns null if the bytes are not a bitmap. */
        private fun shrink(raw: ByteArray): ByteArray? {
            val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeByteArray(raw, 0, raw.size, bounds)
            val w = bounds.outWidth
            val h = bounds.outHeight
            if (w <= 0 || h <= 0) return null
            if (w <= MAX_EDGE && h <= MAX_EDGE && raw.size < 96 * 1024) return null  // already small

            /* inSampleSize first so the full-size bitmap never exists: a
             * 1024x1024 ARGB decode is 4 MB, and 150 of those is what was
             * printing "tile memory limits exceeded" in logcat. */
            var sample = 1
            while (w / (sample * 2) >= MAX_EDGE && h / (sample * 2) >= MAX_EDGE) sample *= 2
            val opts = BitmapFactory.Options().apply { inSampleSize = sample }
            val decoded = BitmapFactory.decodeByteArray(raw, 0, raw.size, opts) ?: return null
            val scaled = try {
                val longest = maxOf(decoded.width, decoded.height)
                if (longest <= MAX_EDGE) decoded
                else {
                    val f = MAX_EDGE.toFloat() / longest
                    Bitmap.createScaledBitmap(
                        decoded,
                        maxOf(1, (decoded.width * f).toInt()),
                        maxOf(1, (decoded.height * f).toInt()),
                        true,
                    ).also { if (it !== decoded) decoded.recycle() }
                }
            } catch (e: OutOfMemoryError) {
                decoded.recycle(); return null
            }
            val out = ByteArrayOutputStream(64 * 1024)
            val ok = try {
                scaled.compress(Bitmap.CompressFormat.WEBP_LOSSY, WEBP_QUALITY, out)
            } catch (e: Throwable) {
                false
            } finally {
                scaled.recycle()
            }
            return if (ok && out.size() > 0) out.toByteArray() else null
        }

        override fun read(): Int = open().read()
        override fun read(b: ByteArray, off: Int, len: Int): Int = open().read(b, off, len)
        override fun available(): Int = delegate?.available() ?: 1
        override fun close() { try { delegate?.close() } catch (e: IOException) {} }
    }

    /* ------------------------------------------------------------------ */

    private fun trimCache() {
        val dir = imageDir ?: return
        val files = dir.listFiles() ?: return
        var total = files.sumOf { it.length() }
        if (total <= CACHE_BUDGET_BYTES) return
        files.sortedBy { it.lastModified() }.forEach { f ->
            if (total <= CACHE_BUDGET_BYTES) return
            total -= f.length()
            f.delete()
        }
    }

    private fun sha1(s: String): String {
        val d = MessageDigest.getInstance("SHA-1").digest(s.toByteArray())
        val sb = StringBuilder(40)
        for (b in d) sb.append("%02x".format(b))
        return sb.toString()
    }
}
