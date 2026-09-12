---
name: panel-ui-debugging
description: "How to see and measure the live panel UI without touching the user's app — headless Edge, CDP probe, and the sticky/relative trap"
metadata: 
  node_type: memory
  type: project
  originSessionId: 76060765-7250-4692-8400-1a3022b54df3
  modified: 2026-08-17T18:57:03.275Z
---

Visual iteration loop for the embedded panel (CONTROL_PANEL_HTML in app.py):

- **Screenshot**: headless Edge works —
  `msedge --headless=new --disable-gpu --no-first-run --user-data-dir=<tmp>
  --window-size=WxH --hide-scrollbars --virtual-time-budget=9000
  --screenshot=<png> http://10.89.1.246:8096/`. Needs a user-data-dir or it
  silently writes nothing; poll /healthz first or you screenshot the
  restart's connection-refused page.
- **Real geometry**: launch with `--remote-debugging-port=9333`, then a
  dependency-free Node CDP client (HTTP /json → raw WebSocket upgrade →
  Runtime.evaluate returnByValue) dumps getBoundingClientRect for any
  selector. ~80 lines, rewritable from this description. Beats CSS outline
  probes, which cannot see margins or explain gaps.

Two traps found this way:
- `#activity`'s inline `style="position:relative"` **overrides** its
  stylesheet `position:sticky` — a sticky `top` offset there SHIFTS the
  whole section (61px hole under the HUD) instead of setting a threshold.
  Inline styles beating sheet rules make "sticky" elements silently
  non-sticky; check computed position before reasoning about sticky.
- Flex children with `flex:1` (basis 0) can never trigger `flex-wrap` —
  line-breaking uses the basis-clamped size, so they crush instead of
  wrapping. Give buttons `flex-basis:max-content` to make rows truly wrap.

The media player is `#djBar.dj-deck` — a dedicated sticky top strip (the
user wants it iTunes-like, "always a media player"); its transport/LCD/
actions are `.deck-group`s that wrap as units. Do not put it back into the
live bar's wrap-flow. See [pinebox-desktop-launcher](pinebox-desktop-launcher.md).

More traps (2026-08-17 #786 sweep):
- `subprocess` is only imported LAZILY inside functions in app.py — a
  module-level reference crashloops the container on deploy. The shell
  ledger shim (`subprocess.run` wrapped, served in `/api/perf` as `shell`)
  now imports it at the shim.
- **Nabu is the CORE broadcast device** (user decree): full replay ledger,
  device-aware selfheal/stop/probes, and the desktop ROUTES map for nabu
  carries `music: "box"` — music "off" on that route was a silent speaker.
  `djSetOutput` must NEVER infer voice_device "pine" from a 'box' route.
- Panel features: `PINE_3JS` registry + `pineShow3JS(key)` (standard-size
  windows, all-off sweep ordering matters); `/api/mind/topology/seed`
  (pin/drop honored in speakbox_semantic_seed); every panel h2 folds via
  makeCollapsible; FM-then-Music boot order; djRepairPopup is mission
  control (shell ledger terminal + perf pies/bars).
- Desktop: Station drawer (server-backed config), 3js rail with rich hover
  cards, window bounds persisted in config.bounds, portable
  `\\10.89.1.246\ehm_eckx\pinevoice-stack\pine_box.exe` defaults to
  attaching to 10.89.1.246:8096.
