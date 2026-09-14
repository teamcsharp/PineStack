# The loop under the profile

*2026-09-14, 12:40–13:05. Cures #1398 and #1402–#1406; the continuity agent's
#1390, #1396, #1397, #1400, #1401, #1407 and #1408 landed in the same two boots
and are written up in [continuity-investigation-2026-09-14.md](continuity-investigation-2026-09-14.md).*

## The instrument that could not see it

`/api/pulse` (#1156) names any stall of 1.5 s or more, with the frame that was on
the main thread. `/api/deadair` (#1368) had already read the morning's silence as
93% *loop blocked*. Both are true, and both are blind to the same thing: a loop
that is eighty percent busy with work that never once holds it for 1.5 s. That
loop answers `/healthz` in time, never trips the watchdog, and still turns every
clip that needed an event-loop turn at the right moment into a late one.

So the measurement was a profile of the process, not a census of its stalls.
From the DGX host:

```
PY=$(docker top spark-agent -o pid,cmd | awk '/python|uvicorn/ && !/sh -c/ {print $1; exit}')
sudo /usr/local/bin/py-spy record --pid $PY --duration 20 --rate 100 --threads \
     --nonblocking --format raw --output /tmp/pine_prof.raw
```

Three things about reading it. `docker inspect .State.Pid` is the `sh -c`
entrypoint, and py-spy says *Failed to find python version* on it — use
`docker top`. With `--nonblocking` the idle filter does not work: every pool thread
reports ~2,000 of 2,000 samples, so the main thread's *shares* are the reading, not
an absolute occupancy; the leaf `run (asyncio/runners.py:118)` is the loop parked
in its C select, which is the closest thing to "idle" the raw output offers. And a
leaf line can be a bystander — the main thread parked at whatever bytecode it
reached when a pool thread took the GIL for a C call (the agent's reading of
`_gc_report`, below, is that; the cure is the same either way).

## What twenty seconds said (12:50, boot of 12:26, 1,746 main-thread samples)

| inclusive frame | share | what it is |
| --- | --- | --- |
| `run_endpoint_function` | 59.4% | HTTP handlers, mostly polls |
| `dj_state` / `dj_status` | 26.8% | `/api/dj`, 286 KB, 0.76 s a call, polled by every surface |
| `dialogue_flow_state` → `hour_needs` → `dialogue_row_ready` → `tint_coverage_ready` → `crystal_acceptance_mode` → `PromptLearning.settings` | 13.5% → 8.1% | a one-string read that took the learning store's lock and deep-copied its state |
| `pulse_report` → `_gc_report` | 13.0% | the collector's report, built per poll; `gc.get_freeze_count()` walks 521,091 frozen objects |
| `current_async_library` → `_find_and_load` → `_path_stat` → `stat` | 9.6% | **a failed import on every httpx request** |
| `health_details` | 7.7% | the vitals line (memoised 20 s, but it carries the pulse) |
| `dump_python` + `iterencode` | 3.3% | FastAPI's response serialization — the theory I went in with, retired |
| leaf `run (runners.py:118)` | 17.4% | parked / idle |

## The four faults, and why each was invisible

**A failed import, per request (#1406).** `httpcore/_synchronization.py` does
`import sniffio` inside `current_async_library()`, on every request, and catches
`ImportError`. `sniffio` was not installed: anyio 4.15 dropped it as a dependency and
nothing else pulled it in. A failed import is never cached in `sys.modules`, so every
`httpx` call — Ollama, Home Assistant, ComfyUI, the lifeboat, the peers — paid a
`sys.path` scan with a `stat` per entry, on the loop. The cure is one line in
`requirements.txt`; the entrypoint pip-installs on a hash change, and it was installed
into the running container too, which fixed the *running* process at once, because
the next `import sniffio` simply succeeded and stayed. Check after any image change:
`docker exec spark-agent python3 -c "import sniffio"`.

**A lock shared with a desk (#1402).** #1371 moved the learning store's writes to a
worker thread so their fsyncs left the loop. `crystal_acceptance_mode()` then read one
string — the mode — through `settings()`, which takes the same lock and deep-copies
the state. The worker holds that lock through each SQLite commit, so the loop's
one-string read waited for the desk's fsync: the wait had moved, not gone. Under every
`/api/dj` poll, through `hour_needs`. `PromptLearning.mode()` reads the string with
no lock and no copy; the 3 s memo in front of it already tolerates a value one write
behind. *Rule: when a desk thread is added, grep every loop-side caller of the lock it
will hold.*

**The collector's report (#1402).** `_gc_report()` — three `gc` calls — was built for
every poll, and `gc.get_freeze_count()` is a walk of the permanent generation, half a
million objects after #1393 froze the vector stores. Whether the 13% was the walk or
the main thread parked there under a pool thread's GIL hold, the report is now the
count `_gc_freeze_after_load` wrote down, memoised for five seconds.

**Files parsed per read (#1403, #1404).** `call_log_read()` parsed the whole call log
— 2.6 MB, 5,000 rows with transcripts and flow reports — on every call, and it is
called from the novelty check, the caller card, the records lists and every hang-up;
the pulse caught it at 3.4 s four times in ten minutes. `call_log_add()` then graded
the finished call on the loop (`call_flow_report` → `call_tint_report` → two contract
extractions per turn) and wrote the file back with an indent. Now the rows live in
memory keyed on `(st_mtime_ns, st_size)` with a two-second grace, the way
`crystals_read` has worked since #1022, and a hang-up appends to the panel's ring at
once and hands the grading and the write to one daemon thread, in order.
`pushed_sections()` — a two-byte file read for every `/api/dj/sections` poll — got the
same memo.

**The lab's trace (#1398).** `rejection_lab_runtime.record()` was a SQLite INSERT and
commit — an fsync — for every tint-wired model call, on the loop; the pulse caught
`ask_model` at 11.0 s. The trace id is read synchronously (it lives in a ContextVar a
thread would not see) and the write goes to a writer thread; the one caller that keeps
the row (`line_review_capture`, for `lab_cut_step`) says `wait=True`.

## After (13:02, boot of 12:57, 1,875 main-thread samples)

| inclusive frame | before | after |
| --- | --- | --- |
| `run_endpoint_function` | 59.4% | 22.1% |
| `dj_state` | 26.8% | 4.7% |
| `dialogue_flow_state` | 13.5% | 3.7% |
| `hour_needs` | 12.8% | 2.8% |
| `crystal_acceptance_mode` | 8.1% | 0.1% |
| `_gc_report` | 13.0% | 0.0% |
| `current_async_library` (the failed import) | 9.6% | 0.0% |
| `health_details` | 7.7% | 0.5% |
| leaf `run (runners.py:118)` — parked | 17.4% | 57.2% |

The pulse of the same boot, first five minutes: 6 stalls, 33.5 s, against 37 stalls
and 120.8 s in the ten minutes before (12:40). What was left was the other class
entirely — two 12–13 s rows in the first minute after boot (`sfx_history_add` and
`_voice_media_names` as bystanders while the 684 MB vector store was parsed under the
GIL in a pool thread), and one 12.25 s `outside: run` at boot+107 s, which is that
store being *written* in one `json.dumps` — the agent's #1407 writes it in slices.

## What is still on the loop, in order

- **The vector store itself.** 684 MB of JSON floats, parsed once per boot in a pool
  thread that holds the GIL for the length of the parse, and rewritten on a progress
  save. Slicing the write (#1407) bounds the dump; the parse needs the store out of
  JSON — a small metadata JSON beside a binary array — and that is the next
  structural item, not a memo.
- `spoken_text` (app.py, regex) 5.7% of the after-profile, `re.sub` 3.0%.
- `read_text` 4.8% — a file read on the loop each poll; `load_settings` showed at 2.05 s
  once and `_read_voices_disk` is on the earlier list.
- `ssl.create_default_context` 1.7% — every `httpx.AsyncClient()` builds a fresh SSL
  context and loads the CA bundle; one shared client per peer would remove it.
- `sfx_history_add` writes a 180 KB ledger on the loop per sting; cheap, but it is a
  file write on a disk the pantry flusher shares.
- `pantry_spoken_for()` — the shelf walk behind `_row_clip_keys`, cached 15 s, 5 s
  when it runs; it belongs in a thread with the stale set served meanwhile.

## The endless set, on the same day

The user's ask was "the SFX guy able to play clip after clip after clip … cache a
list and execute it fluidly in the background". #1395 made the loop button a playlist
rung ahead from the clip book (three deep, ~20 s ahead, each clip stamped to start
when the previous ends); #1399 made the desktop shell's tube mount itself; #1405 kept
the ladder from reading the rung-ahead pictures as a stuck queue. PineTab §27 has the
user-facing account.

## The second boot (13:04:52, with the agent's #1407/#1408), clean ten minutes

Pulse 13:05–13:15: 24 stalls, 76.4 s, worst 13.0 s — the one 13 s row is the
startup parse again (`sfx_history_add` as bystander at boot+9 s); the vector
store's dump now shows as four rows of under 2 s (`outside: run`, worst 1.95 s)
where it was one of 12–16 s. Gap ledger since boot: 2 gaps, 90 s in 9.3 minutes
(16%; the previous hour read 48%). System2: 5 of 18 slots empty, 3 past deadline
(was 14 of 18). The station heard one second ago; the set rung 60 clips.

Names new to the pulse, for the next pass: `gold_pick` (2×, worst 6.1 s),
`<genexpr>` at 6.8 s beside it, `speakbox_heard` (2×, worst 4.3 s),
`pinelink_state` (5.5 s — a subprocess or a socket on the loop). The waiting
count's decay is #1410, on disk for the next boot.

## The other half: the tablet (14:00)

The operator said *the station is stuttering*. The station's stalls were one
cause (the vector store's five-minute save, #1412 — every file touch on the loop
waited behind a 684 MB write). The other was the tablet, and it was not the
video set: with the set off for five minutes the kiosk sat at 255% and its
WebView at 289%. Per thread (`cat /proc/<pid>/task/*/stat` twice, diffed by
comm): `CrRendererMain` saturated, `Realtime AudioWorklet` ~80% of a core,
`Chrome_InProcGpu` + `RenderThread` + `mali` ~150%. The Chrome profiler over
`webview_devtools_remote_<pid>` (adb forward, `Profiler.start/stop`) named the
JS: `drawScope` 17%, `paintScope` 6%, `querySelectorAll` 6% — and 43–72% in
`(program)`. `document.getAnimations()` counted 380. Cures #1413a–e are in
PineTab §28; after #1413d the kiosk's GPU/render threads fell to 53/47/30% and
the audio thread to 35%, with the main thread's remaining load being the CSS
animations #1413e switches off. The measurement to keep: the tablet's user
agent is `Linux; X11; TrebleDroid`, not Android — an `/Android/` test throttles
nothing there.

**The trace, not the profiler (14:20).** With rAF paced and 363 of 380
animations gone the tablet's main thread was still 96% busy and only 22% of it
script. Chromium's `Performance.getMetrics` gave the split (task 96%, script 18%,
layout 7%, style 4%) and hiding every canvas and video changed nothing; a 3 s
`Tracing.start` with `devtools.timeline` + `.stack` + `.invalidationTracking`
gave the names: `ProxyMain::BeginMainFrame` 66% (my own pacing wrapper was
re-arming a real rAF per skipped frame — #1413f), then, with that fixed, 55
frames and 47 paints a second driven by `LayoutInvalidationTracking @
paintFeed` — 3,000 invalidations in 3 s from the SCRIPT view re-dressing every
row of a 300-row feed on every poll. Recipe worth keeping: aggregate `X` events
on the `CrRendererMain` tid by name; count `*InvalidationTracking` events by
`args.data.stackTrace[0]`.
