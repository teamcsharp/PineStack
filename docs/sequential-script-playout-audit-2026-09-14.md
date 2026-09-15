# Sequential script and playout audit

Date: 2026-09-14. Scope: investigation and design discussion; no broadcast implementation or deployment.

Follow-up: the diagnostics portion is now implemented; see
[Script incident diagnostics, version 2](notes/script-report-diagnostics.md).
The findings below describe the code inspected during the original audit.

Recording workflow follow-up: the operator selected one complete conversation
or segment per performer session. See
[Recording speakers and assembling conversations](notes/speaker-recording-and-script-assembly.md)
for the proposed master recordings, verified cuts and final audio cue contract.

## Required behavior

The operator wants the broadcast and Script view to progress through the same committed sequence, line by line. The operator selected this fallback policy during the investigation:

> Choose a ready replacement before it enters the committed script, then play it in order.

This establishes the boundary: planning can change; the admitted reading order cannot. Preparation, emergency fill and SFX must all respect that boundary.

## Evidence reviewed

- The two open requests in `data/pine_requests.md`: #1146 (out-of-order lines and quiet speech) and #1140 (full-screen report images with finger annotation), including the attached #1140 image.
- Nineteen September 14 files in `data/script_reports`: seventeen substantial captures and two test/dry captures.
- The script-ledger history, scheduler and orchestrator documentation, current backend and renderer code, and relevant tests.
- Live read-only requests: `/healthz` returned healthy and `/api/dj/state` returned an active broadcast. `/api/screenplay` timed out during this audit; no current live ordering measurement was obtained from that request.

### What the captures establish

Across the seventeen substantial captures, eight contain backward highlight movements representing five distinct recorded events. Nearby reports repeat some events. These are measurements of the display, not independent evidence of the acoustic playback order.

The clearest example is `data/script_reports/script_2026-09-14_212305.md`: the highlight moves from element 1909 to 1538, then to 1884 within approximately 2.7 seconds. It briefly selects an older gallery block before returning to the current material.

The latest report, `script_2026-09-14_222009.md`, contains sixty samples with no highlighted line and a station-side report of approximately sixteen seconds without speech. That is a separate symptom from a backward movement. Music was reported as playing; absence of speech does not establish complete audio silence.

All seventeen substantial reports truncate their main page-state JSON at approximately 30,000 characters, leaving invalid JSON. Their separate sequence-check and station-state sections remain useful, but the original page evidence is incomplete.

Some automated explanations are demonstrably wrong. Reports around 21:22-21:23 describe blocks 6699 and 6700 as duplicate copies. Inspection of the ledger finds three and seven rows respectively, with no shared line IDs or identical texts: those are separate portions of a conversation. Treat generated explanations as hypotheses until their claims are checked against the underlying events.

## Current causes and gaps

References below identify the source as inspected; line numbers may move with subsequent work.

### 1. The ledger does not authorize playback

`script_ledger_commit` explicitly tolerates failure without stopping the broadcast (`app.py:133346`; caller at `83825`). Rescue, adverts, gold bars and other producers can reach the feed through other paths. `script_ledger_catch_up` assigns positions afterward (`133415`), through the keeper that watches the many append sites (`132578`).

Thus the ledger is partly a record of what happened. It is not yet the instruction that every playback path must obey.

### 2. The page still reconstructs positions from changing estimates

The compositor's anchor condition accepts a positive `air_at` (`app.py:134865`). Prepared rows already receive estimated positive `air_at` values before delivery (`83875` onward). Consequently, a row can anchor another event before it is actually heard, and later changes to estimates can change the reconstructed placement.

`AIR_AT_HEARD` includes `published` and `airing` (`24328`), although publication and buffering alone do not establish audible playback. The existing playback tests explicitly distinguish those states.

### 3. The renderer can select a line from a different audio file

`activeRow()` first searches feed metadata for the playing file, then falls back to burst rows without requiring their file identity (`desktop/renderer/script-page.js:3480`, `3523`). A read-only execution of those functions returned an old burst's line while a new file was playing.

When a real playhead is unavailable, the view can also use wall-clock estimates adjusted by the latest poll (`3400`). There is no playback-occurrence and sequence guard on every change of highlight (`3620`).

### 4. Announcing intent and starting audio are different events

The burst path sets `_STREAM_NOW` before awaiting `_play_on_box` (`app.py:84118`). The box transport still has to acquire its lock and prepare delivery (`22060`). A clock started at handoff can therefore advance before audio starts.

The single-line speaking state and stream speaking state also have separate lifetimes and precedence (`28023`). An interjection can select one while the other clock continues advancing.

### 5. Reporting and scrolling interfere with the evidence

