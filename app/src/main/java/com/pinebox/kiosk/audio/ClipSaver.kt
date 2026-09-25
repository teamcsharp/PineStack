package com.pinebox.kiosk.audio

import android.content.ContentValues
import android.content.Context
import android.os.Environment
import android.provider.MediaStore
import android.util.Log
import java.io.File
import java.io.OutputStream

/**
 * KEEPING A LINE.
 *
 * "If I want to download it to the tablet, if I want to download it to the
 * local recording folder where I'm extracting things."
 *
 * Two destinations, deliberately different in kind:
 *
 *   DOWNLOADS   the tablet's own Downloads/Pine Box folder. Visible to
 *               every file app and to a USB cable, which is what "download
 *               it to the tablet" means to somebody who wants to find it
 *               later without this app's help.
 *   RECORDINGS  a named working folder for the material being extracted.
 *               Which folder that is belongs to the OPERATOR, not to this
 *               file, so it is read from the terminal's config and only
 *               falls back to a sensible default - and whatever it writes,
 *               it answers with the full path so there is never any doubt
 *               about where a clip went.
 *
 * WHY MEDIASTORE AND NOT A FILE PATH. Android 10 ended an app's freedom to
 * write wherever it likes on shared storage, and this app holds no storage
 * permission at all. MediaStore is the road that needs none: the system
 * owns the file, the app is handed a stream to fill, and the result is a
 * real entry the file manager can see. A direct File() write into
 * /storage/emulated/0 would fail on this tablet, silently on some builds.
 */
object ClipSaver {

    /** Where a clip went, or why it did not. */
    data class Kept(val ok: Boolean, val where: String, val bytes: Int,
                    val detail: String = "")

    private const val TAG = "PineClip"

    /**
     * Write bytes into shared storage under a folder.
     *
     * @param folder relative to the collection, e.g. "Pine Box" - the
     *   operator's own folder name arrives here from the config.
     */
    fun keep(
        context: Context,
        bytes: ByteArray,
        name: String,
        folder: String,
        mime: String,
    ): Kept {
        if (bytes.isEmpty()) return Kept(false, "", 0, "there was nothing to save")
        return write(context, name, folder, mime, bytes.size.toLong()) { it.write(bytes) }
    }

    /**
     * KEEP A FILE, STREAMED - the video sibling of [keep].
     *
     * "If I swipe in from the right side, I want to save a recording and
     *  save it out to the Pine Box recordings folder that I have specified."
     *
     * A twenty-minute screen replay is tens of megabytes, and [keep] takes a
     * ByteArray - reading a file that size into one to hand it over would
     * put a second copy of the ring on a heap that already carries the ring.
     * So the file is copied into the MediaStore stream in 64 kB pieces and
     * never sits in memory whole. The destination is the one every other
     * keep uses, Download/<folder>, so a screen video lands beside the clips
     * and presets the operator already looks for there.
     */
    fun keepFile(
        context: Context,
        file: File,
        name: String,
        folder: String,
        mime: String,
    ): Kept {
        val size = if (file.exists()) file.length() else 0L
        if (size <= 0L) return Kept(false, "", 0, "there was nothing to save")
        return write(context, name, folder, mime, size) { out ->
            file.inputStream().use { it.copyTo(out, 64 * 1024) }
        }
    }

    /** The one MediaStore road under both keeps: open, fill, publish. */
    private fun write(
        context: Context,
        name: String,
        folder: String,
        mime: String,
        size: Long,
        fill: (OutputStream) -> Unit,
    ): Kept {
        val safe = safeName(name)
        val relative = Environment.DIRECTORY_DOWNLOADS +
            (if (folder.isBlank()) "" else File.separator + folder.trim('/'))

        return try {
            val values = ContentValues().apply {
                put(MediaStore.MediaColumns.DISPLAY_NAME, safe)
                put(MediaStore.MediaColumns.MIME_TYPE, mime)
                put(MediaStore.MediaColumns.RELATIVE_PATH, relative)
                /* IS_PENDING keeps it invisible until it is complete, so a
                 * half-written clip is never picked up by anything else. */
                put(MediaStore.MediaColumns.IS_PENDING, 1)
            }
            val resolver = context.contentResolver
            val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                ?: return Kept(false, "", 0, "the system would not open a file there")

            resolver.openOutputStream(uri)?.use { fill(it) }
                ?: return Kept(false, "", 0, "the file opened but could not be written")

            values.clear()
            values.put(MediaStore.MediaColumns.IS_PENDING, 0)
            resolver.update(uri, values, null, null)

            val shown = relative + File.separator + safe
            Log.i(TAG, "kept $size bytes at $shown")
            Kept(true, shown, size.coerceAtMost(Int.MAX_VALUE.toLong()).toInt())
        } catch (err: Exception) {
            Log.w(TAG, "could not keep the clip", err)
            Kept(false, "", 0, err.message ?: err.javaClass.simpleName)
        }
    }

    /**
     * A filename a file system will accept, built from what the line SAYS.
     *
     * The operator is going to look for this in a folder later, and
     * "clip-4f8a2b.mp3" tells him nothing about which line it was. The
     * first few words do.
     */
    fun nameFor(said: String, id: String, ext: String): String {
        val words = said.trim().split(Regex("\\s+")).take(7).joinToString(" ")
        val stem = if (words.isBlank()) "pine box line" else words
        val tail = if (id.length >= 6) id.take(6) else id
        return safeName("$stem ($tail).$ext")
    }

    private fun safeName(raw: String): String {
        val cleaned = raw
            .replace(Regex("[\\\\/:*?\"<>|\\x00-\\x1f]"), " ")
            .replace(Regex("\\s+"), " ")
            .trim()
        val capped = if (cleaned.length > 120) cleaned.take(120) else cleaned
        return if (capped.isBlank()) "pine box clip" else capped
    }
}
