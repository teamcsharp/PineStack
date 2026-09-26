# SFX and Music

## SFX

| Concern | Current implementation |
|---|---|
| Storage | **OBSERVED:** files under `SFX_ROOT` plus locally made/edited media; metadata in `data/sfx_clips.db` |
| Schema | `clips(path,sid,name,folder,video,bytes,mtime,seconds,playable,seen_at,deck_cycle,...)`; `sfx_meta`; leased `sfx_index_work` (`app.py:sfx_db`; `clip_speech.py`) |
| Indexing | `ClipIndex` and incremental speech/vision workers extract folder/name tokens, keywords, speech/vision descriptions |
| Search/match | token stemming, folder seeds, keyword/description scores; `sfx_match.Cand`, `peers`, `choose` |
| Vector search | **NOT PRESENT IN CURRENT IMPLEMENTATION** for core SFX picking; descriptions may be model-produced, but selection is metadata/token/scoring based |
| Selection | threshold + score band/peer set + random/deck rotation; bans/deletes/weights and play history filter candidates |
| Repetition | durable `deck_cycle`, `sfx_history*`, `sfx_seen.json`, cadence receipts, per-voice speech banks |
| Timing | cues are attached to line/turn/punctuation positions and materialized into assembly cue maps (`sfx_cue.py`; `conversation_assembly.py`) |
| Mixing | ffmpeg/PCM assembly combines effects with voice; levels/lengths are cached; stream layer mixes program audio |
| Ducking/volume | listener/music/voice mix controls plus per-clip measured levels; route-specific UI controls |
| Triggers | road/line punctuation, SFX guy reaction logic, operator soundboard, station transitions, video/SFX road |
| LLM role | model can describe/index media and may write text suggesting reactions; deterministic match/rotation chooses the actual clip in core paths |

**OBSERVED:** `/api/sfx/doctor` exposes share reachability, folders, scan/index pool, video pool, lengths, bans, and repair actions. SFX state was actively updating during collection.

## Music

| Concern | Current implementation |
|---|---|
| Library | `MUSIC_ROOTS` (default `/music`), recursively indexed to `music_index.json` |
| Metadata | id, title, artist, album, extension, duration, path, size/mtime/search text; art/lyrics/notes in side stores |
| Selection | `radio_fill`, `radio_next_track`, `dj_next_track`; station filters, request queue, focus/rotation, played avoidance, shuffling |
| Scheduling | records are the continuous bed/primary clock; scheduled talk runs between or over them; explicit music requests enter System 2 events/queue |
| Duration | tag-derived where possible, estimate otherwise; `_dj_loop` uses measured/estimated seconds and listener/sequencer correction |
| Queue/state | `_RADIO.queue`, `requests`, `now`, `started`, `coming`; `/api/radio`, `/api/radio/next`, `/api/dj/state` |
| Playback | browser page fetches the current media; box route can separately play it; stream decodes/mixes program audio |
| Transitions/fades | overlap/tip delay settings, intro/outro and talk-over tasks, stream mix/bed behavior; no universal DAW-style timeline |

## Interaction with Conversation

**OBSERVED:** `_dj_loop` starts a record and runs `_record_talk` beside it. Track talk binds generated copy to a specific current/coming record and rechecks that binding before model work, render, and air (`record_binding.py`; `_dj_speak_floorless`). Banter/SFX can be assembled as one clip or published around the music route. A pressed skip bypasses research/intro generation for immediate record start.

**INFERRED:** Music is both content and continuity infrastructure. A conversation system cannot assume silence before/after a dialogue; it must respect record phase, floor ownership, stream route, and overlap timing.

