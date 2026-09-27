# System 3 — Rollout

Status on 2026-09-26: all ten implementation phases of
`docs/system3_blueprint.md` §19 are built and deployed. The station runs
System 3 in **SHADOW** on every road. Active authority is one switch away,
and the next gate below says what has to be true before flipping it.

## Rollback (any time, no restart)

| To | Do |
|---|---|
| stop System 3 influencing air | System 3 window → Controls → mode **shadow** (or `POST /api/system3/settings {"mode":"shadow"}`) |
| stop System 3 entirely | mode **off**: every hook returns `None` and the station is the legacy station byte for byte |
| undo a table / structure edit | Controls → reset tables and structure, or re-save an older version from `GET /api/system3/config?hash=` |
| remove the code | `cp /tmp/app.py.bak-system3 app.py` (the pre-System-3 file) and restart; the modules are inert without the install line |

Mode changes take effect on the next round planned; nothing already written
is rewritten.

## Phase report

| # | Phase (blueprint §19) | What exists | Tests |
|---|---|---|---|
| 1 | Baseline / contracts | architecture snapshot (evidence), golden-seed trajectory pinned, metrics defined (`/api/system3/status`), regression tests | `tests/test_system3.py::PlanTests::test_golden_seed_trajectory` |
| 2 | Domain model | `System3Conversation` aggregate, participants, dynamics, turns, `PerformanceIntent`, identity correlation, versions | serialisation round trip, event well-formedness |
| 3 | RNG + decision engine | `DrawStream` root seed, 3-stage weighted draws with recorded effective weights, filters, transitions, CTS/ES/RS/IRS/FL tables, persistence | RNG, pick, cooldown, time gating, controls, disabled rows, replay |
| 4 | Shadow mode | every banter and caller write planned beside the legacy writer; comparison recorded; nothing reaches air | `test_shadow_never_reaches_the_words` |
| 5 | Planned-scene integration | the running order replaces #1386's in ACTIVE; deterministic validation; bounded repair (banked rounds only) | end-to-end runtime test, validation tests |
| 6 | Speakerbox + performance | seeded door rolls, per-line prepend/append marks, act-triggered quotes, material through `speakbox_quote` with real candidate lists; ES → six emotion dims → `performance_vector(state=)` | material and timeout tests, performance tests |
| 7 | SFX Guy | per-turn play/placement/intent, extra dues above the cadence floor, intent words to the matcher, what played recorded with matcher counts | SFX tests, end-to-end SFX observation |
| 8 | UI | Conversation / Rolodex / Script in sync, build animation from recorded rolls, Tables, Structure (node view), Controls | headless-browser probe: 0 errors, selection syncs both ways |
| 9 | Active selected roads | `active_selected_roads` + `roads`, per-road modes; callers keep their protocol | road-mode tests, caller annotation test |
| 10 | Turn-by-turn | Mode B director on the banked beat chain (`generation_mode=turn`), observe → replan → resolve → next beat; replayable | Mode B tests, director test |

Changed files: `app.py` (22 anchored edits, `tools/system3_patch_app.py`,
+112/−11), new `system3.py`, `system3_tables.py`, `system3_store.py`,
`system3_runtime.py`, `frontend/system3.js`, `frontend/system3.css`,
`tests/test_system3*.py`, `docs/SYSTEM3_*.md`.
Migration: none. `data/system3.sqlite3` is created on first start.

Verification at deploy: 51/51 System 3 tests inside the container, no new
pyflakes undefined names, the served panel's inline script passes
`node --check`, the station healthy in 15 s, System 3 loaded in shadow.

## Gates

**Gate A — shadow → active on `banter` (next).** Leave shadow on for at
least two clean hours of normal programming (no deploys; see the restart
note in the ops memory), then check `/api/system3/status` and the list:

- `failures` 0, or every entry understood, and `writes_dropped` 0;
- `plan_ms_max` well under 100 ms (the planner is on the event loop);
- in the Script view of shadow rounds, System 3's plan reads coherently beside what the legacy writer produced;
- the Rolodex for a handful of rounds shows sensible candidate sets (nothing ineligible, weights as documented).

Then Controls → mode **active selected roads**, roads **banter** only.

**Gate B — active on banter, observed.** After two hours active:
verdicts are mostly `compliant`/`partial` (Status strip); `repairs` are rare;
`material_timeouts` are low; dead-air and repetition meters are no worse
than the shadow hours (`/api/director/deadair`, gap log); heard receipts
appear on System 3 lines in the Script view. If any of this fails, return
to shadow; nothing else needs undoing.

**Gate C — callers.** Add `caller` to roads. Watch `call_flow_report`
refusals: the annotation must not raise them (the protocol legs are not
edited, only appended to).

