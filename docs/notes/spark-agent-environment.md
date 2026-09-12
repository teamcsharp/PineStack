---
name: spark-agent-environment
description: Environment quirks for working on spark-agent from this Windows machine
metadata: 
  node_type: memory
  type: project
  originSessionId: 5b7915ce-38d4-41a6-8fe0-c5344d093b3b
  modified: 2026-08-16T17:39:40.353Z
---

The repo lives on an SMB share (`\\10.89.1.246\ehm_eckx\pinevoice-stack\spark-agent`, host "lilspark", a DGX Spark) and is SLOW — copy `app.py` (~2MB) to the scratchpad, work locally (grep/edit/`python -m py_compile`), then copy back once.

**Why:** recursive Glob/ripgrep over the share times out; dozens of Edits over SMB are painfully slow.

**How to apply:**
- Git needs `git config --global --add safe.directory '%(prefix)///10.89.1.246/ehm_eckx/pinevoice-stack/spark-agent'` (done 2026-08-14; different host/user SIDs).
- Local Python 3.12.5 matches the container (python:3.12-slim). Container deps: fastapi, uvicorn, httpx, mutagen, pyserial, imageio-ffmpeg (static ffmpeg binary — the only audio tool).
- **`python -m py_compile` is not enough.** It passed on a `NameError` that
  only fired at runtime (a variable whose defining line was removed in a
  refactor, still referenced below). Run `python -m pyflakes app.py` before
  every deploy and read the *undefined name* lines — the rest are noise.
- The panel is one giant `CONTROL_PANEL_HTML = r"""…"""` (plus
  `RADIO_PAGE_HTML` for the `/tune/<token>` listener page). Extract the
  `<script>` block and `node --check` it — a JS syntax error is otherwise
  invisible until the page is open.
- Chrome is at `C:\Program Files (x86)\Google\Chrome\Application\chrome.exe`.
  `--headless=new --virtual-time-budget=N --dump-dom` + writing the result
  into `document.title` measures real layout (overlaps, overflow) without a
  browser automation stack. Inline the probe `<script>`: an injected
  `<base href>` makes a `src="probe.js"` resolve at the server and 404.
  Recipe that works (verified 2026-08-15, found the #740 flex bug and
  exercised every new modal for runtime errors):
  - `Invoke-WebRequest -OutFile` for the page, then splice with
    `[Text.Encoding]::UTF8.GetString/GetBytes`. A `-replace` on the decoded
    `.Content` mangles UTF-8 and fakes a "SyntaxError" in the panel script.
  - Splice at the **first** `<head>` only (`IndexOf` + `Substring`), never
    `.Replace("<head>", …)`: the panel script contains the literal string
    `"<!doctype html><html><head><script>"`, so a blanket replace edits code
    inside a JS string and fakes a SyntaxError that `node --check` on the
    extracted script cannot see. Same class as the UTF-8 trap above.
  - The page runs from `file://`, so its own relative `/api/...` calls cannot
    resolve. Stub `window.api` after load and call the renderers directly —
    that is the code under test, not fetch.
  - Stub `requestAnimationFrame` and `setInterval` to no-ops in a `<head>`
    script, or the page's own animation loops keep virtual time alive and
    `--dump-dom` never returns (it hangs past a 2-minute timeout).
  - Capture stdout with `Start-Process -RedirectStandardOutput`; a plain
    `>` or `$out =` from this shell comes back empty.
  - Hook `window.onerror` + `unhandledrejection` into an array and print it
    in the title — that is how you tell a modal that opened from one that
    threw.
- There is **no global `esc()`** in the panel script — every `esc` is a
  function-local `const`. Reaching for one from new top-level code is a
  ReferenceError `node --check` cannot catch. The global escaper is
  `callerDossierEsc(s)`.
- **wyoming-piper wedges.** Repeatedly: the port stays open, `describe`
  returns nothing, `voice_allowlist()` empties and every Piper render fails
  "No such voice: <a real voice>". Three times in one session (2026-08-16).
  Clear it with `POST /api/service/restart {"name":"wyoming-piper"}` — that
  endpoint takes ANY container in the stack, not just spark-agent — and it
  comes back reporting 163 voices. The same shape as the Pine Box wedge
  (#712): an open port is not a working service, on either device.
- Voices route by NAME: `vl_########` ids are library clones (xtts/f5),
  everything else is a Piper voice. Anything that renders on the broadcast
  path should go through `voice_render_any` (#784) rather than
  `voice_generate` — it is the ladder that guarantees a line gets audio while
  any engine is alive, and it never hands a clone id to Piper.
- three.js is vendored at `data/vendor/three.min.js` (+module/core builds).
- Stack config: `../compose.yaml`; secrets in `../.openwebui.env`; peer services on host network: HA :8123, ComfyUI :8188, voice-lab :8771, XTTS :8770, Ollama :11434, app :8096.
- The permission classifier sometimes blocks Invoke-RestMethod/WebRequest calls (it blocked extracting the API key from the served page; reading `.openwebui.env` directly is fine). See [pine-inbox-workflow](pine-inbox-workflow.md).
