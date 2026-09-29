"""[vcrfx] pinelive.py: PineCam to live counts its flips, so a viewer's page
that polls every few seconds can replay every flip it missed with the CRT
effect ("they should be seeing a video go in and out ... over and over as I'm
flipping the switch"). The count rides the clock (clock_extra.pinelive.picture
.switch) and /api/pinelink/mine (app.py). In memory: a restart starts at 0,
and a page that sees the count go DOWN only re-bases.
TARGET: pinelive.py
"""
from _vcrlib import Edit, main

EDITS = [
    Edit("count", "self.video_flips = int(getattr(self, \"video_flips\", 0)) + 1",
         """        if old.get("tailscale_video") != new.get("tailscale_video"):
            self.note("tailscale_video", "public video %s" % (""",
         """        if old.get("tailscale_video") != new.get("tailscale_video"):
            self.video_flips = int(getattr(self, "video_flips", 0)) + 1     # [vcrfx]
            self.note("tailscale_video", "public video %s" % ("""),
    Edit("method", "def video_switch(self)",
         """    def public_video_blocked(self) -> bool:
        return self.armed() and not bool(self.settings.get("tailscale_video"))
""",
         """    def public_video_blocked(self) -> bool:
        return self.armed() and not bool(self.settings.get("tailscale_video"))

    def video_switch(self) -> dict[str, Any]:
        \"\"\"[vcrfx] PineCam to live as a viewer's page needs it: whether it is
        on, how many times it has been flipped since the station started, and
        whether a set is armed (the only time the switch decides anything).\"\"\"
        return {"on": bool(self.settings.get("tailscale_video")),
                "flips": int(getattr(self, "video_flips", 0)),
                "armed": bool(self.armed())}
"""),
    Edit("clock", "\"switch\": self.video_switch()",
         """            "picture": {"kind": (self.picture.kind if show else "none"),
                        "art": art if show else ""}}}""",
         """            "picture": {"kind": (self.picture.kind if show else "none"),
                        "art": art if show else "",
                        "switch": self.video_switch()}}}                # [vcrfx]"""),
    Edit("module", "def video_switch() -> dict[str, Any]:",
         """def public_video_blocked() -> bool:
    try:
        return PL.public_video_blocked()
    except Exception:  # noqa: BLE001
        return False
""",
         """def public_video_blocked() -> bool:
    try:
        return PL.public_video_blocked()
    except Exception:  # noqa: BLE001
        return False


def video_switch() -> dict[str, Any]:
    \"\"\"[vcrfx] PineCam to live: on, flips, armed (see PineLive.video_switch).\"\"\"
    try:
        return PL.video_switch()
    except Exception:  # noqa: BLE001
        return {"on": False, "flips": 0, "armed": False}
"""),
]

if __name__ == "__main__":
    raise SystemExit(main(EDITS))
