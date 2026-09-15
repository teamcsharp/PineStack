# Script incident diagnostics, version 2

Implemented 2026-09-14 following the sequential-playout audit.

## What a tap records

The Script view keeps a passive, bounded sixty-second history. Tapping `!`
immediately submits that history and a snapshot. Ten seconds of subsequent
observations and the screenshot finish the same incident. The initial report
is durable before its screenshot or follow-up arrives.

Repeated observations are coalesced into records with first/last timestamps,
sample counts and start/end media positions. Changes of highlighted identity,
document revision, file, player source, scroll position or player state remain
distinct. Overlapping taps each retain their own history.

Line text lives once in a keyed row table. Context includes the lines around
the highlight, or the actual active line/visible viewport when nothing is
highlighted. Audio mappings include nearby cue windows and the claimed active
and highlighted identities, including when those claims name another file.
Distant cues in a long recording do not displace the relevant rows.

## Evidence and interpretation

- Full line IDs, document revisions, media identities and cue offsets.
- Actual playhead position from `bridge.t` or local `currentTime`; estimated
  and unavailable positions are explicitly distinguished.
- Local player mute/volume, readiness, network and buffer state when available.
  The desktop bridge does not provide all those properties; unavailable data
  remains explicit.
- The selected output, relevant server feed/queue records, bounded browser
  playback receipts, and recent loop stalls, without a disk-wide log scan.
- Client, server and screenshot observation timestamps remain separate.
- Explicit counts distinguish deliberate exclusion of distant cues from
  evidence dropped because a recorder or payload limit was reached.

The analyzer distinguishes a line being repositioned in the document from a
change to an earlier highlighted identity. It can also identify mismatched
media and observed position regressions. These are observations, not proof of
what physically sounded at the speaker. Prepared/published rows are not
promoted to heard audio by the reporter.

The recorder does not scroll, seek or repair playback. Its caution control
survives document reconciliation and cannot become the viewport's anchor.

## Files and compatibility

Each incident has a unique numeric-suffixed `script_*.md` summary and a single
`script_*.json` evidence file under `data/script_reports/`. The JSON is bounded
before serialization; serialized JSON is never sliced. Markdown links to that
one evidence file instead of repeating motion, context, screen text and full
station state several times.

The screenshot is saved once. Its reference is attached to the existing inbox
request, preserving full-screen viewing and annotation. Retries do not create
another request/image or restore an original image after the operator edits
it. A missing/deleted inbox item is not recreated. An incomplete report is not
cached as final in the Script inbox viewer.

Legacy report files remain readable. Legacy clients can still submit, with
their positional evidence preserved as legacy data rather than interpreted as
version 2 playback observations. New clients retain at most three failed
follow-up payloads for retry; screenshot bytes are not kept in that retry store.

Endpoints:

- `GET /api/script/report/status`: recorder schema and capture windows.
- `POST /api/script/report`: save the initial incident and create its inbox reference.
- `POST /api/script/report/{name}.md/finish`: attach follow-up evidence idempotently.
- `GET /api/script-reports/{name}.md`: compact summary, including completion status.
- `GET /api/script-reports/{name}.json`: complete bounded evidence.

## Implementation and verification

Pure client recorder: `desktop/renderer/script-diagnostics.js`.
Client integration: `desktop/renderer/script-page.js`.
Pure normalization/analysis: `script_diagnostics.py`.
Atomic incident storage: `script_report_store.py`.
Station snapshots and route integration: `app.py`.

Tests cover coalescing, overlapping taps, playhead source selection, long-file
context bounds, unlit viewport context, valid bounded JSON, cautious anomaly
classification, screenshot timing, durable initial capture, rapid unique
filenames, idempotent completion, authentication, legacy reads, and preserving
operator image edits. Endpoint tests compile only the report functions into
an isolated ASGI application; they never import/start the station or write to
its live stores.

The full application still has pre-existing lint findings outside this change.
The diagnostics modules and their route tests have no pyflakes findings.

This implements the diagnostics portion of the audit. Enforcing one committed
playback sequence across all producers remains separate implementation work.
