# Extending the station

Written for whoever — or whatever — works on this next. Everything here is a
rule that was learned by breaking it.

---

## 1. The invariants

Break one of these and the station goes quiet, or lies to the operator. In
rough order of how badly.

### The air is never dead

Every road, every check, every optimisation is subordinate to this. Concretely:

- a function on the air path **must not raise**. Wrap it. `schedule_take()`,
  `selling_now()`, `coord_brief()` and every road all return an empty value on
  any exception rather than propagating.
- a refusal is a message, not a dead endpoint. `schedule_interject()` returns
  `{"ok": False, "why": ...}` rather than raising at the operator.
- a filter that would leave nothing must be **ignored**, loudly. `radio_fill()`
  does exactly this with `music_focus()`: a corner of the library matching
  nothing is logged and dropped, and the whole library comes back.
- material that fails a check goes to the **back of the shelf**, never in the
  bin. A round that misses its point still beats silence.

### Nothing is bound to the station when it belongs to a round

The station has global state — what is being held up, what is being sold, what
kind of round last ran. It is tempting to read it at the moment a line is
written. **Do not**, unless the thing you are reading genuinely is a property of
the station at that instant.

Measured failure: hanging the gallery's painting on booth lines by reading
"what is the station holding up right now" put a painting beside a phone call
about a library book, twice, because an ad had sold one a minute earlier.

Rounds are written in bursts and their booth rows land well after the round
kind has moved on, so `_RADIO["last_round_kind"]` is **not** a reliable guard at
row-append time either. Bind it to the entry, in `_banter_air()`, and clear it
for a round that has none.

### Whatever `shelf_put()` stamps, the restore path must stamp too

`_SHELF` comes back from `SHELF_PATH` at startup **without going through
`shelf_put()`**. Anything you add in `shelf_put()` is therefore missing for
exactly the rows that survived a restart — which on a station under active work
is most of them. `#968`'s brief audit hit this immediately: the audit reported
"nothing checkable has been banked" while the shelves were full.

### A report reads the thing, not a log of the thing

Related, and the general form of the above. `brief_state()` reads the
**shelves** first and its in-memory ring second, because the shelves are the
truth and the ring is a session artefact. If a reporting function can read the
real state, have it read the real state.

### Do not spend a model visit to check the model

The writing desk is the bottleneck the whole station queues behind. A check
that costs a desk visit per round takes writing time from the show it is
checking, and it is the same model marking its own homework. Every check in
this codebase is deterministic: `segment_audit()`, `coord_brief()`,
`coord_capacity()`, `interject_progress()`. Keep it that way.

### Measure before you assert

See `rendering.md` §5. A constant describing how long, how loud or how much
should be checked against `task_stat()` before it is trusted. The phone-call
bug lived for a long time behind a well-written comment explaining a number
that was wrong by 3x.

---

## 2. Adding a segment kind

1. **`SCHEDULE_KINDS`** — add `{"kind", "label", "blurb"}`. The blurb names the
   function that runs it; keep that habit, it is how anyone finds the road.
2. **`SCHEDULE_PROMPT_SEED`** — the default system prompt for the kind.
3. **`SCHED_PREP_KIND`** — map it to a preparing road. Reuse an existing road
   when the shape matches (`bombshell` uses `ad`: a short written read).
4. **`CANNOT_PREPARE`** — add it *only* if it genuinely cannot be written
   ahead, with the reason. That reason is shown to the operator on the entry's
   bar instead of an empty one.
5. **The round chain** in the torrent — `elif kind == "yours":` — and give it a
   **fallback**. Every kind falls back to banter when its own road comes up
   empty. `caller` alone did not, for a long time, and a four-minute phone
   segment could air nothing at all round after round.
6. **`SEGMENT_BRIEF`** — if the kind's job is checkable from the words, add a
   brief. If it is not, leave it out; `segment_audit()` returning
   `checked: false` is the honest answer and it keeps the pass rate meaningful.
7. **`SHELF_CAPS`**, **`SHELF_LABEL`**, and **`SHELF_REUSABLE`** if a rested
   copy going out again is acceptable for that kind.

## 3. Adding a check

Follow `segment_audit()`:

- deterministic, cheap, explicable
- says which evidence it looked at (`found`), so a false alarm is arguable
  rather than mysterious
