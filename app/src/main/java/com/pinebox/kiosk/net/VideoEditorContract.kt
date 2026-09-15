package com.pinebox.kiosk.net

import org.json.JSONObject

/** Only station-owned identities cross the capture/editor bridge. */
object VideoEditorContract {
    const val SOURCE_ROUTE = "/api/video-editor/sources"
    const val SOURCE_LIMIT = 256L * 1024 * 1024

    fun identity(value: String): String {
        require(Regex("^[0-9a-f]{32}$").matches(value)) { "invalid video editor identity" }
        return value
    }

    fun editorPath(id: String) = "/video-editor/?source=${identity(id)}"
    fun exportRoute(id: String) = "/api/video-editor/exports/${identity(id)}"
    fun exportFileRoute(id: String) = exportRoute(id) + "/file"

    /** OkHttp requires ASCII headers. JSON escapes preserve Unicode errors
     * and device details without permitting control characters in a header. */
    fun audioHeader(audio: JSONObject): String = buildString {
        for (character in audio.toString()) {
            if (character.code in 32..126) append(character)
            else append("\\u").append(character.code.toString(16).padStart(4, '0'))
        }
    }
}
