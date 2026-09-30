"""[cam-ffmpeg] the Pine Cam's cuts use the station's own ffmpeg.

There is no ffmpeg on this container's PATH (`which ffmpeg` answers nothing);
the station's encoder is imageio-ffmpeg's, which every other road reaches through
_sfx_ffmpeg_exe(). The span cutter - the /api/pinelink/cut route behind the box's
record button - called a bare "ffmpeg" and could only ever raise FileNotFoundError;
the new thumbnail and recordings-preset code had copied it.

Usage (ON THE HOST): python3 tools/cam_ffmpeg_patch.py --check|--apply
"""
import ast
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDITS = [
    ('            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",\n',
     '            [_sfx_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",   # [cam-ffmpeg] not on PATH here\n'),
    ('            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",\n',
     '            subprocess.run([_sfx_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",\n'),
    ('    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(src),\n',
     '    subprocess.run([_sfx_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(src),\n'),
]

if __name__ == "__main__":
    mode = sys.argv[1]
    path = ROOT + "/app.py"
    src = open(path, encoding="utf-8").read()
    if "[cam-ffmpeg]" in src:
        print(path + ": APPLIED")
        sys.exit(0)
    out = src
    for old, new in EDITS:
        assert out.count(old) == 1, "%r found %d" % (old[:60], out.count(old))
        out = out.replace(old, new)
    ast.parse(out)
    if mode == "--check":
        print(path + ": ready")
        sys.exit(0)
    shutil.copy(path, "/tmp/app.py.bak-cam-ffmpeg")
    with open(path, "r+", encoding="utf-8") as fh:
        assert fh.read() == src
        fh.seek(0)
        fh.write(out)
        fh.truncate()
    print(path + ": applied")
