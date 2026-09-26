# Decision Ownership

| Decision | Current owner | Mechanism | Source location | Observable? | Logged? |
|---|---|---|---|---|---|
| Next segment | scheduler + System 2 + show loop | deterministic clock/slot/reservation with fallback | `app.py:schedule_take`, `_dj_loop`; `system2_runtime.py:dispatch` | schedule/System2/playout APIs | yes, distributed |
| Segment duration | schedule/System 2 plus media facts | configured target/deadline, measured audio/track length | `system2.py` slot body; `system2_writing.py`; `app.py:_dj_loop` | yes | yes |
| Topic | mixed | operator/schedule/retrieval + RNG + model elaboration | `caller_topic.py`; `app.py:topic_cooker`, `dj_banter` | partial | selected topic/source often |
| Initial speaker | prompt + LLM, bounded by code | required labels/cast, parsed sequence | `app.py:dj_banter`, `dj_call_generated` | script | indirectly |
| Next speaker | mostly LLM | model writes labeled multi-turn script; parser validates | same | script | indirectly |
| Emotional tone | mixed code/RNG/LLM | speaker state/weather -> prompt/performance vector; LLM wording | `app.py:speaker_state`, `weather_roll_round`, `performance_vector` | partial | partial |
| Agreement/disagreement | mostly LLM | approach/brief directs behavior; response inserts can override | `app.py:approach_pick`, `dj_banter`; `response_bank.py` | text | not as a decision |
| Conversational reaction | mixed | LLM response plus response bank/SFX reactions | `app.py:speak_turns`; `sfx_reaction.py` | text/SFX | output yes |
| Pushback/escalation | mostly LLM + speaker state | prompt and `escalation_feel` | `app.py:escalation_feel`, `perf_directive` | partial | partial |
| Topic transition/reframe | LLM within round; scheduler between rounds | prompt/approach and next road | `dj_banter`; `schedule_take` | output/schedule | partial |
| Conversation ending | mixed | requested turns, scene completeness, hangup/deadline/fit, LLM closing text | `system2_writing.py:scene_complete`; call/story helpers; `speak_turns` | script/status | yes, outcome |
| Prompt contents | deterministic composition + RNG sources + operator config | layered strings and retrieved chunks | `active_prompt_text`, `schedule_prompt_for`; `crystal_prompts.py`; `segment_prompts.py` | prompt-history/trace APIs | yes, with gaps |
| Context selection | mixed weighted RNG/rules | source query, cooldown, document lock, top-k | `speakbox_quote`, `library.search`, `segment_prompts.expand` | source/provenance | mostly |
| Retrieval result | deterministic scoring + filtering | vector cosine + lexical score + per-doc cap | `library.py:search`, `_vector_rows`, `_word_rows` | library/trace views | selected result partly |
| SFX selection | scored/weighted RNG + durable deck | token/keyword score, peer band, bans, rotation | `sfx_match.py:choose`; `app.py:sfx_db_pick_rotation_*` | SFX doctor/history | yes |
| SFX timing | deterministic assembly + cue rules | punctuation/turn positions, beats, cue map | `conversation_assembly.py`; `sfx_cue.py` | cue map/script | yes |
| Music selection | queue/config/RNG | request queue, station filters, shuffle, played avoidance | `app.py:radio_fill`, `radio_next_track`, `dj_next_track` | `/api/radio` | played/queue |
| TTS voice | config/role binding | cast/role -> voice -> engine | `app.py:VOICE_ROLES`, `session_voices`, `voice_engine_for` | DJ state/provenance | yes |
| TTS style/intonation | mixed code/RNG/external engine | performance vector and engine-specific payload | `performance_vector`; voice adapters in `app.py` | partial | partial |
| Playback order | linear sequencer + floor | `(block,ord)`, starts, route, acknowledgements | `playout_sequencer.py:LinearSequencer`; floor helpers in `app.py` | `/api/playout` | yes |
| Failure recovery | deterministic policies/watchdogs | retry, lease reclaim, engine ladder, reserve/filler, service restart bridges | `voice_render_any`; `System2Runtime`; startup hooks; `resource_guard.py` | health/glass/flow | yes, distributed |

## Decisions Implicitly Delegated to the LLM

**OBSERVED:** The LLM normally chooses wording, turn-level rhetorical action, the actual next speaker within the requested cast/format, how strongly to agree or push back, local topic transitions, and how to close. Code can request or evaluate these properties but does not represent each as a structured decision.

**OBSERVED:** Topic identity, cast, maximum turns, source facts, schedule purpose, voice, output order, deadlines, admission, and playback are not left solely to the LLM.

**INFERRED:** Agreement, response behavior, and flow are the least explicit ownership areas. They emerge from prompt text and generated dialogue, making them difficult to inspect or replace independently without adding structured state/events.

