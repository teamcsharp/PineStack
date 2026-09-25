package com.pinebox.kiosk.gallery

import android.content.Context
import android.util.Base64
import androidx.documentfile.provider.DocumentFile
import org.json.JSONArray
import org.json.JSONObject

/**
 * READING THE MPC'S DISK, not just writing to it.
 *
 * "I want to connect the MPC Live 3 to this Pine tab through USB and have it
 *  viewed as a multimedia device or a mass media drive where I can access the
 *  presets and preferences we are creating for the MPC, and then load those up
 *  as pads or presets."
 *
 * UsbTarget is the write half - it puts a kit on the card. This is the read
 * half: list what is on the card, and hand a file back so a kit made ON the
 * MPC (or one we wrote earlier) can come back onto the pads.
 *
 * WHY SAF COVERS BOTH KINDS OF CABLE, and this is the part worth knowing. An
 * MPC in "USB mode" presents its disk as MASS STORAGE; some firmware and some
 * other gear present MTP instead. Those are completely different transports -
 * one is a block device, the other is a file protocol - and an app that went
 * looking for a mount path would work with one and not the other. The Storage
 * Access Framework sits above both: the system's picker lists a mass-storage
 * volume and an MTP device side by side, and a tree URI behaves the same
 * either way. So the operator points at the MPC once, whichever kind it is,
 * and everything after that is identical.
 *
 * WHAT IT WILL NOT DO is mount anything by itself. Android gives an ordinary
 * app no way to mount a USB volume, and a platform signature does not change
 * that - /mnt/media_rw belongs to the storage daemon. The system mounts it,
 * the operator points at it, we read it.
 *
 * CHUNKED ON PURPOSE. A kit is WAVs, and a bank of long grabs is tens of
 * megabytes. Every byte handed to the page crosses the JavaScript bridge as
 * base64 inside an evaluate, so a whole file in one answer is a multi-megabyte
 * string through a channel that was built for JSON. It is read in pieces and
 * assembled on the other side.
 */
object UsbBrowse {

    /** About a megabyte of file per answer, which is ~1.4 MB of base64. */
    const val CHUNK = 1024 * 1024

    private fun root(context: Context): DocumentFile? {
        val tree = UsbTarget.target(context) ?: return null
        return DocumentFile.fromTreeUri(context, tree)
    }

    /** Walk a "a/b/c" path from the chosen disk. Empty path is the disk itself. */
    private fun walk(context: Context, path: String): DocumentFile? {
        var here = root(context) ?: return null
        for (part in path.split('/')) {
            if (part.isBlank()) continue
            here = here.findFile(part) ?: return null
        }
        return here
    }

    /**
     * WHAT IS IN A FOLDER.
     *
     * Folders first and then files, each sorted by name, because that is how a
     * person reads a disk - and because an MPC card has a handful of folders
     * among hundreds of samples, and a single alphabetical list buries them.
     */
    fun list(context: Context, path: String): JSONObject {
        val out = JSONObject().put("path", path)
        val here = walk(context, path)
        if (here == null) {
            return out.put("ok", false)
                .put("detail", if (UsbTarget.target(context) == null)
                    "no disk has been chosen yet"
                else "there is nothing at that path on the disk")
        }
        if (!here.isDirectory) {
            return out.put("ok", false).put("detail", "that is a file, not a folder")
        }
        val folders = JSONArray()
        val files = JSONArray()
        val kids = here.listFiles().sortedBy { (it.name ?: "").lowercase() }
        for (child in kids) {
            val name = child.name ?: continue
            val row = JSONObject()
                .put("name", name)
                .put("dir", child.isDirectory)
                .put("bytes", if (child.isDirectory) 0L else child.length())
                .put("at", child.lastModified())
            if (child.isDirectory) folders.put(row) else files.put(row)
        }
        /* A FOLDER THAT IS A KIT SAYS SO. The operator is looking for kits,
         * not for a file manager, so the one fact that matters - "there is a
         * program in here" - is answered here rather than by making the page
         * list every folder twice to find out. */
        for (i in 0 until folders.length()) {
            val row = folders.getJSONObject(i)
            val name = row.optString("name")
            val inner = here.findFile(name)
            val program = inner?.listFiles()?.firstOrNull {
                (it.name ?: "").endsWith(".xpm", ignoreCase = true)
            }
            if (program != null) row.put("program", program.name)
        }
        return out.put("ok", true).put("folders", folders).put("files", files)
            .put("name", here.name ?: "")
    }

    /**
     * A PIECE OF A FILE, as base64.
     *
     * @return `eof` true when this chunk reaches the end, so the caller knows
     *   to stop without having to compare lengths it may not have been told.
     */
    fun read(context: Context, path: String, offset: Long, want: Int): JSONObject {
        val out = JSONObject().put("path", path).put("offset", offset)
        val file = walk(context, path)
            ?: return out.put("ok", false).put("detail", "no such file on the disk")
        if (file.isDirectory) {
            return out.put("ok", false).put("detail", "that is a folder, not a file")
        }
        val size = file.length()
        val take = want.coerceIn(1, CHUNK)
        return try {
            context.contentResolver.openInputStream(file.uri).use { source ->
                if (source == null) {
                    return out.put("ok", false).put("detail", "it would not open")
                }
                /* skip() may return short and is allowed to - loop until the
                 * offset is genuinely reached, or the read is silently of the
                 * wrong part of the file. */
                var skipped = 0L
                while (skipped < offset) {
                    val moved = source.skip(offset - skipped)
                    if (moved <= 0) break
                    skipped += moved
                }
                if (skipped < offset) {
                    return out.put("ok", false).put("detail", "that file is shorter than that")
                }
                val buffer = ByteArray(take)
                var got = 0
                while (got < take) {
                    val read = source.read(buffer, got, take - got)
                    if (read < 0) break
                    got += read
                }
                out.put("ok", true)
                    .put("bytes", got)
                    .put("size", size)
                    .put("eof", offset + got >= size)
                    .put("base64", Base64.encodeToString(buffer, 0, got, Base64.NO_WRAP))
            }
        } catch (err: Exception) {
            out.put("ok", false)
                .put("detail", err.message ?: err.javaClass.simpleName)
        }
    }
}