**Gate D — turn by turn.** `generation_mode = turn` affects only banked
beat-chain rounds (the prepared-content buffer absorbs the extra model
visits). Enable after Gate B, and watch `mode_b_beats`, the larder's
fill rate and the lookahead's "nothing fits" lines.

## 2026-09-26 — the pair talking through each other (engine v2)

Asked "why are these conversations not connecting ... the people are still
appearing as if they're talking through each other", the first directed
rounds were read against their plans. Two of three banter rounds had the
legacy full-swath door fire (dial at 45%, 3,000 characters, seats spread):
eight "turns" that were one comedy transcript, and one food-documentary
transcript, dealt alternately to the host and the co-host after the writer
had finished. A document split between two voices is a monologue; nothing
in it can answer the line before. The append door did the same with a
shorter passage. Tint was off and was not a factor.

Fix, at the road that owns the decision: on a System 3-directed round the
three splice doors stand down (`_quote_door`, recorded in the door ledger),
and the same sliders drive System 3's own marks inside the running order —
a passage read by one speaker, before or after their line, which the next
speaker answers. The full-swath dial becomes an opening speaker-box
monologue (CTS1 "Speaker-box Quote / Monologue", up to 700 characters) read
by the initiator. Engine version 2; decision replay says so when asked to
replay an engine-1 conversation.

## Known limits and risks

