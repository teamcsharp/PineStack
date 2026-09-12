---
name: resume-reel-and-shelf-burn
description: "#1151: shelf_take burned unheard callers (the resume dead-air root cause), the page-gap arithmetic max(0, R−S), pantry-key miss causes, and the resume reel"
metadata: 
  node_type: memory
  type: project
  originSessionId: 21948932-a31d-4dd3-9e25-119ba26127d8
  modified: 2026-08-30T11:01:36.146Z
---

**Resume dead air, root-caused 2026-08-28 (#1151, 3-agent scan + live
capture):** a caller's 6.6s line rendered 37.8s ON AIR (trace.render.ms)
after a days-long pause. Chain: `shelf_take` refused caller rows >24h as
"burnt" (caller NOT in `SHELF_REUSABLE` → can never claim the 72h repeat
exemption) and its tail-trim — the only `_SHELF` rebind of five ignoring
#1075 — deleted 84 unaired calls (−6253s) in one take; `pantry_burn`'s
clip sweep collected 739 orphaned takes 6s later. `hours_ready` counted
stock the picker was committed to refusing (no age term in
`dialogue_row_ready`; `shelf_take` has one).

**The page-gap law (memorize this):** a round airs in pages of 2/4/8/8
turns (`_batches` in speak_turns); TTS is pipelined (`premade`, gate=2
station-wide) but the page CONCAT is serial-inline. **Dead air at a page
boundary = max(0, R − S)**: R = next page's render+mix wall time, S =
current page's spoken length. All-pantry-hits → R≈concat≈0 → seamless.
Leads (7s `VOICE_BROADCAST_LEAD_MS`, 38s `PAGED_ANNOUNCE_EARLY`) cancel
out — raising them never fixes gaps. Inter-round ~100s holes = write+
render latency unmasked: the floor is taken BEFORE rendering (blinds
cover_the_gap/talk_watch/dead_air_watch via `_floor_busy`), and resume
re-armed `_LAST_SAID` to zero at the moment it emptied the feed.

**#1151 invariants:**
- `shelf_take`'s age-refusal and tail-trim both gate on
  `resort_may_drop` — an unaired row is NEVER "burnt" or shed.
- `caller_hello_for(name)` — prep AND air draw the hello
  deterministically by caller (was: prep `CALLER_HELLOS[0]`, air
  rotating → guaranteed miss on every prepared call's first line).
- `_banter_air` keeps a banked caller's held voice when the entry's
  takes are rendered in it (the #913 health redraw re-keyed every take;
  playing a WAV needs no engine).
- All-hits rounds collapse to ONE page (≤150s; else pages of 8).
- Pause stamps `voice_cut_ms` going IN (+`_PAGE_AIR_UNTIL=0`), and the
  paused /api/dj/voice branch carries `cut_ms` — pages flush promptly.
- Resume seeds `_LAST_SAID = now − (talk_quiet_limit()−20)` (playout
  clock stays now per #1120) + `banter_due=0`.
- #1150's freshness shift clamps to `min(now, at+slept)` (was stamping
  pause-written rounds into the future); larder contract clause
  (`_larder_current`) also gets the paused+`row_unaired` protection.
- **The resume reel**: `reel_tick()` (coordinator paused branch, beside
  workshop_tick) welds the readiest banked round's takes
  (`entry["takes"]` → pantry paths → `_call_concat_blocking` + beats)
  into ≤150s, stores via `_store_media`, protected in
  `_protected_media_keys` (`_REEL["media"]`); `reel_open()`
  (fire_and_forget from `radio_pause_set(False)`) airs it as one stream
  clip via `page_feed_append`/box, writes chat rows source="reel",
  `talk_said_now()`, pops the source larder entry.

**#1154 — the mystery pauses (2026-08-30):** the assist satellite's
transcripts stitched ambient/broadcast speech onto "Pause the radio…"
and the spoken-intent road matched it mid-ramble → the station paused
ITSELF (found via conversations.jsonl: "…This is the beauty of bigger
power when it comes to marketing", "…Yeah. Push it."). Rules now in
`station_intent`: destructive intents (pause, off) require an EMPTY
residue after stripping the matched phrase + filler words — a wrapped
command is refused and logged; start/unpause stay permissive (spurious
start = the wanted direction). `radio_pause_set(on, why=)` — every
caller attributes itself; `paused.json` carries `why`; the pipeline
"OFF AIR/BACK ON AIR" lines say "asked by: …". If a pause is ever a
mystery again, read paused.json's why and grep conversations.jsonl.

**Pantry-miss taxonomy** (a "prepared" round rendering live): text
changed (hello mismatch FIXED; retint `_dialogue_audio_drop`; freshen on
repeat-detect), voice changed (air redraw FIXED for banked; recast),
engine changed (#989 stand-in orphan — takes stored under the standin
engine can never be found). `pantry_key` = sha1(engine\0voice\0text).
Weld ceilings: ~165s box (`ANNOUNCE_TIMEOUT` 180), ~320s page (stall
guard 360s). See [floor-and-paced-air](floor-and-paced-air.md), [orchestrator-judgment-book](orchestrator-judgment-book.md),
[dialogue-pipeline-diagnostics](dialogue-pipeline-diagnostics.md).
