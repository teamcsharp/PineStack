# Music progression and host continuity — inbox #1060

The immediate Nabu silence had a routing explanation: persisted music, voice
and reply outputs were all `here`, with `box_talk=false`. The selected-device
metadata still said Nabu. A page listener completed a real 77.352-second,
ten-line host/cohost/caller rerun (`7acb25bce9b0406e`), but those acknowledgments
did not establish Nabu playback. Under the explicit outside-Nabu listening
request, normal authenticated routing restored all three outputs to `box` and
enabled Nabu delivery. Home Assistant then changed idle to playing and retained
the physical 84% level. The device exposes no media-position/duration fields
through the installed ESPHome integration, so no numerical position is claimed.

The song repetition was confirmed in the durable music log. “Plok OST - Slow
Beach (Slow Version)” repeatedly returned to the front across restarts and a
pause/resume. Its unfinished record-bound dialogue still owned that record, and
`track_talk_restore_queue` placed every such owned record before the new shuffle,
even when the record had aired after its links were written. Restoration now
checks persisted played times: unplayed paid records retain their FIFO priority;
already-aired records keep their owed text and takes while returning to their
ordinary shuffle positions. Repairing dialogue no longer forces a replay.
The live record clock separately advanced through Plok, U817 and Warm Machine.
Later read-only desktop measurements showed the music position advancing from
106.6 to 186.6 seconds over approximately 80 seconds, with `loop=false`. The
concurrent ordinary ten-line caller broadcast completed at 114.12275 seconds
with ten audible line acknowledgments; the redundant outer desktop player was
paused. Another ordinary ten-line call subsequently began and advanced normally.

After the authorized Nabu restoration, three explicit per-stream requests from
the desktop Node client changed music, voice and reply outputs back to App at
17:53:45–48 UTC. These preceded the desktop relaunch; route-file hashes were
unchanged across that relaunch. The current App choice is preserved pending the
operator's preference. The desktop now derives its selected preset from actual
backend routes, explicitly identifies mixed routes, lists each stream, and
distinguishes Nabu enabled, paused and not routed. Five route regressions pass.
None of these later App acknowledgments is claimed as Nabu acoustic evidence.

A subsequent real App silence exposed a second independent fault. The
13.3685-second station-introduction WAV had an unfinalized ffmpeg streaming
header: RIFF and data sizes were both `0xffffffff`. Mutagen reported
89,478.4853125 seconds despite only 641,766 bytes on disk. The page scheduler
trusted that duration and reserved nearly 25 hours after the introduction.
The client correctly received the next caller but waited for that future time;
this was not an autoplay denial. PCM WAV duration now uses actual available
sample bytes, while other formats keep their media-duration reader.

The scheduler repairs unexplained future gaps beyond five minutes in FIFO
order, preserving delivery IDs, original words and active playback. Each voice
poll carries `reservation_updates` independently of its `since` filter; the
desktop changes queued timestamps without replaying active audio. The two
actual unstarted deliveries (`5306b74e8fd64c49`, `406cf37adba44060`) and all ten
original call rows were saved before deployment in `page_delivery_recovery.json`.
Startup restores this FIFO before ordinary show tasks, and only audible ended
receipts covering all expected lines remove a saved delivery. Four regressions
cover the malformed WAV, FIFO timing and identity, poll updates and recovery
through real acknowledgment handling. The complete integration suite passed
249 tests before deployment; live post-deployment completion is checked separately.

After deployment, the preserved upstairs clip played first, then original
caller `406cf37adba44060` reached `ended` with all ten lines acknowledged and no
unconfirmed rows. The durable recovery file became empty only after those
receipts. Ordinary call `6d5a2a0b299749de` then completed with ten of ten lines
acknowledged at volume 0.267, followed by another audible ordinary host line.
The measured speech gap stayed below a second in these samples. The Comet2
music clock advanced through 60.1, 172.6 and 249.5 seconds, then naturally changed
to Gameboycolor, measured 21 seconds into that next record. No skip was submitted.
All eight emergency recordings also finished preparation in the real current
voices, four per presenter. A later natural 15-second host gap triggered
`2904e30a355e4401`, without a manual audition. Its original DJ statement played
from 0 to 5.513792 seconds, then the cohost from 5.513792 to 10.978583 seconds.
The actual App listener reported `ended`, two scheduled lines, two acknowledged
lines and complete=true. Both rows retained `emergency_host` and
`coverage_credit=false`. A different reserve pair subsequently advanced through
both lines after the one-minute cooldown. This verifies fallback operation;
the cooldown and finite reserve do not imply uninterrupted original dialogue.

At 100% talk, the empty conversation shelf formerly drove approximately five
failed scheduling attempts per second. Failed rounds now wait five seconds
before retrying. The ordinary writer admission and preparation clocks continue
to retain and repair the missing work.

The station now prepares a separate persistent emergency reserve:
`continuity_reserve.json`, four two-host exchanges in the currently selected
voices and engines. These are plain, clearly identified continuity statements,
authorized by #1060's request for a working fallback when tint cannot finish.
Preparation makes real recordings under the normal engine admission limits.
The media sweeper protects the manifest's recordings even after the original
pantry entries expire, including a fresh process reading the saved manifest.
Playback only spends a fully recorded pair, requires an acknowledged speech gap
and a free conversation floor, follows the selected output, and is limited to
one pair per minute. It never runs a model or voice synthesis on its playback
path. A pause, disabled voice output or changed cast prevents publication.
The measured-gap fallback works at lower talk settings as well as 100% talk.
Both-output selection publishes to both transports, and the page reservation
keeps the floor until its scheduled audio settles. Deliberately disabling device
speech prevents a device-only route from silently bypassing that choice via App.

Every reserve row carries `emergency=true`, `coverage_credit=false` and the
reason it was needed. The hourly controller explicitly excludes emergency
continuity and repertoire auditions from ordinary content-road credit. Failed
tint, accepted scripts and their existing takes remain owed and intact.
The reserve is finite and repeats on rotation during a prolonged outage; it is
service continuity rather than a claim that the requested original program has
been produced. It does not interrupt an accepted conversation to insert status.

`GET /api/dj/continuity` reports current-cast ready counts, preparation state and
the latest reason. `POST /api/dj/continuity/prepare` uses the authenticated
recording path to prepare at most eight missing recordings. The normal show
clock also prepares the reserve in bounded passes.

Ten targeted regressions cover music restoration without debt loss, persistence
of actual reserve clips, missing-file readiness, selected voices and Nabu route,
no live synthesis or volume adjustment, pause/cast guards, repeat cooldown and
the absence of ordinary quota credit. Root's separate resource audit owns
memory, CUDA and service-lifecycle findings.
