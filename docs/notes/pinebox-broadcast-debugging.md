---
name: pinebox-broadcast-debugging
description: "Playbook for \"DJs not broadcasting out of nabu\" — which endpoints diagnose what, and what the meters actually prove"
metadata: 
  node_type: memory
  type: project
  originSessionId: 76060765-7250-4692-8400-1a3022b54df3
  modified: 2026-08-19T19:28:26.405Z
---

Terminology: the user says **"the box" / "the pine box" for whichever device
is the selected broadcast speaker** — since 2026-08-17 that is the NABU
(core device by decree; the PineVoice Wyoming unit is secondary). A
deliberately powered-off box is normal operation: flip the master switch
(`POST /api/dj/output {"box_talk": false}`) so the show stops knocking and
runs on the page; held clips replay when it returns and the switch goes on.

When the nabu box (Home Assistant Voice PE, `assist_satellite.home_assistant_voice_09f8a8_assist_satellite`, MAC **b4:0e:cf:2a:89:5f** on TacoNet) goes quiet:

**NEVER TRUST A HARD-CODED ADDRESS FOR IT — DHCP MOVES IT.** An older note here said .161 and warned .205 was "a different box". On 2026-08-20 that was measured false and cost hours of silence: .161 had no ARP entry at all and .205 carried the satellite's own MAC. Identify the box by **MAC**, and get its address from `/api/pinebox/diagnose` (`host`/`mac`) or `GET /api/pinebox/wire` — never from memory. #973 made `_wire_probe`/`nabu_device_alive` try every candidate (env NABU_PROBE_HOST → SATELLITE_HOST → the literal) because a probe that says "dark" is the switch that makes every self-healing rung STAND DOWN, so a stale address silently disables the whole ladder.

**Port shape tells you which fault it is:** 6053 OPEN = healthy; 6053 REFUSED but ping OK = IP stack up, firmware not running — HA has nothing to connect to, so HA restarts and the restart-button entity are both useless and it needs a PHYSICAL power cycle; ping TIMEOUT = off or off-network.

**HOST-REBOOT PLAYBOOK (#836/#837, 2026-08-19)** — a lilspark reboot
breaks FOUR things at once, each lying differently:
1. Nabu keeps a HALF-ALIVE ESPHome session: entities "available",
   media player "playing" with media_content_id None, play_media
   returns 200 and does NOTHING. No watchdog fires. Cure =
   `nabu_device_restart()` (button.home_assistant_voice_09f8a8_restart,
   drops ~20s, rejoins, audio resumes).
2. The iTunes library CIFS mount (//exbox.local/quickswap/Music/iTunes
   → ~/music/itunes, fstab `nofail`) silently doesn't mount; container
   /music/itunes is EMPTY, every indexed track 404s while the show
   keeps queueing. Fix: `sudo -n mount /home/ehm_eckx/music/itunes`
   (passwordless sudo works) THEN restart spark-agent — the docker
   bind is rprivate, a late mount does NOT propagate in.
3. voice-director wedges "deactivating"; lifeboat
   POST /restart/voice-director fixes it. XTTS dies with it.
4. TWO idle clocks kill revived XTTS: the agent's (#835 fix: ready
   transition stamps _XTTS_LAST_USED) AND the DIRECTOR's
   (engine_idle_clock reads _ENGINE_LAST_RENDER which direct :8770
   renders never touch — #836 fix: agent POSTs
   /director/engine/{eid}/rendered via _director_stamp, throttled 60s).
