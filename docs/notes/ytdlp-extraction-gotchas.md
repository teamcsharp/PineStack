---
name: ytdlp-extraction-gotchas
# 2026-08-17: STABLE yt-dlp is not enough anymore — YouTube SABR
# enforcement 403s media fetches on most clients; voice-lab now
# self-upgrades with --pre (nightly channel), classifies
# "unable to download video data"+403 as DATA_FORBIDDEN (move ladder on,
# don't retry the same dead URLs), leads the YouTube rungs with
# tv/web_embedded, and base retries dropped 10→3 (http sleep cap 15s).
# Vimeo now REQUIRES login site-wide (cookies.vimeo.txt jar), same as
# Instagram. Ingest "range" is normalized to start/end at the API door
# (#795) — it used to be a silent no-op outside the panel.
description: Non-obvious yt-dlp facts verified live on this box (2026-08-14) for the voice-lab downloader
metadata: 
  node_type: memory
  type: reference
  originSessionId: 5b7915ce-38d4-41a6-8fe0-c5344d093b3b
  modified: 2026-08-17T23:59:42.862Z
---

Verified by testing on the DGX, not just reading docs:

1. **imageio-ffmpeg's binary is named `ffmpeg-linux-aarch64-v7.0.2`.** yt-dlp finds tools by *filename*, so it reported "ffmpeg is not installed" and refused every ranged download. Setting `ffmpeg_location` is **not enough**: the check that rejects a partial download is `FFmpegFD.available()`, which builds a throwaway post-processor with no options and only looks on `PATH`. Fix = symlink to `/tmp/ffbin/ffmpeg` *and* prepend that dir to `os.environ["PATH"]`.
2. **Don't ask yt-dlp for ranges at all.** Even with ffmpeg found, `download_ranges` handed the job to ffmpeg-as-downloader, which answered exit 251. Download whole, trim in `_extract_audio` — one path for uploads and downloads.
3. **Python API `js_runtimes` is a dict**, not the CLI list: `{"deno": {}}`. A list raises ValueError at construction. Best is to omit it: `pip install yt-dlp[deno]` drops the binary in the scripts dir where yt-dlp looks first.
4. **Debian nodejs is too old** (18/20 vs yt-dlp's 22+ minimum) — apt is a dead end; use the `deno` pip extra.
5. **`yt-dlp[default]` pulls `yt-dlp-ejs`**, the JS-challenge solver. Bare `pip install yt-dlp` gets neither, and YouTube then returns storyboards only.
6. **Cookies change the client set**: with a jar attached, every `SUPPORTS_COOKIES=False` client (visionos, android_vr, ios, android, tv_simply) is dropped, so a cookie-only ladder rung made of those returns "Failed to extract any player response". Keep separate cookie/anonymous ladders.
7. **`formats: ["missing_pot"]` is harmful** — it re-enables formats yt-dlp skipped because they 403.
8. **"This content isn't available, try again later" is a RATE LIMIT**, not a dead video. Wait and retry; walking more clients makes it worse.
9. **`yt_dlp.__version__` doesn't exist** — use `from yt_dlp.version import __version__`.
10. **This box's IP is bot-checked by YouTube for anonymous requests** (every client, even with the PO-token provider running). Only a cookies.txt fixes that. Non-YouTube sites (Dailymotion tested OK) work fine without.

See [pinevoice-deploy-paths](pinevoice-deploy-paths.md).
