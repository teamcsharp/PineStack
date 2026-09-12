# Working notes

The operating knowledge of the station, kept alongside the code for the life of the
project. Each note is one thing that was learned the hard way: what was measured, what
turned out to be a lie, which diagnostic cannot be trusted, and what the fix actually
was.

They are listed here roughly in the order they were learned, which lines up with the
eras in [HISTORY.md](../../HISTORY.md). Notes link to each other freely.

The header of each note carries its kind:

- `project` — ongoing work, goals and constraints not derivable from the code
- `feedback` — a standing rule from the operator, with the reason for it
- `reference` — a pointer to something outside the repository
- `user` — who the operator is and how they work

A note reflects what was true when it was written. Where one names a file, a function or
a flag, check it still exists before acting on it.

---

- [Pine inbox workflow](pine-inbox-workflow.md) — "inbox" = resolve data/pine_requests.md via implement → restart → POST resolve with Bearer key
- [spark-agent environment](spark-agent-environment.md) — slow SMB share: work on a local copy of app.py; git safe.directory; imageio-ffmpeg; vendored three.js
- [PineVoice deploy paths](pinevoice-deploy-paths.md) — SSH works; which container is bind-mounted vs needs a rebuild; what is and isn't in git
- [yt-dlp extraction gotchas](ytdlp-extraction-gotchas.md) — ffmpeg filename/PATH trap, ranges, js_runtimes dict, cookie/client interaction, verified live
- [Approvals and the classifier](approvals-and-classifier.md) — "auto approved" in chat changes nothing; allowlist vs safety classifier, and what each blocks
- [Voice fidelity engine](voice-fidelity-engine.md) — /verify + /reference/score; identity cosine is NOT comparable across clip lengths (duration ladder); XTTS vs F5 numbers
- [F5-TTS server](f5-tts-server.md) — second engine on :8772; the ≤12s reference-clipping trap; HF Xet hangs on this box
- [XTTS clone server](xtts-clone-server.md) — lives in reachy-gateway not the compose stack; reachy_restart is how new code loads; errors-as-200
- [Pine Box Desktop launcher](pinebox-desktop-launcher.md) — runner cache in %LOCALAPPDATA%, direct electron.exe launch, ELECTRON_RUN_AS_NODE trap; stale-runner = old main.js until relaunch (#1148 white-popup cause); /export/kit window carve-out
- [Pine Box broadcast debugging](pinebox-broadcast-debugging.md) — diagnose/initialize/drain/recover endpoints; what the playout meters do and don't prove
- [Panel UI debugging](panel-ui-debugging.md) — headless Edge screenshots + CDP geometry probe; inline-relative-kills-sticky trap; the deck (#djBar) design contract
- [Voice Director](voice-director.md) — engine bench (ENGINE_REGISTRY), role pinning, characters+feeling via /feel, benchmark, OpenAI /v1/audio/speech for OpenWebUI/Hermes
- [openWakeWord training](openwakeword-training.md) — ~/oww-train pipeline on DGX; HF-CDN-stalls-use-pget.py; onnx_tf dead on aarch64 → convert_manual.py; hey_dj.tflite live on :10400
- [Dialogue pipeline diagnostics](dialogue-pipeline-diagnostics.md) — /api/dj carries the gap telemetry; the larder is TEXT-only so "prewritten" rounds still pay full TTS
- [SFX Guy + crystal cabinet](sfx-guy-and-crystal-cabinet.md) — per-voice quip DBs + sfxguy_rate slider; 🔮 popup, agent:del bridge, duplicate /api/crystals routes trap
- [Orchestrator dead wiring](orchestrator-dead-wiring.md) — the desks were sound but unreachable; ask "called / runs / changes anything" before reading logic
- [Parallel session + commitment ledger](parallel-session-commitment-ledger.md) — a second session edits app.py; dialogue_stock_items is the ONE inventory; re-pull before every patch
- [Hour contract: two truths](hour-contract-two-truths.md) — panel red = fresh famine, desk = real holes (2.35× oversubscribed); #1134 uncovered field, ladder-vs-scorecard reconcile, ad tint-verbatim fix
- [Studio guest feature](studio-guest-feature.md) — guest rides the THIRD seat (#568); "guest" schedule kind (#1135) airs the interview, live-only, banter fallback
- [Event-loop starvation + watchdog](event-loop-starvation-watchdog.md) — unpause silence root cause, FIXED #1142 (four memos; spoken_for stays uncached); spark-agent-watchdog exists; py-spy dump method
- [Floor + paced air](floor-and-paced-air.md) — #1146 _FLOOR_LOCK round gate + page pacing (out-of-order fix); memo book; caller tint strike/lesson; #1147 the five garble mouths (leaked elements, shell unmute war, detached tune players, boot feed epoch, one append door)
- [Public broadcast road](public-broadcast-road.md) — #1149 funnel→8097 public door (same loop!), music ?br= + music_lo cache, retime window-min anchor, listener unpause (wake-only), stall hunter + _chunk_save/dialogue_flow_state fixes
- [Orchestrator judgment book](orchestrator-judgment-book.md) — #1150 pause-honest clocks (larder 24s/min bleed fix, slot "banking" verdict, retint spares short roads), judgment ledger + road factors/lessons, pause workshop, 🕸 logic graph + dial
- [Resume reel + shelf burn](resume-reel-and-shelf-burn.md) — #1151 shelf_take burned unheard callers (resume dead-air root cause); page-gap law max(0,R−S); hello/voice pantry-key misses fixed; pause stamps cut going in; the resume reel; #1154 mystery pauses = mic hearing the show ("pause the radio" mid-ramble refused; paused.json carries why)
- [Comfy doctor](comfy-doctor.md) — #1152 ComfyUI under systemd + data/comfy_kick restart bridge; venv needs --break-system-packages; comfy_doctor troubleshooter, chat intent, 🩺 auto-opening console
- [Services steward](services-steward.md) — #1153 services_census (whole stack incl. vector guides), steward census→repair→re-census, hostsvc-kick bridge (ollama), xtts autofix via :9010, chat ask + spoken restart commands, 🏥 console
- [Pause banking + records underneath](pause-banking-and-records-underneath.md) — #1155 pause banked nothing after hour 5 (desk-bound finishing, larder starved, dead news counted); Records-first off + torrent = record loop queued on the floor (no music); phone clock takes the bank first
- [Pulse, library road, firmware-down Nabu](pulse-library-and-firmware-down.md) — #1156 the 2026-09-02 outage: CIFS-over-Wi-Fi crawl + sync saves starved the loop (watchdog storm); Nabu ping-OK/all-ports-refused = power cycle; /api/pulse names blockers, music_hot shelf, wire detail probe, route-around cure; json holds the GIL
- [Pine Box Gazette](pine-box-gazette.md) — #1019 hourly newspaper off the station's log (hermes-paper-agent contract in-process): desks, check codes, editions on disk, 📰 window, chat commands, recap tie-in; paper_write uses call_ollama not ask_model
- [Rhyme variety, the 10s rule, the calls](rhyme-variety-flow-calls.md) — 2026-09-08 night: pine_rhyme (the crystal's rhyme families); the writer landed on furniture because of the ANCHOR FLOOR not the prompt; 8 lines aired 100+ times because continuity was tried before gold; 29% of calls vaporized via the 2/4/8 page ladder
- [Rejection deep scan + the stack](rejection-deep-scan-and-stack.md) — 2026-09-08 night: the hint was lying (1,205 of 1,884 suggestions not rhymes), the near reading, read-plain passages, the queue drains itself; and the measured bottleneck: the deep tint lane at 8-12 rounds/h against 44 asked
- [Tint yields to the air](tint-yields-to-air.md) — #1063/#1064 the 2026-09-06 silence and the crystal rule: hold ON by default, "meaning" grade, tint lane, 3 asks per line, every road rapped (SFX guy, continuity, responses); how to read /api/tint; settings.json can pin an old default
- [System2 hand-off and switch](system2-handoff-and-switch.md) — #1068-#1070 (2026-09-08): the Codex leftovers (uncommitted, vendor/ required), the rhyme-assist loop stall that restarted the station, System2 now the default engine with fallback + legacy_keepers dials, continuity 1h rest, reuse-rest floor, Rhyme Cloud; Bash tool hangs here (PowerShell + scp + host git)
- [Request book, lanes, strikes](request-book-lanes-strikes.md) — #1079-#1088 (2026-09-08 am): data/pine_journal + /journal + 📖; one Ollama slot again (OLLAMA_NUM_PARALLEL=1, OLLAMA_LANES=1; two slots measured 0.96×) + deploy --recreate; tint gate = waiting depth lanes+3; strike cap (12) + fault memo; cacheable prompt prefix; evaluator reconciliation done; cupboard fill-rate scan; agents die on the session cap → work by hand
- [Rejection queue: making it amiable](rejection-queue-amiable.md) — 2026-09-09: the panel's "623" was a running event tally (the real queue was 174); the biggest fixable block was the gallery's INVENTED TITLES read as names (interior-capital had no dictionary check while sentence-openers had two); the rhyme block is genuine (near reading rescues ZERO); stored verdicts go stale so the queue lied about why
- [The gold freeze (#1157)](gold-freeze-1157.md) — 2026-09-09: the retirement desk had NEVER recorded a row because resort_may_drop returned ABOVE retire_may; six roads deleted rhymed work unasked (shelf_take's caller burn was the big one); an EMPTY audit trail is not evidence; the keep is forever, not a date; larder = 69 kB per round
- [Render is slower than speech](render-is-slower-than-speech.md) — render = 2.97 + 1.05 × audio; the marginal term is ABOVE ONE so continuous live-rendered talk is impossible; only the bank can fill a hole; shorter lines make it worse; 4 phrases in 5 are already back to back
- [The station's register and swearing](station-register-and-swearing.md) — NOTHING in the code blocks swearing (31 gates audited, zero filters); the operator's curse prompt reaches the CHAT agent only (#983), and _register was paper-only; the grader is indifferent (7/10 vs 7/10)
- [Repertoire, dead air, LCD](repertoire-dead-air-lcd.md) — 2026-09-08 pm standing rules: never silent (sfx_fill_gap in both watchdogs + cover), tinted rounds keep 96 h (keep_until, larder_trim, row_innings evergreen, purge spares), LCD shows only the spoken line; rejections census (fragments = notes, own_material roads, repair_hint, supersede); the retirement desk (retire_may gate on every deletion road, per-type rules, /cupboard/retire, Pine Box card, life timers); evening: rhyme_added transformation rule, "Approve as written" (lab kind accept), the orchestrator's reflection (reflection_clock → crystal_operator_refinement), gold bars first in sfx_fill_gap + gold_harvest_entry; late: docs/RapAssembly.md + the 🎛 RapAssembly 3js view (/api/rapassembly; headless probe via cdp-probe.js), the evening's contract folds (rhetorical negation / inner question / station boilerplate / descriptive opener) + the re-grade sweep - THE QUEUE IS THE BACKLOG, check last_at vs deploy times first; desktop relaunch needed for renderer/main.js changes; test_sfx_pool_warm needs the long TEMP path
- [Dead air and staleness, measured](dead-air-and-staleness-measurement.md) — read gap_log/air_log BEFORE turning a knob; the unreachable elif, the one-bar filler, the 8-phrase back-channel pool, and _room (not budget_plan factor) as the real bar-length cap
- [Director's room + seeded conversation](director-room-and-seeded-conversation.md) — 2026-09-10: caller candidates written-but-unrendered (load 0.997), the k=1 theme pin = 94.7% one doc, A:-only swaths = 82% host airtime, blend_script unreachable since #1070, two lying diagnostics, the 🎬 room
- [The Library (manuals shelf)](the-library-manuals-shelf.md) — #1158 /samples/Manuals auto-assimilated; routes are /api/manuals (NOT /api/library); only documentation may open the shelf; compare PDF words not chars
- [Silent station: the needle and the stores](silent-station-needle-and-stores.md) — unbounded await _record_talk pinned the needle 21 min (elapsed>>length, remaining 0, playing true); 7.5 GB of store with NO retention + a lock-taking hot read froze the loop 25% of the time
- [Running order vs the clocks](running-order-vs-clocks.md) — #1160-#1165: the plot term orphaned the whole cupboard every act; the 25s quiet hatch made the sheet advisory; the rescue door serves only 3 roads; banter is the LARDER; ask director_why's census FIRST
- [Gazette set to publishing rules](gazette-publishing-rules.md) — #1158: no `lang` = hyphens:auto inert (and no dictionaries in Electron/headless anyway); the containment pass; paper-probe.cjs measures clipped/escaped/broken
- [Which pile a road lives on](which-pile-a-road-lives-on.md) — #1165/#1169: SIX readers said "empty" about full roads; banter is the LARDER, ads/station IDs have no dialogue entry; use road_source and ask director_why's census FIRST
- [Repetition on air, measured](repetition-on-air-measured.md) — #1175: 43.6% of aired lines are exact repeats; emergency_host = 28 lines/919 airings/97%; the 1-hour cooldown map lived only in memory so every restart reset it; 1,416 gold bars sat unused beside it
- [The quota outranks the sheet](quota-outranks-the-sheet.md) — caller_per_hour 10 vs 4 entries = a deficit that never closes, so calls pre-empt the manager forever (81 call lines / 0 manager in one hour); plus the 75%-queue model constraint and three API-field traps
- [Why the feed shows fragments](why-the-feed-shows-fragments.md) — dj_start() wipes _RADIO["chat"]; stalling box -> dead air -> 3 strikes -> self-restart -> feed emptied (measured: 1 hour of history down to 3 min); and 64% of feed 'prepared' rows are banked shelf material
- [Airings are the meter](airings-are-the-meter.md) — operator's rule: work expires by AIRINGS not time; 0 airings = no time expiry (#1180), news excepted; the shelf stays bounded by caps, not clocks
- [Answerable orchestrator asks](answerable-orchestrator-asks.md) — #1181: answers DO land; prefer≠drive, short-horizon news is not a shortage, and a pin with no door
- [Audio owner and the play switch](audio-owner-and-the-play-switch.md) — #1008 solo gate + #1161 terminals: check `play` FIRST; the stale-delivery sampling trap
- [Every fix becomes a tool](every-fix-becomes-a-tool.md) — operator's standing rule: every hand-applied cure must become a rung the orchestrator can press itself
- [The pause that gags the page](pause-gags-the-page.md) — flags living in the tab that no restart can reach; `published` != heard; a paused station is not a wedge
- [Silent fallbacks hide exceptions](silent-fallbacks-hide-exceptions.md) — #1219: an UnboundLocalError invisible for two days; force the road with air-now, and date regressions by clip_media share