- has a "cannot judge" answer and uses it
- names the **likely cause** in its log line, not just the symptom. "Off brief"
  on its own sends the operator looking at the model when the answer is usually
  a dial they set themselves
- its verdict is stamped on the thing it judged and travels with it

## 4. Adding an endpoint

- `require_read_auth(authorization)` for anything that reads,
  `require_auth(authorization)` for anything that changes something
- return a dict with a `say` field when a human will read it. Every coordinator
  endpoint does; it is what lets the desk show one line without knowing the
  schema
- never raise for an ordinary "no" — return the reason
- pair it with a reader in `desktop/renderer/renderer.js` if the operator needs
  it, and remember the desktop app must be **relaunched** to pick up renderer
  changes, while `app.py` changes need a service restart
- there is a **third surface** now. The panel runs inside
  `<webview id="radioFrame">`, a separate document the Electron chrome cannot
  reach into, so anything that must read state the chrome's own document does
  not hold belongs in the webview preload,
  `desktop/renderer/webview-preload.js`, which posts it out. A **preload
  change is not picked up by a page reload** — only a full desktop relaunch
  loads it, because the preload is attached when the webview is created. The
  DJ voice playhead is the worked example; see
  `notes/the-chrome-cannot-see-the-panel.md`

## 5. Working on this codebase

**Deploying.** `app.py` lives on the SMB share and the share is slow — work on
a local copy, `py_compile` it, then copy it over. Restart with
`POST /api/service/restart {"name": "spark-agent"}` and poll `/healthz`.

**Patching.** `app.py` is very large. Write patch scripts with unique anchor
strings and a match count that must equal 1, so a failed anchor is an error
rather than a silent no-op or a double application. Beware:

- the file contains **literal** unicode (em dashes, curly quotes). An anchor
  written with `—` will not match text stored as the character.
- a patch script that fails partway must not have written anything. Collect all
  replacements, then write once.
- heredocs mangle backslashes, backticks and `\n`. Use a file, not a heredoc,
  for anything with escapes in it.

**Verifying.** Prefer a measurement on the live station to reading the code and
believing it. Several of the fixes in this session looked correct, compiled,
deployed — and did nothing, which only the measurement revealed:

- the transition bar: watched from queued at 0s to done at 243s
- the segment change announcement: heard on air within four minutes
- the music focus: four consecutive records by the pinned artist
- the picture binding: 30 of 60 booth rows, every one a gallery line
- the brief audit: found the operator's own complaint on its first pass

**Committing.** One commit per request cluster, with the measurement in the
message. A commit that says what changed and not what it measured is half a
commit.

---

## 6. Where things are

| what | where |
| --- | --- |
| everything server-side | `app.py` |
| the control panel | `CONTROL_PANEL_HTML` inside `app.py` |
| the radio page | `RADIO_PAGE_HTML` inside `app.py` |
| the desktop shell | `desktop/main.js`, `desktop/preload.js` |
| the desk UI | `desktop/renderer/` — **many files, not three**: `index.html`, `renderer.js`, `styles.css`, plus `webview-preload.js` (the webview bridge), `script-page.js`/`script-page.css` (the SCRIPT view), `sampler.js` (the sample forge), `sfx-tv.js` (the CRT set), `pine-cam.js` (the camera), `clip-doctor.js` (why the video button gave nothing), `talk-dot.js` (the orb) and the rest |
| the tablet's copy of the desk UI | `C:\_tools\pinebox-android\PineBoxKiosk\app\src\main\assets\pine-views\` — byte-identical copies, injected by `ViewAssets.kt`; a change here needs `./deploy.sh`, never a bare gradle build (`docs/pinetab.md` §18) |
| persisted state | `data/` — `prep_shelf.json`, `settings.json`, `pine_requests.md`, `crystals/`, `speakbox/`, `sfx_clips.db` (the clip book), `pinelink/` (camera state, recordings, cuts), `pinelink_pref.json`, `shares.json` (tune-in links, with the camera tick), `gap_log.jsonl` (every silence, with its cause) |
| host-side units | `tools/pinelink.service`, `tools/pinelink-kick.{path,service}` (the flag-file door from the container to the radio), `tools/99-pine-neigh.conf` (the ARP ceiling) |

