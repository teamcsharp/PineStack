---
name: floor-and-paced-air
description: "#1146: the round-level FLOOR lock + page-road pacing fixed out-of-order dialogue; memo book; caller tint strike/lesson - the invariants that must not be undone"
metadata: 
  node_type: memory
  type: project
  originSessionId: 67b7aa21-6be8-4549-b6e1-9c9c65053391
  modified: 2026-08-26T22:51:44.113Z
---

**#1146 (2026-08-26, f734ffd).** Root cause of "dialogue unfolding out of
queue": there was NO round-level speak gate — `_ANNOUNCE_LOCK` serialises
clips only, and on the page road nothing paced anything, so a banked
116s call "aired" in 9s, the next call launched, and three calls
interleaved line-for-line (measured in chat `air_at`, 15:23). Silence
watchdogs were also blind to coalesced rounds (`_SPEAKING` never bumped
there) and covered "106s of silence" mid-round.

**The standing invariants (do not undo):**
- `_FLOOR_LOCK` (near `_ANNOUNCE_LOCK`): held for a whole round
  (`speak_turns` wrapper → `_speak_turns_floorless`) or single line
  (`dj_speak` wrapper). Re-entrant per task. EXEMPT: `kind=="reply"` and
  `by_hand` — a person outranks the show (#206). `_floor_busy()` goes
  false past `FLOOR_STALE_SECONDS` 1500s (watchdogs re-arm on a wedge;
  matches `SEGMENT_LIVELY_CEILING`, raised 720→1500 because a paced
  round's wall time = build + air). `_floor_drop` stamps `_SPOKE_AT`.
  Watchdog readers: talk_quiet source, talk_watch, cover_the_gap, coord
  spot, dead_air_watch, lively, box_hold_watch drain.
- Page pacing in the coalesced loop: burst announced up to
  `PAGED_ANNOUNCE_EARLY` 38s before its air moment WITH an honest
  `broadcast_ms` (clients wait for it — this is what keeps the #998
  download window open); `_paged_settle` before EVERY exit incl. the
  recovery road; pause-aware (paused → no pacing; clips die to the
  resume cut). #776's scar stands: the wait only runs while delivered
  audio is provably still playing.
- Recovery (#767 amended): only the round's unaired TAIL re-airs in
  sequence; mid-round holes are DROPPED ("a hole reads better than a
  scramble"). Never re-air line i after j>i.
- Resume feed-cut: `_RADIO["voice_cut_ms"]` set on unpause;
  `/api/dj/voice` never offers older clips (#1138 fresh-start extended;
  booth history kept per #1117).
- Clients (need F5/app relaunch): single-flight polls with 20s
  self-expiring timestamp guards, ts+url enqueue dedupe, stream clips
  retry at the queue HEAD synchronously, panel got #998 lateness parity.

**Memo book** (`data/manager_memos.json`, keep 1000): every manager memo
banked or aired is archived once with uses/last ledger; banked rows
carry `memo_id` so the later TINTED airing updates its row (no twins).
`GET /api/manager/memos`, `GET /api/manager/memos/archive.md`, `DELETE
/api/manager/memos/{id}`. All I/O via `asyncio.to_thread`; a read fault
returns None and saves STAND DOWN (never clobber the book).
`ALT_GEN_MOST` 3→8, `ALT_GEN_WAIT` 900→1800 for en-masse commissions
(`POST /api/pantry/commission {"kind":"manager","count":N}`).

**Caller tint salvage**: a completed tint failing `call_tint_report` no
longer deletes the row. `crystal_tint`/`crystal_turn` take `lesson=`;
dj_banter retries once with the graded faults, then `_call_tint_strike`
reverts to graded plain (viable, `tint_tried` stamped so
TINT_RETRY_REST paces retints); `retire_rejected_call_entry` strikes up
to `CALL_TINT_STRIKES_MOST=3` before really retiring. Success pops
`tint_lesson`.

**#1147 (same day, 78f4834) — the GARBLE (clips mixed for ~1s) had five
mouths, all client/feed side; server logs were clean throughout:**
1. Lateness-drop advanced the queue WITHOUT stopping an element whose
   play() was pending → dropped clips sounded under the next (panel two
   alternating els; tune single el). Fixed: silence-before-advance +
   idempotent finish (tune) + handed/epoch guard on onplaying.
2. Desktop shell's injected volume script force-UNMUTED every element
   each ≤1s, defeating the #1008 solo gag → second broadcast copy in
   0.5–1.5s bursts. Rule now: the shell only ever ADDS silence
   (`__pineGagged`/`pineGag` aware; `pineShellMuted` marker for its own
   non-live mutes).
3. Tune players were DETACHED Audio objects — invisible to every
   querySelectorAll (solo gate AND shell gating). Now stamped
   `data-pine-live` and appended to document.body. The SAME CLASS of bug bit
   the SCRIPT view a month later, one boundary further out: its playhead scan
   ran `querySelectorAll('audio')` in the Electron chrome, which cannot see
   into the panel's `<webview>` at all — a clean 0%, never intermittent. See
   [the-chrome-cannot-see-the-panel](the-chrome-cannot-see-the-panel.md).
4. No feed epoch at boot → open clients straddled two schedules. Boot
   stamps `voice_cut_ms` like resume; `/api/dj/voice` returns `cut_ms`;
   clients flush queue + sounding clip past it; `djVoiceEpoch` orphans
   in-flight closures (zombie stallGuard/play-rejection retries were
   restarting dead audio — verified-review catch).
5. Only the burst road knew the page-air ledger; 15 other append sites
   stamped now+7s inside sold air → late→suppressed/garbled. ONE DOOR:
   `page_feed_append()` + global `_PAGE_AIR_UNTIL` (burst length + a
   chars/14 estimate for plain clips chains the stamps). REPLIES exempt:
   stamped NOW, clients unshift kind=="reply" to the head (#206).
Also: feed never OFFERS hopeless clips (grace = stream len / 5s sting /
20s line; list kept for booth history); clients pre-drop hopeless clips
before touching an element; panel hold path peeks (no shift/unshift, no
slot flip, ONE deduped timer, unducks while holding — #1146's 45s
announce lead had music stuck ducked between rounds); ffmpeg concat
requires returncode 0 + measurable length (corrupt RIFF zeroed pacing);
?br= sticky-miss (sliding 900s) stops WAV→MP3 mid-session flips;
_LOW_WANTED reprimes from LOW_CACHE names at boot. Desktop: webviews
reload once per real outage (2 failed probes + 60s cooldown) — deploys
now PROPAGATE to the app (they froze pre-fix code before); webview
popups denied → system browser (about:blank kept for PDF export).
Client changes need ONE app relaunch (selfSyncFromShare pulls new
renderer/main from the share) / F5; then outage-reload keeps them
current. jscheck.py trick: extract each `<script>` block + node --check.

**Known residuals (deliberate):** live-road phone ring bypasses the
floor (banked calls carry the ring in-clip); call archive keeps
dropped-hole turns on paper; `pantry_key` ignores fx/who (changing it
would orphan the whole pantry); quota double-fire window while a paced
round airs (floor serialises, doesn't dedupe); the paused-feed early
return carries no cut_ms (flush happens at resume); pineAirPause
resume-one drops a second held clip under overlap>0 (dormant at 0).

See [event-loop-starvation-watchdog](event-loop-starvation-watchdog.md), [dialogue-pipeline-diagnostics](dialogue-pipeline-diagnostics.md),
[hour-contract-two-truths](hour-contract-two-truths.md), [sfx-guy-and-crystal-cabinet](sfx-guy-and-crystal-cabinet.md).