- **Lexical validation.** Act compliance uses keyword cues, and emotion compliance is not checked (it is "unchecked", not guessed). A model-based judge was deliberately not added to the air path.
- **Topic-change material** is only drawn for the speakerbox category. Other CTS categories are direction-only and are eligible only when the road holds that material (news, gazette). Manager, gallery, topic book and research are not wired as material sources yet, so those categories are ineligible.
- **Door roll ownership.** In ACTIVE, the door's number is System 3's, and its meaning (rate + lift) is still the station's. The outcome is joined back at bind.
- **Speakerbox share walks.** Inline passages call `speakbox_quote`, which can be slow on the share (#1250). Each call is bounded at 8 s and shadow never calls it.
- **Per-line turn lookup** matches chunk text to the round's current script. A chunk the air path rewrote after binding (a late freshen) keeps the round's weather instead of its ES, which is logged as not-applied, never mis-applied.

## 2026-09-27 — every road is System 3's (`tools/system3_roads_patch.py`, `[s3-roads]`)

Operator: "Nothing is outside of system 3. It takes over everything." "I
don't want any wedges outside of dictating dialogue. It needs to all be part
of the RNG system with full accountability to its origin. There aren't
intended to be any exceptions to that."

| road | how it moved | where its nodes are |
|---|---|---|
| banter | unchanged: the banter cycle | `config.structure` |
| caller | unchanged: the call protocol as legs (`[s3-calls]`) | `config.structures.caller` |
| recap, ad, news, manager, memo, gallery, mixtape, open_show, fan_mail, guest | `dj_banter(road=...)` names the road; System 3 plans it from that road's legs (`plan_legs`) and hands the writer `render_legs_sheet`; memos (`whole=True`) are directed too | `config.structures.<road>` |
| the SFX Guy's mouth (`sfxguy`) | a SFXGUY node on every host turn: SPEAK/PASS at the desk's interjections dial, then the kind (wire / reaction / shelf); at air `system3_sfxguy_direction` answers the cadence's take and speak_turns' quip in place of `random()`, and `sfxguy_line` draws the line through a chooser that records the candidates and the die | `config.sfxguy`; the plan in `turn_dice.s3.sfxguy` |
| track_talk, station_id, upstairs, interject, ad_spot | `system3_direct_line`: one-seat legs, ES rolled, the running-order clause appended to the writer's prompt, a LINE draw over the road's own list (stock lines, the ad book, the liner stack via `unrepeated(director=)`), the words bound to the node; `dj_speak(system3=stamp)` remembers the stamp by line id and `script_ledger_catch_up` writes it on the ledger row | `config.structures.<road>` |

The register (`system3_tables.ROAD_REGISTER`, on `/api/system3/status.roads`
and the Controls tab) names every road, its writer and its hook. A road
standing aside - mode off, or a planner fault - airs the station's own
words and its lines read "not directed by System 3" wherever they show.

Engine `system3-engine/3`: the SFX Guy's numbers come off their own stream
(`seed|sfxguy`), so the round's draws are exactly what engine/2 drew; the
golden trajectory is unchanged and only the default config hash moved.
Decision replay dispatches by road (line, call, legs, cycle).

### Shared speech door and clean live start

`dj_speak` now obtains an active System 3 node for every line that does not
already carry one. Listener replies use the editable `reply` structure (ES and
RS); other direct single-voice lines use `single_line` or their named line
road. The node's performance vector guides the voice, its running order
guides newly written words, and the final words are bound to the node before
the line id is recorded. The default mode is active.

`speak_turns` withholds an unstamped round while System 3 is active. The
deep-conversation road and saved-exchange button now ask `dj_banter` for a
new System 3-directed performance. Failed stock-line and produced-ad draws
withhold the old item instead of selecting it with the station randomizer.
The legacy manager cut-in prompt, random Speakerbox reaction prompts, and
old record callback frames stand down under active direction. Speakerbox
material remains available to the System 3 running order. Old prepared
dialogue must be purged from the pantry, shelf and larder before expecting
every newly aired line to carry its System 3 origin.

**The Messenger keeps step with the audio.** The Rolodex used to turn when a
round arrived; the operator watched it run ahead of the voice. Now the page
tells the embedded view which line is on air (`live`) and where the clip has
got to (`clock`, every tick, per line inside a welded round): the spin starts
as the line is heard, takes a fifth of the clip, the words type in, and a bar
under the message follows the audio to the clip's end. Arrivals are quiet.

**Verification at deploy:** `tests/test_system3_roads.py` beside the three
existing suites; `tools/system3_roads_patch.py --check` says "already
applied (60 edits)"; pyflakes: no new undefined names; `node --check` on
`frontend/system3.js` and `script-page.js`.

**Rollback:** mode off (no restart) stands every hook down; the patch is
anchored and every edit is guarded, so `--check` names anything missing.

## 2026-09-27 — the orchestrator's window and the length of a round (`tools/system3_glass_patch.py`, `[s3-glass]`)

Operator: "make sure the orchestrator and the popup is connected ... making
sure dialogue length and banter exchanges are long and exponential enough
to encompass the time segments ... I want the popup orchestrator windows
showing RNG and rolodex information and I want glyphy reactive to the
dice / roulette results in his indicator and I want to see him rolling
dice in the popup for the currently spoken segment showing numbers for the
values being obtained for the actively spoken line."

- **The line on air, with its dice:** `GET /api/system3/now` resolves the
  station's own record of the line going out (`_SPEAKING_NOW`) to its
  System 3 turn: road, turn i of n, every recorded roll with its d100 and
  the candidates it rolled through, the SFX Guy's node, the round's budget
  (turn budget, planned seconds, the slot's seconds) and its length roll.
  The orchestrator glass (`desktop/renderer/orchestrator-glass.js`, on the
  desk and the tablet) polls it every 1.5 s while open: a pane above the
  list shows the words, the reels spin through the recorded candidates,
  the dice count up to the recorded values and land, and Glyphy's face
  rolls with them, then takes the feeling the ES roll landed on for a few
  seconds before the conductor's own mood returns. A line no node made
  reads "not directed by System 3".
- **The round's length is a roll.** A free round's turn count was
  `random.randint(banter_min_lines, banter_max_lines)` in `dj_banter`.
  System 3 rolls it now (`LENGTH` event, its own draw, replayable), the
  round takes System 3's count and the judge's bar follows it. A round the
  slot on air or System 2 sized keeps that size - a budget is an
  obligation, not a roll - and `entry_fill_out` still adds rounds from the
  shelf until the entry's minutes are used.
- **Record links bind the words they return** (the fallback link included).

## 2026-09-27 — passages end at a sentence end (`[s3-cut]`)

Operator: "these lines appear to be cutting off and stopping short of
saying the full phrases." Measured on the air log: 11% of aired host
lines ended mid-phrase in the two hours before the roads restart and 13%
after - a standing condition, not a new one. The share System 3 owned was
passages handed to the writer cut at a character count (600 for a call's
passage, 200 in the call sheet, 420 and 720 in a running-order row, and
the station's `speakbox_quote(cap=)`), which the model read out verbatim,
cap and all. `system3.sentence_cut(text, cap)` now ends every such passage
at a sentence end (failing that a clause break, failing that a word), and
material is fetched with a little slack and cut back. The rest of the
mid-phrase lines are fill fragments outside System 3 (gold bars and
punctuation rows made from a turn's last chunk) - not moved yet.

## 2026-09-27 — active broadcast admission

- A single spoken line receives a System 3 line plan and turn stamp before
  synthesis. The `single_line` and `reply` roads are editable in the System 3
  register. A missing active plan withholds the line.
- A multi-turn round admits only script turns with matching System 3 turn IDs
  and dice. Prepared audio is checked by spoken text because one script turn
  can contain several clips. An incomplete conversation with fewer than half
  its planned turns is withheld; severely short live drafts get a repair pass.
- Active caller rounds no longer insert the stock hello, and active rounds no
  longer swap a planned turn for unrelated shelf text or run a legacy
  freshener after binding. The System 3 emotion vector reaches live speech.
- Automatic SFX Guy speech requires its planned node. The Banter button now
  lets System 3 choose its shape and does not speak a stock acknowledgment.
- The audio encoder now invokes the system `nice` command without a Python
  `preexec_fn`; this removes a fork deadlock seen during the live audit.

### Next (queued, in this order)
1. `docs/SFX_vector_reuse`: the SFX Guy's vector database and crystal made
   accessible to outside applications (lexical, semantic, action, situation,
   emotional, intent, theme, metaphorical, visual), sectioned, backed up,
   redeployable.

## 2026-09-27 — the rolls reach the air (`tools/system3_rounds_patch.py`, `[s3-rounds]`, `[s3-carry]`, `[s3-withhold]`)

Measured over 8 h before this batch (scripts in the session scratchpad;
read `data/system3.sqlite3` and `data/prompt_history.sqlite3` read-only):

- the transcript-repair harvest (`speakbox_harvest`) held the one writer
  lane 54% of the hour (610 calls x 25.6 s); 505 of 566 replies came back
  with no punctuation and were shelved as gems anyway;
- every round that arrived while it did was refused admission, `ask_model`
  returned `""`, and dj_banter prepended the seed passage: 26 of 33 live
  banter rounds aired as ONE turn of raw transcript, bound one second after
  they were planned; 35 news, 12 memo and 7 gallery System 2 rounds bound
  zero turns;
- the banked beat writer re-emitted the "immutable" transcript in 163 of 302
  replies and `zip()` seated the copies as the new turns;
- four station-side `random()` directives fought the per-turn ES in ~120
  one-call prompts; `initial_emotions` were handed in on 0 of 1,308 rounds;
- the live config's cycle and tables were the defaults (the only save was a
  news variant dropped 11 ms later); 247 planned rounds were never bound and
  recorded nothing.

Shipped (23 app.py edits, engine + runtime + editor, 115 tests green):

1. **The lane.** `station:harvest` is its own admission category (cap 1);
   `_harvest_yields` waits while any round writer is waiting or active;
   `_live_round_waits` gives a LIVE round (`mark.live`, purpose `... live`)
   up to 45 s for a slot; a document whose repair came back unpunctuated
   is marked (`data/speakbox_harvest_bad.json`) and skipped 12 h; one
   harvest per speakbox draw.
2. **Never the seed alone.** A deferred ROUND raises `WritingDeferred`; a
   writer that returned no turns withholds the round. Both are recorded
   (`system3_withhold`), and a sweep files rounds nobody bound in 30 min as
   `ABANDONED`.
3. **Beats.** `_beat_fresh_only` drops the lines a beat handed back that
   were already spoken before they are seated; the retry says so.
4. **The prompt randoms are rolls.** `TEMPER1` / `SHOCK1` / `INTERJECT1`
   tables, the `shock_beat` / `interjections` / `mention` controls, on
   their own streams; the four prompt clauses and "moods right now" stand
   down when System 3 owns the round. Default config hash
   `48e47262ef173867`.
5. **Carry.** The last round's ending (seats' emotion, position, energy,
   dynamics, unresolved points, landing line, tempers) is the next live or
   System 2 round's start, decayed over 20 minutes; turn 1 picks up from the
   landing; banked rounds take it in the voice at air.
6. **The editor says what it saved** (`s3-ok` notice with the live hash and
   version) and the Controls tab lists every config version with the live
   one marked. `system3.js?v=5`.

Verify after the restart: `/api/system3/status` (`carry`, `open_rounds`,
`metrics.withheld / abandoned / carried / carry_in`), prompt-history purposes
`station:round live` / `station:harvest`, plan->bind seconds no longer under
3 s for live banter, and the pipeline log's `the transcript repair of ...
came back unpunctuated`.

### Next
- The `talk_radio / 150` force-seed (67% of rounds open on a passage) is the
  one station-side random left in dj_banter's round shape.
- The tablet APK carries `script-page.js` with `system3.js?v=4`; rebuild to
  pick up v5 (the desktop and the served page already do).

### Second pass, the same day
- The harvest pauses for an hour after five unrepaired repairs in a row
  (`HARVEST_PAUSE_AFTER`, `HARVEST_PAUSE_FOR`); a real repair ends the run.
- A call rolls tempers, the shock beat and the mention too (`plan_call`);
  never interjections. The call sheet's head carries the tempers.
- A stored config gains the default tables it predates, once, at load
  (`add_missing_default_tables`, remembered in `defaults_added`); the live
  config got TEMPER1 / SHOCK1 / INTERJECT1 through the tables API meanwhile.
- `tools/system3_rounds_patch.py` checks and applies sequentially and knows
  an applied edit by a distinctive line it inserted (27 edits).
