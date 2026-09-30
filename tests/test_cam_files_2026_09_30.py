"""[cam-files] File management's Pine Cam videos: storage, delete, cache clear,
and the section in the popup that uses them."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "app.py").read_text(encoding="utf-8")
JS = (ROOT / "desktop" / "renderer" / "filemgr.js").read_text(encoding="utf-8")
CSS = (ROOT / "desktop" / "renderer" / "filemgr.css").read_text(encoding="utf-8")


def _body(name: str) -> str:
    at = SRC.index("def %s(" % name)
    nxt = re.compile(r"^(?:def |async def |@app\.)", re.M).search(SRC, at + 10)
    return SRC[at:nxt.start() if nxt else len(SRC)]


class TheRoads(unittest.TestCase):
    def test_routes(self):
        for route in ('@app.get("/api/pinecam/storage")', '@app.post("/api/pinecam/delete")',
                      '@app.post("/api/pinecam/clear-cache")'):
            self.assertIn(route, SRC)

    def test_the_cache_is_only_what_the_footage_makes_again(self):
        body = _body("pinecam_cache_files")
        self.assertIn('not n.startswith("h3_")', body)            # a pinned H3 reference stays
        self.assertIn('n.startswith(("cut_", "list_"))', body)     # album cuts stay
        self.assertNotIn("pinelink_clips_dir", body)               # never the footage

    def test_delete_spares_the_segment_being_recorded(self):
        body = _body("pinecam_delete")
        self.assertIn("still being recorded", body)
        self.assertIn("pinecam_path_of(name)", body)               # the name is checked, never a path


class ThePopup(unittest.TestCase):
    def test_the_section_uses_the_roads(self):
        for road in ("/api/pinecam/storage", "/api/pinecam/recordings", "/api/pinecam/export",
                     "/api/pinecam/delete", "/api/pinecam/clear-cache", "/api/pinecam/thumb/"):
            self.assertIn(road, JS)
        self.assertIn("'Pine Cam videos'", JS)
        self.assertIn("loadCam(ui.camOpen);", JS)

    def test_deletes_are_holds_and_the_player_closes(self):
        self.assertIn("'Hold to delete it from the Spark'", JS)
        self.assertIn("camStop();            /* [cam-files]", JS)
        self.assertIn("'Close the player'", JS)
        self.assertIn(".fm-cam-player[hidden] { display: none; }", CSS)


if __name__ == "__main__":
    unittest.main()