- The motion recorder reads playhead `position` or `at`; the desktop bridge actually provides elapsed seconds in `t`. `at` is its arrival timestamp (`script-page.js:1818`; `renderer.js:935`).
- The recorder labels samples without a bridge as estimated even when a local audio element is available. This explains why the saved motion can say `e` while the snapshot says `headIsRead: true`.
- Motion records moving DOM indices and shortened IDs without document revision or playback occurrence. A negative index change can mean document movement rather than a different earlier line.
- The caution button's sticky wrapper can become the viewport anchor, then be removed during reconciliation (`script-page.js:1902`, `2851`, `2885`; `script-page.css:973`). The anchor cannot then be restored.
- The recorder itself calls `scrollIntoView` (`1839`), adding another source of scrolling.
- Client state is captured before an optional screenshot delay; server state is sampled after submission. They can describe different instants (`2037`, `2097`; `app.py:108189`).
- Report filenames have only second precision, allowing rapid submissions to share a filename (`app.py:108347`).

## Proposed architecture

```text
Writers / preparation / SFX / rescue
                 |
         Mutable candidate plan
                 |
  Choose ready material and finalize audio
                 |
     Atomic admission to committed script
                 |
       One ordered playout controller
                 |
       Selected output / audio player
                 |
       Playback receipts and playhead
                 |
              Script view
```

### Admission

Before committing a segment, verify that its final audio is available and its ordered line/cue offsets are known. Choose a ready replacement here when necessary. Commit a unique playback occurrence, ordered sequence positions, exact audio identity and cue sheet together.

A reusable sample's content ID is not its playback occurrence ID. Playing the same sting twice produces two distinct occurrences in the script.

Existing welded round files are useful: they already preserve internal audio order. Retain those files and give them an authoritative cue sheet rather than rebuilding voice generation.

### Playback

Give one controller sole responsibility for dispatch and advancement. The existing transport boundaries `_play_on_box` (`app.py:21922`) and `page_feed_append` (`23868`) must require admission from the same controller. Producers, watchdogs and scheduling clocks submit candidates instead of starting broadcast audio themselves.

Keep a ready buffer so selection happens ahead of the reader. Random SFX is still possible: decide its slot before admitting the affected material. A live interruption can be admitted at a future safe boundary; it must not rewrite positions already committed to the reader.

### Display

Render the committed sequence directly. Keep existing positions stable as new material is appended. Use the selected player's actual file and offset, mapped through its cue sheet, to identify the active occurrence. Buffered outputs need their own playback position, rather than the server's current wall-clock position.

Use one scroll controller. Preserve the last trustworthy position when playback evidence is unavailable and expose the synchronization state. Merely preventing a backward visual movement would hide an audio fault; it would not enforce playback order.

### Recovery

After admission, a delivery failure must retain the committed identity and position. Record blocked, interrupted or uncertain delivery explicitly. Reconcile the player or resume from a trustworthy checkpoint before advancing. A route change or restart needs an ownership generation so late messages from the previous player cannot advance the current broadcast.

Do not equate a command acknowledgment with proof that sound reached a speaker. Deterministic dispatch is enforceable; acoustic exactly-once delivery during a disconnected or failed device requires telemetry that some outputs may not provide.

## The exclamation button

Make a tap freeze a passive incident recording immediately. Suggested retention: sixty seconds before and fifteen seconds after the tap, stored under a unique incident ID. An optional annotation step can follow without delaying the evidence capture; this also accommodates #1140's full-screen image and red finger drawing request.

Preserve:

- Full occurrence and line IDs, sequence positions, document revision, player/output identity and ownership generation.
- Actual media file, playback offset, start/end/error events and queue head.
- Planning replacements and their recorded reasons; admission, dispatch and acknowledgment events.
- Original client and server timestamps, observation source and freshness.
- Screenshot, viewport state, actual highlighted row and operator note.

Keep raw JSON valid and separate from the readable summary. The explanation should link its claims to those events and distinguish a confirmed order violation, a missing/stale display mapping, a scroll movement and a gap in speech. Automatically preserve incidents when a sequence invariant fails; tapping remains the operator's way to add observations the system cannot detect.

## Implementation sequence and acceptance

1. Repair capture and reproduce the concrete stale-file and scroll-anchor failures.
2. Introduce the admission store and sequencer behind the existing transports; audit every broadcast producer and recovery path.
3. Switch the live script to the admitted sequence and actual playback position.
4. Prove behavior with independent transport traces, then validate on the actual selected Pine Box output.

Acceptance requires every started occurrence to have been committed first, every next occurrence to follow the admitted sequence, and existing committed positions to remain unchanged. Include SFX, adverts, rescue and music cues as appropriate; formatting headings are not playback steps.

Exercise late/out-of-order preparation, competing producers, repeated sample reuse, duplicate and delayed acknowledgments, stalled polling, ownership changes, disconnect/reconnect, pause/resume, hour rollover, and crashes around admission and handoff. Validate speech continuity separately from ordering: a stationary cursor during an intended music section is not an order failure.

## Validation performed and limits

The existing Node bridge and script-view suites passed 40/40. They do not exercise the reproduced `activeRow()` failure or establish global playback order. The stale-file selection was reproduced using an isolated read-only execution of the current functions.

Backend tests were inspected, not run against shared runtime data. Some fixtures do not redirect the script-ledger writer and could append fixture rows to the live ledger. Future tests must isolate all runtime stores.

This audit proves specific display and architecture defects. It does not establish that every saved visible jump was also audible, nor that the current physical output has been verified end to end.
