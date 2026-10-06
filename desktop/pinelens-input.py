"""Persistent JSON input worker. Coordinates are native desktop pixels."""
import ctypes
import json
import os
import shutil
import subprocess
import sys

KEYS = {"Enter": 13, "Tab": 9, "Escape": 27, "Backspace": 8, "Delete": 46,
        "ArrowLeft": 37, "ArrowUp": 38, "ArrowRight": 39, "ArrowDown": 40,
        "Home": 36, "End": 35, "PageUp": 33, "PageDown": 34,
        "ctrl": 17, "shift": 16, "alt": 18, "meta": 91}
KEYS.update({f"F{i}": 111 + i for i in range(1, 13)})
XKEYS = {"Enter": "Return", "ArrowLeft": "Left", "ArrowRight": "Right",
         "ArrowUp": "Up", "ArrowDown": "Down", "PageUp": "Prior", "PageDown": "Next",
         "ctrl": "ctrl", "meta": "super"}


def main():
    win = sys.platform == "win32"
    if win:
        user = ctypes.windll.user32
        # A per-monitor DPI aware worker uses physical pixels on every monitor.
        try:
            user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:
            user.SetProcessDPIAware()
    elif not os.environ.get("DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland" or not shutil.which("xdotool"):
        raise RuntimeError("Desktop control needs Windows, or an X11 session with xdotool")
    buttons = {"left": (2, 4), "right": (8, 16), "middle": (32, 64)}
    held = set()

    def xdo(*args):
        subprocess.run(["xdotool", *map(str, args)], check=True, timeout=2, stdout=subprocess.DEVNULL)

    def button(name, down):
        if win:
            user.mouse_event(buttons[name][0 if down else 1], 0, 0, 0, 0)
        else:
            xdo("mousedown" if down else "mouseup", {"left": 1, "middle": 2, "right": 3}[name])
        if down:
            held.add(name)
        else:
            held.discard(name)

    def release():
        for name in list(held):
            button(name, False)

    def key(vk, down):
        user.keybd_event(vk, 0, 0 if down else 2, 0)

    def unicode_text(text):
        # SendInput's pointer-sized fields matter on 64-bit Windows.
        class Keyboard(ctypes.Structure):
            _fields_ = [("vk", ctypes.c_ushort), ("scan", ctypes.c_ushort),
                        ("flags", ctypes.c_ulong), ("time", ctypes.c_ulong), ("extra", ctypes.c_size_t)]
        class Mouse(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long), ("data", ctypes.c_ulong),
                        ("flags", ctypes.c_ulong), ("time", ctypes.c_ulong), ("extra", ctypes.c_size_t)]
        class Payload(ctypes.Union):
            _fields_ = [("keyboard", Keyboard), ("mouse", Mouse)]
        class Input(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong), ("payload", Payload)]
        raw = text.encode("utf-16-le")
        for i in range(0, len(raw), 2):
            unit = int.from_bytes(raw[i:i + 2], "little")
            events = (Input * 2)(Input(1, Payload(keyboard=Keyboard(0, unit, 4, 0, 0))),
                                 Input(1, Payload(keyboard=Keyboard(0, unit, 6, 0, 0))))
            if user.SendInput(2, events, ctypes.sizeof(Input)) != 2:
                raise RuntimeError("Windows refused desktop input")

    print(json.dumps({"ready": True}), flush=True)
    try:
        for line in sys.stdin:
            try:
                cmd = json.loads(line)
                kind = cmd["type"]
                if kind == "pointer":
                    if win:
                        user.SetCursorPos(int(cmd["x"]), int(cmd["y"]))
                    else:
                        xdo("mousemove", "--sync", cmd["x"], cmd["y"])
                    if cmd["action"] != "move":
                        button(cmd.get("button", "left"), cmd["action"] == "down")
                elif kind == "release":
                    release()
                elif kind == "wheel":
                    if win:
                        user.mouse_event(0x800, 0, 0, int(cmd["delta"]) * 120, 0)
                    else:
                        xdo("click", "--repeat", abs(int(cmd["delta"])), 4 if cmd["delta"] > 0 else 5)
                elif kind == "text":
                    if win:
                        unicode_text(cmd["text"])
                    else:
                        xdo("type", "--clearmodifiers", "--", cmd["text"])
                elif kind == "key":
                    mods = cmd.get("modifiers", [])
                    name = cmd["key"]
                    if win:
                        vk = KEYS.get(name)
                        implicit = 0
                        if vk is None and len(name) == 1:
                            mapped = user.VkKeyScanW(ord(name))
                            if mapped == -1 and not mods:
                                unicode_text(name)
                                continue
                            if mapped == -1:
                                raise ValueError("Key has no Windows shortcut mapping")
                            vk, implicit = mapped & 255, (mapped >> 8) & 7
                        combined = set(mods)
                        combined.update(m for mask, m in ((1, "shift"), (2, "ctrl"), (4, "alt")) if implicit & mask)
                        try:
                            for mod in combined:
                                key(KEYS[mod], True)
                            key(vk, True)
                            key(vk, False)
                        finally:
                            for mod in combined:
                                key(KEYS[mod], False)
                    else:
                        xdo("key", "--clearmodifiers", "+".join([XKEYS.get(m, m) for m in mods] + [XKEYS.get(name, name)]))
                print(json.dumps({"ok": True}), flush=True)
            except Exception as exc:
                release()
                print(json.dumps({"error": str(exc)[:200]}), flush=True)
    finally:
        release()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"error": str(exc)[:200]}), flush=True)
        sys.exit(1)
