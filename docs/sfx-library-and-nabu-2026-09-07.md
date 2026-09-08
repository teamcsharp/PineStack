# Sample library and Nabu transport evidence

The requested folder is present as `\\10.89.1.125\QuickSwap\samples_grabbed`.
`samples\_grabbed` does not exist. The share already mounts at
`/home/ehm_eckx/samples` on the station and read-only at `/samples` in Docker.
No mount or path configuration change was needed.

The read-only inventory found **15,761 MP3 files in 11 immediate child folders**.
All current files fit the existing drop-folder discovery depth. The configured
`samples_grabbed` root is rescanned every 120 seconds. Large individual folders
rotate a random 400-file subset, and recent arrivals bypass that subset cap.
The earlier live snapshot contained 7,821 playable clips across all configured
roots, including 7,363 fresh clips. Those numbers are a cached pool snapshot,
not the total library or proof of playback. Full counts and paths are in
[the manifest](sfx-library-manifest-2026-09-07.json).

`sfx_seconds` previously discarded every cached duration after 8,000 entries,
even though the grab library alone is nearly twice that size. It now retains
up to 32,000 metadata entries and evicts only the oldest overflow readings.
Path plus file modification time still invalidates a replaced recording.
The reset behavior was reproduced; a live latency improvement has not been
measured. Three new cache regressions and five existing freshness checks pass.

Nabu is the Home Assistant Voice PE at `10.89.1.161`, MAC
`20:f8:3b:09:f8:a8`, with firmware 26.6.0 / ESPHome 2026.6.0. Home Assistant
reported the device unmuted at 60%. Its advertised announcement format is
FLAC, 48 kHz, mono, 16-bit; the music format is stereo. The installed ESPHome
integration forwards `announce=true` and proxies the station WAV to FLAC.
No audio format, device, route, volume, firmware or playback command was
changed during this investigation.

Passive capture from Unix time 1788809298 to 1788809343 observed Nabu's
`micro-decoder` request its Home Assistant FLAC proxy URL and receive HTTP 200.
About 29 ms later, Home Assistant's FFmpeg reader fetched
`165ba04819834f32bade38fba4cd2c95.wav` from the station. That original file is
93.608 seconds of 24 kHz mono 16-bit PCM. The new device connection received
about 2.63 MB during the capture, alongside an older connection. The capture
does not identify the older connection's content; byte totals may include
retransmissions. See [the scrubbed HTTP evidence](nabu-http-observation.json).

Home Assistant also logged several FFmpeg proxy process-exit timeouts. These
occur in cleanup and do not, alone, establish failed speech. The observed
successful fetch means the proxy is not universally failing.

The installed media entity exposes no announcement identity or playback
position, and its `playing` state can describe music. The Assist satellite
stayed idle while the media announcement was fetched. Therefore neither that
state nor an HTTP transfer proves that this exact spoken clip was audible.
The existing handoff behavior remains unchanged. New `_LAST_PLAYOUT` fields
and `/api/pinebox/status.delivery` explicitly report transport acceptance,
the inference basis, and `audible_confirmed: false` for Nabu. A successful
post-wait state check is labeled `home_assistant_state_after_wait`; acceptance
without that check is labeled `home_assistant_command_accepted`.

The combined 18 isolated cache, freshness, Nabu telemetry and volume ownership
tests pass. Acoustic confirmation remains separate from these checks.

## Subsequent startup-pool diagnosis and fix

The September 7 restart exposed a separate publication delay: the pool stayed
empty for about 366 seconds even though the persisted duration cache already
contained 3,458 library samples of four seconds or less. The eventual full
scan published 4,864 clips. All nine observed sample opportunities before that
publication were omitted. This was delayed availability, not a permanently
failed scan or a need to lengthen/trim samples. Evidence is retained in
`sfx-pool-diagnosis.json` and `sfx-broadcast-observation.json`.

The new refresh first loads the duration cache in its worker thread and
validates a bounded subset against configured folders, file type, exact
mtime, positive finite duration and the current cap. It publishes the first
verified subset before enumerating the full inventory. The warm pass accepts
at most 64 clips, checks at most 256 eligible cached candidates, and stops
between filesystem operations after two seconds. A single stalled NAS call
can exceed that soft wall-time budget, but it does not run on the event loop.

The complete scan then publishes additional verified batches as it proceeds.
It reuses each folder inventory instead of walking it twice, preserves the
rotating per-folder cap and includes recent arrivals beyond that cap. During
ordinary refreshes, the current usable pool remains available until the new
inventory is complete. Every publication checks its job identity and captured
settings signature, then applies current bans and weights. A superseded or
cancelled scan cannot publish stale results. The history endpoint distinguishes
partial readiness (`ready_at`, `filling`) from the completed `walked_at` clock.

Seventeen isolated warm-pool, freshness and duration-cache tests pass;
independent review also passed all nine new warm-pool tests. They cover early
publication before blocked inventory/probes, exact mtime and symlink/quantity
limits, restart cache loading, periodic variety retention, settings races,
bans/weights and recent arrivals. These checks issue no playback or settings
commands. Final live warm-start timing is recorded separately after deployment.

The final deployed check is now saved in `sfx-warm-final-live.json`. The first
GET already found 3,133 verified clips available while `filling=true` and
`walked_at=0`; the latest publication at that observation was 42.349 seconds
after the reported restart completion (1788812588.3885). The observer began
after startup, so this is an upper bound on initial availability, not an exact
first-clip measurement. The full scan completed at 1788812643.3155, about
54.927 seconds after restart, with 4,369 clips. The subsequent periodic scan
kept the existing selection and progressively grew it to 4,645 during the
observation. There was no six-minute empty-pool interval in this check.

`nabu-mix-final-live.json` separately confirms Music 0, DJs 1, Replies 0.5,
all Nabu routes, station on/unpaused, and the physical master still 30%
unmuted. The dispatch receipt records actual speech gain 2. These were only
authenticated GETs; sample selection, audible completion and physical volume
were not commanded by the observers. The final backend suite passed 883 tests
and 95 Node checks passed before this deployment (main-task
verification). Both bounded observers have exited.