The ONE BUTTON: `_deep_repair()` = box_triage(fix) + deaf-device rung
(nothing verified audible 120s → zombie-stream stop + device reboot +
fresh needle + drain) + verified-audible verdict. POST/GET
/api/pinebox/repair, /api/pinebox/engines, /api/pinebox/engine
(deploy/terminate/bounce), /api/pinebox/act (device_reboot/music_kick/
drain/director_restart). Desktop: Agent status cell → 📻 Radio Triage
popup. The spoken rescue (#827) runs _deep_repair too. #837: POST
/api/radio-cache/span {lo,hi,label} cuts the broadcast rebuild for any
window (seals the open episode first); booth hang-up rows carry ⬇.

**THE TRIAGE NOW LEARNS (#880/#881)** — stop re-deriving cures by hand.
`GET /api/pinebox/learned` shows what the station knows;
`repair_fingerprint()` names the fault in tree-visible terms
(audio:none, shelf:jammed, device:accepts [only WITH audio:none],
device:unreachable, device:breaker, director:dark, engine:X_dark [only
the cast's engine — the other is deliberately unloaded under #866],
library:empty, routing:drifted); `repair_suggest()` ranks cures by
wins/losses (Laplace) × freshness; `_deep_repair` tries the top cure
FIRST then climbs; `repair_record()` writes the outcome either way.
Ledger at data/repair_learned.json, seeded with this session's eight
cures. `_run_cure` can do: device_reboot, engine_bounce,
lifeboat_director, restore_routing, shed_stale_shelf, music_kick,
piper_restart. Needs a human: drop_caches, remount_shares,
switch_writer. **When a NEW fault+cure is found, add it to REPAIR_SEED
so it survives a ledger reset.**

**THE SILENCE CATALOGUE (#842-#857, 2026-08-19)** — a full day of
"no broadcast". Ranked by how much airtime each cost:
1. **#856 the missing announce flag**: `_play_on_box`'s NABU branch sent
   play_media WITHOUT `"announce": True`, so every DJ line entered the
   MEDIA pipeline and REPLACED the record — measured: device went
   `playing`→`idle` and stayed. With the flag it rides the ANNOUNCEMENT
   pipeline (ducks 20dB, swells back). `bypass_proxy` must stay OFF —
   the device cannot decode our WAV natively (measured: nothing played).
2. **#854 the self-gag deadlock**: `_play_on_box` declines every fresh
   line while `_BOX_HOLD` is non-empty; `_replay_held`'s docstring
   admits "a genuinely unplayable head clip jams the shelf". 3 bad clips
   = permanent total silence. Now: 3 tries then release, and
   `shelf_is_stuck()` (90s no advance) yields the air.
3. **#855 poisoned routing ledger**: panel `djSetOutput()` auto-fired by
   djGo/djToggleSession POSTed the browser's stale selects with NO
   `system` flag → wrote music="here" into routing_operator.json as an
   operator choice; `_box_vigil` then replayed it on every box flap. The
   DESKTOP REBUILD button did the same with music="off" — so clicking
   rebuild when the radio died made it deader. #839's guard was dead
   code (read `music_to` from a ledger keyed `music`).
4. **#851 the oscillator**: engines are grandchildren of voice-director's
   unit → default KillMode=control-group meant every director restart
   SIGKILLed XTTS+F5. Plus the f5 LAUNCH cmd lacked `&` so deploy froze
   the director's loop 240s → agent's 45s timeout → lifeboat restart →
   cgroup kill → repeat. Fix: `KillMode=process` + `TimeoutStopSec=20`.
5. **#842 no fallback for named voices**: `actor_locked` REMOVED the
   piper rung, so a cast line with both clone engines down was LOST
   while the log lied "Piper included". Piper floor is now unconditional.
6. **#850**: piper_catalog awaited piper_voices with NO timeout (the one
   unguarded call site) and #842 put it on every render → hang. And the
   box road DELETED unrenderable lines (page road shelves them).
7. **#843 UMA wedge**: page cache eats the unified pool → engines hang
   mid-load, port bound, never answer. `drop_caches` + swapoff.
Device-side: the nabu's volume sitting at **0.3999 = its hardware floor
= HA volume ZERO** (silent), and the half-alive state (accepts announce,
plays nothing) — the tell is TIMING: announce returning FASTER than the
clip length means it was dropped; press `button.*_restart`.
Guards now on the host: `pinebox-uma.timer` (5min) and
`pinebox-engines.timer` (30s, restarts the director too, then falls back
to launching engines directly). Autonomous: `dialogue_watchdog` (#857)
runs _deep_repair when no host line has been VERIFIED audible in 7 min.

**Rescue ladder, all rungs (#827/#836/#839)**: L1 the agent's
`is_radio_rescue` in generate_answer — formal phrases (_RESCUE_RX) PLUS
short shouts ≤70 chars (noun regex radio/station/pine fm/broadcast +
mood where/down/dead/bro/fuck/fix/at…, music-order guard) → _deep_repair
with the verdict spoken back. L2 (#839): the HA custom component
(pinevoice-stack/home-assistant/custom_components/
spark_agent_conversation/conversation.py — ROOT-owned, edit via host
`sudo -n python3` runner, .bak-839 kept) — when all 3 POST attempts fail
AND the utterance matches its own _RESCUE regex, it calls the LIFEBOAT
:8099 /restart/spark-agent (X-Lifeboat-Key = the component's api_key),
waits for /healthz up to 75s, re-asks once; else speaks "the lifeboat is
restarting the station's brain — ask again in half a minute". HA must be
docker-restarted to load component changes. Verified live: "where the
station at" and "station bro" both trigger the deep repair through
/api/conversation/process.

**TWO entities on one device (#826)**: the satellite carries TALK, but
MUSIC plays on `media_player.home_assistant_voice_09f8a8_media_player`
(NABU_MEDIA_PLAYER) — "voice fine, records silent" = the media player
entity went unavailable while the satellite stayed up. box_triage has a
"music player" rung now (probes the state, climbs nabu_link_ladder when
dead). **Rescue words (#827)**: speaking "where is the radio station" /
"what happened to the network" / "reboot the radio" / "bring up Pine FM"
to the device (or POST /v1/chat/completions) trips `is_radio_rescue` in
generate_answer → box_triage(fix=True) + verdict spoken back; "play the
music and the DJs out of the device" trips `is_play_on_device` → routes
both to "both". **Monitor (#825)**: POST /api/dj/monitor {"on":true} —
while on, box-bound clips (solo lines, round bursts, stings) ALSO ride
the page feed and the panel keeps following the record clock, so the
full broadcast is judgeable on the page mixer with routing all-nabu;
"🎧 Monitor the air" button beside Reset levels; not persisted, resets
off on restart. Great debugging tool: turn it on to SEE box-bound
dialogue in /api/dj/voice.

**Wake words** (#787/#788): "hey DJ"/"hey LLM" are TEXT routers applied to
the STT transcript — the device only physically wakes on **"Okay Nabu"**
(stock microWakeWord list; custom words need reflashed firmware). Usage:
"Okay Nabu" → chime → "hey DJ, …". The pipeline is: DGX Spark pipeline →
faster_whisper STT → conversation.spark_agent (custom component, retries
3× through agent-restart windows) → POST :8096/v1/chat/completions.
E2E test without the device: HA token via
`docker exec spark-agent python3 -c 'import json;print(json.load(open("data/ha_token"))["token"])'`
then POST :8123/api/conversation/process {"text","agent_id":"conversation.spark_agent"}.

**Resilience layer (#805/#806, 2026-08-18)**: the LIFEBOAT — systemd
service on host :8099, stdlib, outside Docker: GET /status (no auth),
POST /restart/<container|voice-director|stack> with X-Lifeboat-Key =
SPARK_AGENT_API_KEY. Use it when spark-agent itself is down. The
voice-director runs under systemd (voice-director.service, Restart=
always); its PRESSURE VALVE (45s clock in the director) frees ComfyUI
<25G avail, unloads idle engines <18G, evicts ollama + anything
unloadable <12G — GET :8090/host/pressure. OLLAMA_KEEP_ALIVE=30m via
systemd override. CALLS root causes (measured 52/99 zero-turn): silent
`except: return []` around the round write + ask_model fragment-bin —
both now fall back to _fallback_call_script so a rung phone always airs;
ring moved after the script exists; calls joined the thin-draft rewrite;
rerun fuzzy leg exempts kind="call"; can_cut re-arm keeps caller
protection; call hold-clips get 3× replay window; the shelf drain gates
on satellite availability (was 237 hammer-sends/day at a dead entity).
Nabu drops = 2.4GHz RF (6 outages/102min in one day; enable the RSSI
diagnostic entity in HA; consider ESPHome api reboot_timeout 5min +
power_save NONE + static IP; real fix is AP placement).

**Talk continuity** (#795): HOLD_REPLAY_STALE is enforced now (stale held
clips go to the page, not re-aired); zero-turn calls log as never_aired;
the phrase gate skips host seats during calls; speak_turns binds its plan
locally (concurrent rounds were IndexError-killing each other via the
global _RADIO["plan"]).

1. `GET /api/pinebox/diagnose` (open read) — full rung list with cause.
2. `GET /api/debug/tasks` — the x-ray. `speak_turns` with no deeper await =
   waiting on XTTS renders in `gather(premade)` (normal, can be minutes);
   `speak_turns <- _play_on_box <- sleep` = a line is airing RIGHT NOW.
3. `POST /api/pinebox/initialize` (Bearer key) — idempotent recovery ladder,
   ends with an audible test.
4. `POST /api/dj/drain` (Bearer key) — replay hold-shelf clips now.
5. `POST /api/pinebox/recover` — reloads the ESPHome entry + restarts agent;
   last resort is power-cycling the device itself.

**The 2026-08-17 outage & the #793 ladder**: "satellite is unavailable"
while the device still PINGS = HA's ESPHome session died; reload_config_
entry returns 200 and fixes nothing; `docker restart homeassistant` is
what fixes it (HA is NOT in the compose stack — /api/service/restart
refuses it as "host-managed", but the docker-socket-proxy on
127.0.0.1:2375 restarts it fine). Then recover releases the held breaker
backlog (it PRESERVES held clips and restarts the agent; playout ratio
returns to 1.0 as clips drain). This whole climb is now AUTOMATED:
`nabu_link_ladder()` in app.py — verify reload 20s later → TCP-probe the
hardware (RST = alive, only timeout = powered off → stand down) → HA
restart on a persistent budget (data/repair_stamps.json: 30-min cooldown,
4/day — survives the agent restarting itself) → wait ≤240s for the entity
→ recover. Fires from satellite_selfheal's dead-link branch only (the
#712 stall path is untouched — never restart HA when the link is alive,
it severs live streams and causes the stutter loop). Manual:
`POST /api/repair/nabu-ladder` (`{"dry_run":true}` shows every guard).
Kill switch: env NABU_LINK_ESCALATION=0. Probe addr: NABU_PROBE_HOST.

Meter honesty (#784): nabu acks announces instantly, so wall-time playout
ratio reads 0% and gets rescued to 100% purely by "entity state is valid" —
a wedged Voice PE (accepts announces, plays nothing, shows idle) passes every
software check. `last_ratio: 0.0` in `/api/dj/state` box block is often just
the latest unrescued sample, not an outage; `silent_for` resetting every
~20s means announces are being verified continuously. Only ears at the box
prove audio. XTTS server: loopback-only `127.0.0.1:8770` on nabu (check via
SSH, not LAN curl — LAN refusal is normal). See [xtts-clone-server](xtts-clone-server.md),
[pine-inbox-workflow](pine-inbox-workflow.md).

**"hey DJ" wake word (#807, 2026-08-18)**: a REAL custom openWakeWord
model trained on the DGX — `~/openwakeword-custom/hey_dj.tflite`, served
by the `openwakeword` container on :10400 (wyoming-openwakeword,
restart=unless-stopped). HA Wyoming integration added via REST config
flow; the "DGX Spark" pipeline has wake_word_entity=wake_word.openwakeword
wake_word_id=hey_dj. Quality: 80.3% detection @0.5 threshold, ~3 FP/h on
dense noise (tune threshold in HA if needed). LIMITATION: the Voice PE
firmware 26.6.0 hard-sets use_wake_word:false — on-device microWakeWord
only — so the PHYSICAL device still wakes on "Okay Nabu" until a custom
ESPHome reflash (options in ~/voice-director/logs/hey-dj-wake.md;
upstream: home-assistant-voice-pe#334). Any HA-STREAMING satellite on
that pipeline wakes on "hey DJ" today. Retraining kit kept at
~/oww-train (22GB): raise n_samples in hey_dj.yml, rerun 08_chain.sh,
convert_manual.py (onnx_tf is broken on aarch64 — manual converter is
mandatory), copy + docker restart openwakeword. HF downloads on this box:
use ~/oww-train/pget.py (segmented curl) — wget/hf_hub stall at 0 bytes.
- ALWAYS-BROADCAST scan (#818): Nabu quiet = music_to 'here' (browser-only); fix music 'both'. DEEP ROT caught live: Nabu playout verification is PAPER - _play_on_box fabricates airtime + paper-verifies via entity-online while media_player sat idle 30min; every watchdog trusts the forged _BOX_LAST_OK. BUILD NEXT: verify by polling media_player into 'playing', persist stamp, ON-AIR WATCHDOG loop (initialize->ladder->recover->HA page on no VERIFIED audio in N min). Also 178 corrupt-WAV TTS drops overnight (leading zero bytes vs RIFF; stopped post-restart - watch).
- #807 (2026-08-18): REPEATED DIALOGUE root cause — the coalesced-burst
  playout verdict read the SHARED _LAST_PLAYOUT meter, which any concurrent
  ack/sting overwrites mid-burst → aired bursts scored as misses → shelved →
  replayed = whole conversations heard twice (amplified when #801 raised
  HOLD_REPLAY_STALE 600→3600). Fix: trust _play_on_box's own verified
  non-empty return unless the meter still holds THIS clip's key. Purge tool:
  POST /api/dj/hold/clear {"older_than":0}. NOTE: purge right after restart
  can hit before box_hold_watch loads the shelf from disk — check held count
  after. Lesson: any shared "last playout" meter is race-prone; pin verdicts
  per clip.
- #814 (2026-08-18, 97040af): THE TRIAGE TREE — `box_triage()` /
  POST /api/pinebox/triage: show (resume if FM memory says on) → HA → entity
  → `_wire_probe(NABU_PROBE_HOST)` tri-state (a REFUSED port = alive!) →
  branch: session wedge→link ladder; alive+linked→restart button; DARK→
  route music+voice 'both' via self-POST /api/dj/output + `_box_vigil()`
  (60s wire watch → selfheal + booth line on return). Briefs the booth with
  real findings via dj_banter. #810 watchdog ends in it. Total-outage
  playbook: device 100% packet loss + show off → voice 'both' + dj/start =
  audible on page/app immediately; the vigil catches the device's return.
  2026-08-18 outage resolved itself: Nabu rejoined (power/RF), tree verified
  all layers healthy live.
- #824/#825 (2026-08-18, f28a3e4/d554f84): the SELF-HEALING is complete.
  Triage rungs now: show → HA → entity → device-on-wire (reboot button only
  after >600s verified-silent) → DIRECTOR (dead :8090 → lifeboat restart via
  `_lifeboat_restart`/`_director_post`) → ENGINES (xtts/f5 health →
  `_director_post` deploy). Director's LAUNCH gained a real f5 entry (was
  "external": killable, never startable — every f5 death collapsed the
  fallback chain). `_xtts_bounce_maybe`: healthy-on-paper XTTS failing 3
  renders/10min = wedged → terminate+deploy, 15min cooldown. Revive evicts
  the WRITER model when standins weren't enough (<30G). Recurring-silence
  catalogue for future me: engines OOM-killed (load needs ~40G transient),
  f5 dead+unstartable, wedged xtts, larder starvation, gates-drop-to-silence,
  music routed page-only + broken page player, raced playout meter, AND
  (#826, c3f83eb) THE STING SCAN: sting_due() walked the 3,447-file CIFS
  grab folder + probed durations SYNCHRONOUSLY in the event loop on every
  roll — healthz timed out, endpoints took 18s+, announce pacing stretched,
  "the station is dead". Pool cached now, refreshed off-loop per minute.
  LESSON: any per-line hot-path touch of /samples (CIFS) or fresh probe work
  must ride asyncio.to_thread + a cache. Music rides 'both' since 2026-08-18
  evening (operator demanded wall-to-wall).
- #830/#831: idle-but-deaf wedge (device accepts announces, plays 0%, entities idle) — HA restart + session rebuild DO NOT fix it; the DEVICE reboot does. Remote path now exists: button.home_assistant_voice_09f8a8_restart (was a disabled diagnostic entity; enabled via websocket config/entity_registry/update with disabled_by:null — script pattern in scratchpad enable_entities.py; docker cp into homeassistant + exec). Press via /api/services/button/press; device drops ~20s and rejoins. ALSO: #822 proof must accept EITHER nabu entity moving (media_player 'playing' for music, assist_satellite 'responding' for announces) — watching only the media player scored every voice line as a miss and silenced the station (#830). No WiFi-signal sensor exists on fw 26.6.0.
- #810 (2026-08-18, commit 3365b5c): the TODO is DONE — `onair_watchdog()`
  (startup loop): FM on + box_talk + voice→box and _BOX_LAST_OK stale >10min
  → selfheal → nabu_link_ladder → `nabu_device_restart()` (presses
  button.home_assistant_voice_09f8a8_restart, env NABU_RESTART_BUTTON,
  30-min cooldown). FM OFF now releases the ollama writer model
  (keep_alive 0) via `_fm_off_offload()` in dj_stop. Writer model switched
  to qwen3.6:35b-a3b (MoE, ~75s/round warm — obeys avoid_reruns unlike the
  4B; /api/model to switch; hf.co/unsloth/Qwen3.8-27B-GGUF:Q4_K_M pulled as
  the dense alternative). "Station quiet" 2026-08-18 root cause: user set
  music_to='here' via the Music dropdown while their app player was stuck →
  music audible NOWHERE; fixed music_to='both'. SFX stings now also draw
  from `samples_grabbed/10hrTIKtok` (dj.sfx_folders; /samples IS the
  \\10.89.1.125\QuickSwap mount, read-only, non-recursive per folder,
  ≤4s cap).

- #1156 (2026-09-02): the firmware-down shape (ping OK, 6053/80/3232 all refused) now has its own branch — `_wire_probe_detail`, route-around + vigil-on-LISTENING + operator page; the ladder stands down. Read `/api/pulse` before blaming the box. See [pulse-library-and-firmware-down](pulse-library-and-firmware-down.md).

- **2026-09-11, "no dialogue out the radio" — ASK `GET /api/pinebox/status` FIRST.**
  It answers in one sentence, in the station's own words: `cause`, `spoken`,
  `steps`, plus a per-rung `checks` list. Here it said *"The Pine Box master
  switch is OFF, so the station is not calling it — whatever the DJ voice
  picker says"*, with every other rung green and
  `/api/pinebox/speaker` adding *"nothing on the device explains silence"*
  (satellite idle, reachable, 55%, unmuted). That is the whole diagnosis;
  reading route flags, feed states and listener reports by hand first was
  wasted work. **`box_talk:false` persists in `data/routing.json`**, so it
  survives restarts and "it worked yesterday" proves nothing — read that file.
  Cure: `POST /api/dj/output {"voice":"box","reply":"box","music":"both",
  "box_talk":true}` (this is also the ONLY route-setting door — there is no
  `/api/dj/route` or `/api/radio/route`). Setting `voice` to box/both flips
  `box_talk` true on its own unless `system` is set. Confirm with box-aired
  rows in `/api/dj` `chat[].aired == "box"` — they took ~140s to appear.
  `POST /api/orchestrator/policy {"does":"drive:none"}` (#1178) is the
  matching door for clearing a standing drive.
