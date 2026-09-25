package com.pinebox.kiosk.gallery

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Environment
import android.os.storage.StorageManager
import android.provider.DocumentsContract
import androidx.documentfile.provider.DocumentFile
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * PUTTING A KIT ON THE MPC, OVER THE CABLE.
 *
 * "I want the ability to connect my tablet up to the MPC while the MPC is in
 *  USB mode and transfer templates over to the MPC and place the kits in the
 *  specified location on the SD card for it to be able to open our kits."
 *
 * WHAT "USB MODE" MEANS HERE. An MPC Live/One/X put into USB mode presents
 * its SD card (or internal drive) to the host as an ordinary USB mass storage
 * disk. So the tablet has to be the HOST, which needs an OTG adapter or a
 * USB-C to USB-C cable - a phone-to-phone charging cable will not do it,
 * because something has to supply the bus.
 *
 * WHY THIS GOES THROUGH SAF AND NOT THROUGH A PATH. Android will not let an
 * ordinary app open /mnt/media_rw/<UUID> even with a platform signature -
 * that tree belongs to the external storage daemon, and MANAGE_EXTERNAL_
 * STORAGE does not reach removable USB volumes either. The supported road is
 * the Storage Access Framework: the operator points at the MPC's disk ONCE
 * with the system picker, the grant is persisted across reboots, and every
 * kit after that is written without another prompt.
 *
 * That one-time pick is not a wart, it is the only honest way in - and it is
 * also the moment the operator chooses WHERE on the card the kits land, which
 * is the other half of what was asked for. An MPC browses its whole disk, so
 * any folder works; pointing at `Expansions` makes them show up as an
 * expansion, and pointing at the card root makes them show up in Browse.
 */
object UsbTarget {

    private const val PREFS = "pine-usb"
    private const val KEY_TREE = "tree"
    private const val KEY_NAME = "name"

    /** Where the MPC's disk was last pointed at, or null. */
    fun target(context: Context): Uri? {
        val saved = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(KEY_TREE, null) ?: return null
        val uri = runCatching { Uri.parse(saved) }.getOrNull() ?: return null
        /* A GRANT CAN GO AWAY - the card is unplugged and replaced, the user
         * revokes it, the volume is reformatted. Checked rather than assumed,
         * because the alternative is a write that fails with a permission
         * exception the operator cannot act on. */
        val held = context.contentResolver.persistedUriPermissions.any {
            it.uri == uri && it.isWritePermission
        }
        return if (held) uri else null
    }

    fun remember(context: Context, uri: Uri, name: String) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putString(KEY_TREE, uri.toString())
            .putString(KEY_NAME, name)
            .apply()
    }

    fun targetName(context: Context): String =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(KEY_NAME, "") ?: ""

    /** The intent that asks the operator to point at the MPC's disk. */
    fun pickIntent(): Intent =
        Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).apply {
            addFlags(
                Intent.FLAG_GRANT_READ_URI_PERMISSION or
                    Intent.FLAG_GRANT_WRITE_URI_PERMISSION or
                    Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
            )
        }

    /**
     * WHAT DISKS THE TABLET CAN SEE.
     *
     * Reported so the panel can say "the MPC is not plugged in, or it is not
     * in USB mode" rather than opening a picker onto nothing. A removable
     * volume that is MOUNTED is the MPC (or a memory card); the tablet's own
     * storage is reported too, marked as not removable, because seeing it
     * listed is how the operator knows the question was actually asked.
     */
    fun volumes(context: Context): JSONArray {
        val out = JSONArray()
        val manager = context.getSystemService(Context.STORAGE_SERVICE) as? StorageManager
            ?: return out
        for (volume in runCatching { manager.storageVolumes }.getOrDefault(emptyList())) {
            val row = JSONObject()
                .put("name", runCatching { volume.getDescription(context) }.getOrDefault(""))
                .put("removable", volume.isRemovable)
                .put("primary", volume.isPrimary)
                .put("state", runCatching { volume.state }.getOrDefault("unknown"))
            runCatching { volume.directory?.absolutePath }.getOrNull()?.let {
                row.put("path", it)
            }
            out.put(row)
        }
        return out
    }

    /** Is anything that could be an MPC actually attached right now? */
    fun anyRemovable(context: Context): Boolean {
        val list = volumes(context)
        for (i in 0 until list.length()) {
            val row = list.optJSONObject(i) ?: continue
            if (row.optBoolean("removable") &&
                row.optString("state") == Environment.MEDIA_MOUNTED
            ) return true
        }
        return false
    }

    data class Sent(val ok: Boolean, val files: Int, val bytes: Long,
                    val where: String, val detail: String = "")

    /**
     * COPY A KIT FOLDER ONTO THE TARGET DISK.
     *
     * @param from the folder under Downloads the exporter already wrote
     * @param into the name the folder should have on the MPC's disk
     *
     * The kit is copied rather than re-generated: it has already been built
     * and verified on local storage, and building it twice is two chances to
     * differ. An existing folder of the same name is REPLACED file by file
     * rather than deleted first - a half-deleted kit on a card the operator
     * is about to unplug is worse than a mixed one.
     */
    fun sendFolder(context: Context, from: File, into: String): Sent {
        val tree = target(context)
            ?: return Sent(false, 0, 0, "", "no MPC disk has been chosen yet")
        if (!from.isDirectory) {
            return Sent(false, 0, 0, "", "there is no kit at " + from.absolutePath)
        }
        val root = DocumentFile.fromTreeUri(context, tree)
            ?: return Sent(false, 0, 0, "", "that disk is no longer reachable")
        if (!root.canWrite()) {
            return Sent(false, 0, 0, "", "that disk is mounted read-only")
        }
        val folder = root.findFile(into)?.takeIf { it.isDirectory }
            ?: root.createDirectory(into)
            ?: return Sent(false, 0, 0, "", "could not make a folder on that disk")

        var files = 0
        var bytes = 0L
        for (file in from.listFiles().orEmpty().sortedBy { it.name }) {
            if (!file.isFile) continue
            folder.findFile(file.name)?.delete()
            /* octet-stream for everything, deliberately: a provider that
             * "corrects" an extension to match a MIME type is exactly how the
             * program file became <name>.xpm.xml on local storage, and an MPC
             * browses for .xpm. */
            val made = folder.createFile("application/octet-stream", file.name)
                ?: return Sent(false, files, bytes, folder.name ?: into,
                    "could not create " + file.name + " on that disk")
            val wrote = runCatching {
                context.contentResolver.openOutputStream(made.uri)?.use { sink ->
                    file.inputStream().use { source -> source.copyTo(sink) }
                } ?: 0L
            }.getOrElse {
                return Sent(false, files, bytes, folder.name ?: into,
                    "writing " + file.name + " failed: " + (it.message ?: it.javaClass.simpleName))
            }
            files += 1
            bytes += wrote
        }
        return Sent(true, files, bytes, describe(context, tree, into))
    }

    /* A path a person can act on, rather than a content:// URI nobody can
     * read. Best effort - SAF does not promise a real path exists. */
    private fun describe(context: Context, tree: Uri, folder: String): String {
        val id = runCatching { DocumentsContract.getTreeDocumentId(tree) }.getOrNull()
        val disk = targetName(context).ifBlank { id ?: "the chosen disk" }
        return disk.trimEnd(':') + "/" + folder
    }
}
