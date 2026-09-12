# Independent Nabu music and speech levels

The September 7 instruction changes Nabu's sliders to independent digital stream levels. The physical speaker dial remains the master. This supersedes the earlier explicit music-slider behavior documented in `nabu-volume-1059.md`; historical measurements in that document remain historical.

| Stream | Persisted setting | Meaning |
| --- | --- | --- |
| Music | `nabu_music_level`, fallback `music_box_level` | 0 stops only music; 1 is original amplitude. |
| DJs, recorded dialogue, adverts and SFX | `nabu_voice_level` | 0 is deliberate silence; 0.5 is original amplitude; 1 is twice the amplitude, with peak limiting. |
| Replies | `nabu_reply_level` | Same independent speech scale; default 0.5. |

The authorized activation is music 0 and DJs 1, with music still routed to Nabu so raising its slider later can resume the current record. The main task deployed the tested backend at Unix time 1788811437 and activated these settings at 1788811479.28. Read-only delivery verification is recorded below.

Music changes refresh the current track from the station's elapsed position. A generation token, track occurrence, route and latest gain are checked after encoding and before the device command. Music 0 sends only `media_player.media_stop`; it does not wait for the announcement lock. Paused/off/stale queued work cannot restart music. Speech and reply changes apply at the next dispatch, including already recorded files. Audio already buffered on the device retains its existing level until that clip finishes.

The installed Voice PE supports separate music and announcement pipelines. ESPHome 2026.6.0 defaults STOP to the media pipeline when no announcement flag is provided; its shared volume setter changes both pipeline speakers. These are the reasons to use a music-only stop and digital per-stream gains, with no shared volume calls. [ESPHome speaker media player implementation](https://github.com/esphome/esphome/blob/2026.6.0/esphome/components/speaker/media_player/speaker_media_player.cpp)

`nabu_audio.py` builds atomic cached 48 kHz, signed 16-bit FLAC derivatives: stereo music and mono speech. It resamples before its limiter, preserves mono amplitude when duplicating to stereo, and never modifies the original recording. The authenticated or signed `/nabu-audio/{key}` route supports byte ranges. Home Assistant receives `bypass_proxy:true` because the files already match the advertised formats. Missing files, obsolete settings or failed conversion refuse delivery; they do not fall back to an unattenuated original. Disposable derivatives are bounded to 96 files / 256 MiB. The module is included in desktop backend packaging.

Each Nabu delivery receipt records the gain actually used, rather than rereading a slider after playback. Zero-gain speech is explicitly `intentional_mute` with basis `operator_muted_stream`: accepted delivery, no audible claim, no self-healing/retry for an intentionally silent stream. The regular Nabu completion inference still does not constitute acoustic proof. The new cadence consumes the dispatch receipt to exclude muted speech from audible credit.

## Validation before deployment

31 tests passed with fresh isolated data and bytecode caches: `test_nabu_audio`, `test_nabu_mix`, `test_nabu_volume`, and `test_nabu_evidence`. Eight encoder tests exercise real WAV/FLAC files; wrapper tests use mocked Home Assistant and never play audio or change device settings.

Coverage includes measured gain and offset, limiter peaks, exact device format and duration, original file hashes, independent speech/reply levels, Music 0 during an active announcement, no-current-record mute, route/slider/record races, produced-ad source validation, signed byte ranges, conversion refusal, cache reuse/eviction, and gain changes after dispatch retaining the correct muted receipt. Tests also forbid TTS during existing-recording gain adjustment and retain the no-automatic-master-volume protections.

For deployment verification, `tools/nabu-direct-observe.py` passively observes the known device `10.89.1.161` and backend port 8096 for 5–55 seconds. It stores only request paths, status/header evidence and traffic counts; signed queries and audio payloads are discarded. A direct GET / HTTP success proves transfer, not sound from the speaker.

## Observed deployment

The full backend suite passed 867 tests, and all 14 Node test files passed before deployment (main-task verification). This agent then performed only passive packet observation, authenticated GETs, and file-format inspection.

- `docs/nabu-direct-observation.json`: bounded capture 1788811506.17–1788811561.24 saw the actual Nabu `micro-decoder/0.2.0` request two `/nabu-audio/*.flac` files directly from port 8096, with matching HTTP 200 responses. Both files are 48 kHz, mono, signed 16-bit FLAC: 13.038 seconds / 725,640 bytes and 56.459 seconds / 2,972,981 bytes. The two requests began 2.93 seconds apart; this observation does not establish complete audible playout of either file. Retransmissions can inflate packet counts and wire-byte totals.
- `docs/nabu-mix-live-observation.json` and `docs/nabu-mix-live-after.json`: Music 0, DJs 1, Replies 0.5; all three routes remain Nabu, station on and unpaused. The first dispatch receipt retained its pre-activation gain 1; the subsequent receipt reports the new actual gain 2, with no intentional mute.
- Both speaker GETs report the physical master at **30%, unmuted**, compared with an earlier historical 60% reading. The independent HA recorder audit (`nabu-physical-volume-audit.json` / `.md`) establishes that 30% was already set at 1788811172.548, about 264 seconds before the backend restart. No subsequent volume change appears through the audit's final reading, and no `volume_set` service event appears in its inspected window. Thus deployment retained the actual pre-deployment 30% level. The actor behind the earlier stepwise change is not proven.

The user had confirmed the previous announcement path was audible before this change. These post-deployment observations prove direct file delivery and dispatch settings, not acoustic confirmation of the new path. The passive capture ended on its intended 55-second timeout; no observer remains running.

After the final SFX warm-start deployment, `nabu-mix-final-live.json` again
confirmed Music 0 / DJs 1 / Replies 0.5, all Nabu routes, on/unpaused, physical
master 30% unmuted, and a dispatch receipt at gain 2. This was a GET-only check;
the saved mixer settings and actual pre-deployment master level survived the
restart. Final SFX pool timing is in `sfx-warm-final-live.json`.