The booth window, the hour view and The Works all live in
`desktop/renderer/renderer.js`. The top status strip is
`desktop/renderer/index.html`. Everything else has been split out into its
own file beside them — look there first, `renderer.js` is no longer the whole
desk.

### 6.1 The roads added on 2026-09-14

Each of these exists because a fault was measured that nothing could see.
They are listed here so the next person finds the door before rebuilding it.

| road | what it answers |
| --- | --- |
| `GET /api/deadair?hours=N` | The dead-air census: every silence in the window by hour, by cause and by the frame that was blocking the loop, with a verdict that says which of two *opposite* faults it was — a famine (more material) or a stall (take the named function off the loop). `learning_desk` reports the queue that #1371 moved the SQLite writes onto. |
| `GET /api/sfx/doctor`, `POST /api/sfx/doctor/{ping,folders,rebuild}` | Why there is no clip, in terms that name a cure. Its first line is the tell for a stale Docker bind: the device id of `/samples` against the station's own data directory. |
| `GET /api/sfx/db`, `POST /api/sfx/db/rebuild` | The clip book — `data/sfx_clips.db`. Every clip with its length and whether it is playable; the video button draws from it in about a millisecond and never touches the share. |
| `GET /api/pinelink/look`, `/state`, `/doctor`, `/frame.jpg`, `/clips` | The Pine Cam, seen from the station. `doctor` asks the neighbour-table question first, because that is the one fault where the radio and the camera are both healthy and the join still fails. |
| `POST /api/pinelink/{connect,reset-radio,on-air,public,cut}` | The cures and the switches. `connect` and `reset-radio` go through the host bridge (`pinelink-kick.path`) — there is no `systemctl` in the container. |
| `GET /api/pinelink/viewers`, `GET /api/pinelink/mine`, `POST /api/share/camera` | Who outside the house may see the camera: nobody, the ticked tune-in links, or anyone with a link. The tick lives *on the link*, so revoking the link revokes the camera. `mine` answers for the caller's own token and lists nobody else's. |

| `GET /api/said/search?q=word&hours=48` | Every time a word or phrase was said on the air, and *why* it keeps being said: `why` names one of four shapes — REPEATS (a few lines re-aired, cure on the repetition desk), ONE ROAD, ONE VOICE, or SPREAD (the word is simply common) — with the counts that back it. The SCRIPT view's search box on the tablet and the desktop draws it. (#1380 for #1110) |
| `POST /api/pine-requests` | Unchanged for callers — but every report now carries a `### Station at the time` block: what is playing, what is being said, the last five lines, the script position, the listeners and their switches, the loop's pulse, the last hour's dead air with its verdict, the ladder's LOOK, the tablet, the learning desk. The request gist stops at the marker, so repeats still fold. (#1379 for #1094/#1095/#1098) |
| `GET/POST /api/cupboard/finish`, `POST /api/cupboard/act {action: cue\|uncue\|finish}`, `GET /api/sfx/video/mode` | The inbox agent's roads (#1363–#1366), now with the buttons they lacked: the retirement desk's *Resume recording the incomplete ones*, its greyed unfinished rows, *Cue* on every row and on each road's unheard list (#1384), and the SCRIPT view's endless-video button beside the video button (#1385). |
| `GET /api/tablet/look`, `POST /api/tablet/doctor/{look,ping,arp,sweep,adopt,wake}` | The tablet, from the station's side (#1367). The desktop's tools icon beside *The tablet* walks them and then does the one rung the station cannot — `adb connect` — and looks again (`tablet-doctor.js`, #1386). |
| the panel's 🧊 button | Every 3JS view (Dialogue Mind, rhetoric sphere, vector tree, the Sim, RapAssembly) and the station's papers (journal, gazette, retirement desk, System2, station flow, the guide, the gallery) from one popup, each entry calling the opener its own button calls (#1381 for #1091/#1092). |

The public door (`:8097`) allows exactly `/api/pinelink/mine` and
`/api/pinelink/frame.jpg` from that set, and both refuse a request that
arrived through it without a token. The first cut did not — measured, a bare
`GET` on `:8097` returned the frame — so read `PublicListenerGate` before
widening `_PUBLIC_GET` again.
