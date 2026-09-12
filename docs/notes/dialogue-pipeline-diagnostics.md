---
name: dialogue-pipeline-diagnostics
description: "How to diagnose Pine Box dialogue/segment gaps — /api/dj and /api/recording-room carry the telemetry; the served-path-vs-file trap; the keeper's block order"
metadata:
  node_type: memory
  type: project
  originSessionId: 972203c0-385f-4018-891c-5d597c362de3
  modified: 2026-08-21T02:42:07.318Z
---

Diagnosing "the DJs stopped talking" / "segments are never ready" on
spark-agent (`app.py`, ~108k lines, one file).

**The three endpoints that matter.** `GET /api/dj` carries `chat`,
`activity_log`, `dialogue_flow` (the gap telemetry: `ready`/`target`/
`render_waiting`/`blockers[]`), and `dialogue_flow.prep.yields` /
`.yielding`. `GET /api/recording-room` counts each road's
written/rendered/lines/ready/seconds. `GET /api/dj/pipeline?since=0` is
the glass — the real event feed, and the only place render timings show.

**`GET /api/recording-room/rows/{kind}` (added #992)** asks of each shelf
row the same questions `prep_render_line` asks, in the same order, so the
first `false` in the row IS the reason it has no audio. Reach for this
first when a road sits at 0 rendered — it is what found #993.

**THE SERVED-PATH-VS-FILE TRAP.** `_store_media()` returns
`{"path": "/media/<key>"}` — a *served URL*, not a filename. Handing that
to ffmpeg or to `Path(...).read_bytes()` silently fails. Use
`_media_file(path)` (added #993), or the older idiom
`VOICE_MEDIA_DIR / clip["path"].rsplit("/", 1)[-1]`. This cost every line
over `VOICE_MAX_CHARS` (800) its audio for a long time: the pieces
rendered, the engine was paid in full, and the result was discarded.
Adverts (~1000 chars) sat at 0 rendered while station IDs (~60 chars) in
the *same loop* finished — that asymmetry is the signature.

**The keeper's block order is load-bearing.** `pantry_keeper()` runs
finishing work (half-rendered rounds; written-but-unvoiced ad/ID reads)
BEFORE the banter loop, because every finishing block opens with
`if not pantry_window(): break` and the banter loop spends the window.
Within the rounds block, kinds take turns one row per lap with a *slice*
of the window each — walking all rows of one kind starves the rest. Both
orderings were bugs (#990, #991); don't "tidy" them back.

**`prep_yield()` must never be armed per-line.** `speak_turns` fires one
`_premake` per line, so anything that arms an 8s hold inside a live
render arms it N times per round and it never expires (#989 B1).

**The pantry IS a content-addressed render cache** — `pantry_key(text,
voice, engine)`, `pantry_put`/`pantry_get`, persisted to
`data/pantry.json`. (Older note here said no such cache existed; that is
out of date.) Always look up the pantry BEFORE any relief/engine gate — a
cache hit spends no engine, and gating above the lookup stops a round
harvesting audio it already owns.

**Restart strands in-flight rounds.** `larder_prepare` sets
`entry["preparing"]=True` and clears it in a `finally`, which does not
survive the process dying. `_larder_save` writes it verbatim and three
separate places skip a `preparing` entry for ever. `_unstrand()` on load
(#995) clears it. `data/larder.json` and `data/prep_shelf.json` are on
the share — read them directly to check.

**Capacity is the real ceiling.** XTTS on this box runs ~2.7–2.9x SLOWER
than realtime (~17s of engine time for 6.3s of audio). A 36-line round is
~15 minutes of exclusive engine. Fair scheduling makes every road
progress; it cannot manufacture throughput. `render_relief()` only
latches at 4.5x (a genuinely *sick* engine, not a busy one) — see the
long comment at `RENDER_COST_SLOW`.

Counting trap: with `stream_show: True` a whole round is COALESCED into
one clip, so "speaking" fires once per round, not per line. Don't read
voicing-vs-speaking ratios as loss.

Always read the LIVE settings (`GET /api/settings`) before acting on any
claim about a default. See [approvals-and-classifier](approvals-and-classifier.md).

Related: [voice-fidelity-engine](voice-fidelity-engine.md), [f5-tts-server](f5-tts-server.md),
[sfx-guy-and-crystal-cabinet](sfx-guy-and-crystal-cabinet.md), [pine-inbox-workflow](pine-inbox-workflow.md).
