---
name: sfx-guy-and-crystal-cabinet
description: "#835/#836: SFX Guy per-voice quip databases + sfxguy_rate slider; the 🔮 crystal cabinet popup and the desktop agent:del bridge"
metadata: 
  node_type: memory
  type: project
  originSessionId: 76060765-7250-4692-8400-1a3022b54df3
  modified: 2026-08-19T10:51:04.212Z
---

**SFX Guy (#835, 2026-08-18)** — the drop seat is a CHARACTER: faded NASCAR
shirt, penny loafers, thick country accent, Dale Earnhardt devotion, a
one-upper streak. Three parts:
- Quip shelves are PER VOICE: `data/sfxguy_quips/<voice_id>.json` (legacy
  fallback `data/sfxguy_quips.json`), 30 seeds baked into app.py
  (SFXGUY_SEED_QUIPS incl. the duck-l'orange bit). API:
  `GET /api/sfxguy/quips?voice=` (default = current drop_voice; returns
  `databases` list), `POST {text|texts, voice?}`, `DELETE {text, voice?}`.
  A shelf materializes on first save; changing drop_voice swaps his whole
  vocabulary. unrepeated() key is `sfxguy-quip-<voice>`.
- Interjection engine lives in speak_turns' coalesced loop right after the
  #833 sting insert: gated on `sfxguy_rate` (DEFAULT_DJ 40, 0–100 slider in
  control_specs "third" section = per-host-statement probability), drop_voice
  set, and `item["who"] in (dj, cohost, third)` — never over callers. Renders
  whole-cloth via voice_render_any(who="drop"); #821 replay cache makes
  repeats 0ms. Pipeline proof: `air` events "the SFX guy pipes up: … (#835)".
- Persona rides the dj_banter prompt next to seek_verdict (~25495): hosts
  react to his heckles, set up punchlines, call out the one-upping;
  seek_verdict raised 0.2→0.35.

**His POSITION is committed now (#1330/#1333, 2026-09-13).** The cadence gate
and the random roll always happened at ASSEMBLY time, but that was never
recorded anywhere — so the script had to work out afterwards where he landed
from a timestamp, and he kept turning up as one half of the worst
out-of-order pair. He is written into `data/script_ledger.jsonl` with his own
`(block, ord)` at the point the running order is final and nothing is audible
yet, and it is never rewritten. The script AHEAD of the needle therefore
already shows where he drops in. Measured: 23 of 23 SFX rows inside their own
conversation. See
[script-ledger-and-the-reading-order](script-ledger-and-the-reading-order.md).

**Crystal cabinet (#836)** — the desktop 🔮 (crystalBtn) opens
`#crystalPopup`: draggable header, CSS `resize: both`, per-crystal card with
ON AIR toggle, strength slider (5–100), album-mind chips (from
/api/speakbox/minds, saved via POST /api/crystals {id, minds}), tint text,
💥 shatter, and running extractions at the bottom. Button stays lit while
any crystal is on. NEW BRIDGE ROAD: `api.del` in preload.js →
`agent:del` in main.js (DELETE with JSON body) — exists now for any UI work.
NOTE: /api/crystals GET+POST are defined TWICE in app.py (~31264 #815 system
wins registration; ~32006 is the dead old SongSight pair) — edit the first.

**Observatory + tinted cast (#820–#823, 3753efb)**: 🌆 in the cabinet head
= the Influence Observatory (hex CITY of the active crystal, one tower per
mind, cast pillars, live arcs per seed; crystal selector puts choice on
air). Feed: `_crystal_influence_note()` ring stamped at speakbox_quote's
success return + the SFX shed; GET /api/crystals/influence. SFX guy tint:
crystal ON → warp roll = max(sfxguy_warp, strength); all brews carry tint
+ a shard from a crystal mind. Cabinet cards show ONLY member minds ('add
minds' expander holds the registry, filtered). GAPS root cause (#823):
larder skipped writing whenever _OLLAMA_GATE was locked — with a never-idle
desk it NEVER refilled; now a shelf <2 queues its write behind the live
one; dialogue_reserve_target 4→6.

**Cabinet round 2 (#820–#825 second wave, c629683, 2026-08-18)**: the
reader tower (towerStart in desktop/renderer/renderer.js) is an
INTERLOCKED HONEYCOMB now — each storey a full hex-grid disc (spiral
axial spots, rings K≤8 picked so ≤34 storeys; cells tangent at spacing
S·√3, rotation.y=π/6 so faces mate), with pointer orbit (drag=turn,
wheel=zoom, shift/right-drag=pan, auto-spin until first touch). #823:
the branch under a crystal is artist-scoped — `sameArtist()` matches
mind id/name stems against crystal name/id + member-id prefixes
("alleninterface-bomb"→"alleninterface"); non-matching minds live in a
dim collapsed "⚠ different artists" fold. #824 overflow: `.cp-body`
min-height:0 + overflow:hidden, head ellipsises, #cpTower flex 0 1 auto
max-width 52%. #822: written-only ad spots get "▶ Cut it & hear it"
(POST /api/dj/ads/{id}/recut with air:false returns {url}; player
injected inline with cacheHold duck) — in the web panel's Ads cache tab
AND the ad book. #820: dj_line gates model output with looks_english —
non-English → one English-rewrite pass → stock phrase.

**The sample forge (#838/#839, 97970a3, 2026-08-19)**: /samples
(\\10.89.1.125\QuickSwap via //exbox.local/quickswap) is READ-ONLY
twice over (fstab ro + compose bind ro) — every extract save silently
failed since #800. Writable root: `SFX_LOCAL_ROOT = data_path
("samples")` (share-visible at spark-agent\data\samples), and
sfx_folders() resolves names against SHARE first then LOCAL. Flow:
/api/samples/fetch (video:true → voice-lab downloads ≤720p mp4,
_snapshot_video BEFORE the lab's extract-and-delete rule) →
/api/samples/video/{id}?t=sig (sign key is "v"+job_id) for scrubbing →
extract {stage_only:true} cuts to a shelf and `_clip_words` (ffmpeg
s16le → wyoming_transcribe :10300) auto-names each cut from its words →
/api/samples/commit {items,folder} moves approved names into
SFX_LOCAL_ROOT/<folder> + rotation. Desktop popup: URLs MUST go through
desktopMusicUrl() (relative src on Electron = file:// = dead player,
the original "can't grab samples" bug); ASCII hexagon loader (sp-hex).
Voice-lab and the HA component are patched ON THE HOST (outside git,
.bak-836/.bak-839 kept); HA component changes need docker restart
homeassistant.

**Stings from the grab folder (#817, 9fe9e4c)**: `samples_grabbed/10hrTIKtok`
in dj.sfx_folders (/samples IS \\10.89.1.125\QuickSwap); 3,447 clips and
growing. sfx_list re-globs PER PICK (new files air immediately, no restart)
and past SFX_MAX_FILES=400 draws a fresh random sample per pick so the whole
folder rotates. Length gate = dj `sfx_max_seconds` dial (clamped 0.5–30; set
to 20 on 2026-08-18, was 5). Sting rows show in the booth as "The SFX Guy
(sting)".

Restart gotcha: `POST /api/service/restart` needs `{"name":"spark-agent"}`
— an empty `{}` is refused as "host-managed". See [voice-director](voice-director.md),
[panel-ui-debugging](panel-ui-debugging.md), [pine-inbox-workflow](pine-inbox-workflow.md).

**Inbox marathon #788–#804 (2026-08-18, commits 0941924/0d140e7)** — 15
requests. Standing systems that came out of it:
- SFX Guy v2/v3: hour cooldown ledger `data/sfxguy_said.json`; warp shed
  `_SFXGUY_WARPED` (ask_model, crystal-tinted, half REACT to the line just
  aired); news road `_SFXGUY_NEWS` (drudge_headlines + spicy take; sets
  `_RADIO["sfxguy_news"]` which dj_banter turns into the hosts' topic);
  dials sfxguy_rate 40 / sfxguy_warp 35. 151 seed quips.
- `looks_english()` gates the swath miner AND the air choke-point (#792 —
  Portuguese lyric aired verbatim). Unit-tested heuristic: diacritics >4%,
  foreign>english stopwords, en<5% on long lines.
- Lyric extraction is restart-proof: specs in `data/lyric_jobs.json`,
  `_startup_lyric_resume` (guarded: skips jobs alive in _LYRIC_JOBS —
  launch inside the 90s boot window once DOUBLED a job); pages found by
  TITLE; lyrics written into minds SONG BY SONG (`_mind_song`) + rolling
  reindex every 8; tag reader covers USLT/SYLT/TXXX/Vorbis/APE + .lrc/.txt.
- HOLD_REPLAY_STALE 600→3600 (#801: held lines were dying to the page).
- Theme owns swaths (#788): theme_owns_air + doc (or speakbox_search best
  doc) forces `only=` in speakbox_quote BEFORE the #834 crystal roll.
- Cabinet v3: /api/speakbox/minds/{rid}/sources + chunks?file=&q= (rows
  carry global index `i`), doc API resolves names across ALL minds (#795),
  three.js hex tower (agent serves /vendor/three.min.js; classic script
  tag dodges CORS-for-modules from file://).
- Desktop deck: booth popup resize:both + saved w/h in djTalkBox bag;
  terminal popup freezes while hovered; app player click-rescues autoplay.
