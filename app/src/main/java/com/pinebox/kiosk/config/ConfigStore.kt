package com.pinebox.kiosk.config

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import org.json.JSONObject

/* One file, one process, and the whole config is six small fields - so
 * Preferences DataStore rather than Proto. The name mirrors Electron's
 * pinebox-desktop.json so the two shells are recognisably the same app. */
private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "pinebox-desktop")

/**
 * Reads and writes [Config].
 *
 * Everything here is suspending. The bridge calls it from a coroutine, and
 * the deliberate absence of a blocking read is what stops someone hanging
 * the WebView's JavaBridge thread on disk I/O.
 */
class ConfigStore(private val context: Context) {

    private object Keys {
        val baseUrl = stringPreferencesKey("baseUrl")
        val apiKey = stringPreferencesKey("apiKey")
        val mode = stringPreferencesKey("mode")
        val port = intPreferencesKey("port")
        val dataDir = stringPreferencesKey("dataDir")
        val python = stringPreferencesKey("python")
        /* THE ROADS TO THE STATION, so a tailnet address can be moved without
         * a new build - see net/Reach.kt. */
        val tailnetUrl = stringPreferencesKey("tailnetUrl")
        val tailnetName = stringPreferencesKey("tailnetName")
        /* AND THE OPERATOR'S OWN FOLDER, which was declared on Config from the
         * day it was added and never written here - so "download it to the
         * local recording folder where I'm extracting things" has never
         * survived a restart. The same omission as the two above. */
        val recordingFolder = stringPreferencesKey("recordingFolder")
        /* THE HOT CORNERS - see config/HotCorners.kt. Five keys rather than
         * one JSON blob, so a corner added later is one line here and not a
         * migration, and so a bad value in one corner cannot take the other
         * three with it. */
        val hotCornersOn = booleanPreferencesKey("hotCornersOn")
        val hotCornerTl = stringPreferencesKey("hotCornerTl")
        val hotCornerTr = stringPreferencesKey("hotCornerTr")
        val hotCornerBl = stringPreferencesKey("hotCornerBl")
        val hotCornerBr = stringPreferencesKey("hotCornerBr")
    }

    val flow: Flow<Config> = context.dataStore.data.map { prefs ->
        val fallback = Config()
        Config(
            baseUrl = prefs[Keys.baseUrl]?.takeIf { it.isNotBlank() } ?: fallback.baseUrl,
            apiKey = prefs[Keys.apiKey] ?: fallback.apiKey,
            mode = prefs[Keys.mode]?.takeIf { it.isNotBlank() } ?: fallback.mode,
            port = prefs[Keys.port] ?: fallback.port,
            dataDir = prefs[Keys.dataDir] ?: fallback.dataDir,
            python = prefs[Keys.python] ?: fallback.python,
            tailnetUrl = prefs[Keys.tailnetUrl]?.takeIf { it.isNotBlank() }
                ?: fallback.tailnetUrl,
            tailnetName = prefs[Keys.tailnetName]?.takeIf { it.isNotBlank() }
                ?: fallback.tailnetName,
            recordingFolder = prefs[Keys.recordingFolder]?.takeIf { it.isNotBlank() }
                ?: fallback.recordingFolder,
            hotCorners = HotCornerPrefs(
                enabled = prefs[Keys.hotCornersOn] ?: fallback.hotCorners.enabled,
                tl = prefs[Keys.hotCornerTl]?.takeIf { it in HotCornerPrefs.ACTIONS }
                    ?: fallback.hotCorners.tl,
                tr = prefs[Keys.hotCornerTr]?.takeIf { it in HotCornerPrefs.ACTIONS }
                    ?: fallback.hotCorners.tr,
                bl = prefs[Keys.hotCornerBl]?.takeIf { it in HotCornerPrefs.ACTIONS }
                    ?: fallback.hotCorners.bl,
                br = prefs[Keys.hotCornerBr]?.takeIf { it in HotCornerPrefs.ACTIONS }
                    ?: fallback.hotCorners.br,
            ),
        )
    }

    suspend fun read(): Config = flow.first()

    /** Merge a patch in and return the result, as Electron's writeConfig does. */
    suspend fun write(patch: JSONObject?): Config {
        val next = read().merged(patch)
        context.dataStore.edit { prefs ->
            prefs[Keys.baseUrl] = next.baseUrl
            prefs[Keys.apiKey] = next.apiKey
            prefs[Keys.mode] = next.mode
            prefs[Keys.port] = next.port
            prefs[Keys.dataDir] = next.dataDir
            prefs[Keys.python] = next.python
            prefs[Keys.tailnetUrl] = next.tailnetUrl
            prefs[Keys.tailnetName] = next.tailnetName
            prefs[Keys.recordingFolder] = next.recordingFolder
            prefs[Keys.hotCornersOn] = next.hotCorners.enabled
            prefs[Keys.hotCornerTl] = next.hotCorners.tl
            prefs[Keys.hotCornerTr] = next.hotCorners.tr
            prefs[Keys.hotCornerBl] = next.hotCorners.bl
            prefs[Keys.hotCornerBr] = next.hotCorners.br
        }
        return next
    }

    /** Used by key self-provisioning, which only ever sets the one field. */
    suspend fun putApiKey(key: String): Config =
        write(JSONObject().put("apiKey", key))
}
