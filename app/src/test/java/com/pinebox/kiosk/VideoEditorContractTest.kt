package com.pinebox.kiosk

import com.pinebox.kiosk.net.VideoEditorContract
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class VideoEditorContractTest {
    private val id = "0123456789abcdef0123456789abcdef"

    @Test fun `only registered identities select station editor routes`() {
        assertEquals("/video-editor/?source=$id", VideoEditorContract.editorPath(id))
        assertEquals("/api/video-editor/exports/$id/file", VideoEditorContract.exportFileRoute(id))
        for (bad in listOf("", "../secret", "https://other.invalid/file", "$id?name=x", id.uppercase(), "$id\n")) {
            assertThrows(IllegalArgumentException::class.java) { VideoEditorContract.exportFileRoute(bad) }
        }
    }

    @Test fun `capture header preserves Unicode details without raw header controls`() {
        val source = JSONObject().put("source", "android-playback-mix")
            .put("detail", "Capture unavailable \u2014 \u00e9\nsecond line\r\nheader: value")
            .put("present", false).put("coverage_ratio", 0.0)
        val header = VideoEditorContract.audioHeader(source)
        assertTrue(header.all { it.code in 32..126 })
        val restored = JSONObject(header)
        assertEquals(source.getString("detail"), restored.getString("detail"))
        assertFalse(restored.getBoolean("present"))
        assertEquals(0.0, restored.getDouble("coverage_ratio"), 0.0)
    }
}
