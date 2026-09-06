# Broadcast preparation and delivery audit — inbox #1057

This audit follows accepted dialogue from the running order through writing,
tint approval, recording, prepared inventory, transport publication and listener
completion. It distinguishes finished audio from words awaiting a recording,
and publication from observed playback.

The existing orchestrator already maintained a schedule inventory, measured
production costs, active-airtime hour contracts, persistent road learning and
pause yield. The gaps were in execution and reconciliation: some partial work
could never become ready, some missing turns could be overtaken, and recovery
queues silently discarded work. These faults were repaired without treating
more concurrent requests as additional hardware throughput.

## Execution findings and repairs

| Stage | Finding | Resulting behavior |
| --- | --- | --- |
| Engine admission | The old `>` comparison could admit a fourth render against a three-slot budget. | Admission checks the post-acquisition ceiling. The normal preparation allowance leaves two slots for live rendering. While paused, preparation may use the whole configured budget. |
| Parallel recording | Pooled sittings ran only one engine at a time. | Independent engine booths can run concurrently during a pause, with one preparation render per engine and exclusive ownership of each script. Context-local deadlines keep one booth from changing another booth's time allowance. Fallback engine reservations share the same accounting. |
| Actor sittings | A pass for one actor counted only that actor's lines. The next actor's pass could never close the complete round. | Every pass reconciles the entire original script against existing takes, including other actors' completed audio. |
| Repeated lines | Indexing takes by `(text, voice, speaker)` collapsed repeated words at different script positions. | Inventory retains every script position in order. Identical audio can serve multiple positions without losing those positions. |
| Missing files and durations | Old counters could survive after a take disappeared or be incremented repeatedly. | Reconciliation rebuilds keys, positions, made count and duration from audio that actually exists. |
| Caller preparation | Transcript offsets still treated every caller as live-only, although banked callers have stored voices and phone effects. | Recorded caller turns occupy their correct prepared positions. A genuinely unassigned voice keeps the whole round unready. |
| Partial readiness | A useful opening could be marked as a prepared round. | The opening remains useful partial progress; readiness requires every planned line. Tint and conversation gates remain in force. |
| Long utterances | Failed sub-renders could produce a shortened clip; failed concatenation could return only the first chunk under the full text's name. | A long utterance succeeds only when every piece exists and the complete join succeeds. Failure leaves the full line owed. |
| Stream batches | Booth conversations could publish later turns after a missing turn, then discard the hole as too late to recover. | All conversations stop at their first missing turn. The complete ordered tail moves to recovery. A failed concatenation likewise stops later batches from passing it. |
| Pause boundaries | A non-caller round could abandon its tail when paused between stream pages. | The accepted tail waits for resume. A deliberately paused floor retains its lease rather than appearing abandoned. |
| Single-line recovery | A failed turn could be followed by its answer; an unrendered queue was limited to 40 lines, expired after 20 minutes and was lost on restart. | The failed turn and its remaining accepted tail are saved in `render_backlog.json` in order, including available clips, voices and effects. The head must complete before recovery publishes its tail. |
| Audio hold shelf | Age/count trims could remove unheard audio. Concurrent consumers could play the same head and then remove the next unheard row. | Unheard stock is retained. The hold drain uses serialized replay and removes only the exact verified row. Explicit operator clearing remains available. |
| Transport time | Explicitly scheduled streams did not reserve their duration centrally; ordinary producers estimated at most 40 seconds. | Every ordinary delivery reserves its actual known/measured duration. All producers share that timeline. Operator replies retain their intentional immediate routing. |
| Playback evidence | A queued delivery alone could appear to cover the conversation. | Per-delivery audits expose scheduled line count, acknowledged count, exact unconfirmed IDs and completion. Received, buffered and muted playback do not credit speech. |
| Listening responses | Added acknowledgments could consume the content limit, be skipped after the final host turn, or create an interruption point inside an unfinished sentence sequence. | Content limits exclude acknowledgments and allow attached final responses. A continuation response does not make an unfinished speaker turn interruptible. Durable response clips count as prepared audio in whole-stream assembly. |

## Memory and corrective decisions

`station_flow.sqlite3` persists each closed hour's requirement score, road
attainment, measured production, paused preparation gains, failures and decisions.
Recent scorecards from the older coordinator store are imported without repeated
copies. The existing local embedding model indexes outcomes asynchronously;
failure or absence of that service leaves searchable lexical evidence available.
Only measured broadcast outcomes enter this retrieval set, so ordinary pipeline
narration cannot impersonate a historical result.

`GET /api/coordinator/memory?q=...` returns evidence IDs, full retained reports,
the retrieval method (`neural`, `lexical` or `recent`), the embedding model,
learning state and measured capacity. Indexing old outcomes may finish shortly
after the first request. New hours are recorded and indexed automatically.

The numeric controller remains the authority for preparation decisions. Closed
hour misses raise bounded road priority and can authorize an already permitted
fallback voice. Three consecutive missed contracts now produce a concrete,
reversible build-first work order for the most deficient road when no operator
pin is active. The controller releases its own recovery pin after that road meets
its contract. An operator's existing pin is respected. Each action carries the
hour identity, attainment and miss streak that caused it. The attainment moving
average now retains a real zero instead of replacing it with the next result.

This is measured feedback and retrieval of prior outcomes. It does not claim
that a language model rewrites station source code or that neural similarity
proves one operational policy caused a later improvement.

## Inspection and validation

* `/api/recording-room` includes current booth capacity, preparation limit,
  live/preparation usage and active engine lanes. Its `tint_recovery` member
  reports legacy proof checks, repair attempts, preserved audio, remaining
  coverage and the reason each pending row is still owed.
* `/api/dj/flow` includes delivery line audits under
  `health.last_delivery.line_audit`, alongside listener events and the talk-gap
  measurement.
* `/api/coordinator/hourly` retains the active requirement contract, pause yield,
  closed scores and learned corrections.
* `/api/coordinator/memory` searches durable broadcast outcomes.

Regression coverage in `test_orchestrator_execution.py` exercises actual actor
sittings, concurrent independent booths, script ownership, admission limits,
duplicate positions, missing audio pieces, concatenation failures, durable
recovery, head-before-tail retry, full-tail preservation, final listening
responses and persisted neural/lexical search. `test_playback_flow.py` checks
receipt versus audibility, muted players, advancing positions, out-of-order
acknowledgments, stream windows, duration reservations and exact unconfirmed
line audits. Existing schedule readiness tests cover FIFO inventory ownership,
current tint, pause accounting and hour feedback.

The Linux deployment environment passed all 190 Python tests after these
changes, including the separately reviewed hold-drain regression additions,
concurrent memory import, embedding retry, operator policy ownership, legacy
proof recovery and exact conversation parsing.
These tests isolate external voice, LLM and playback services; deployment checks
must separately verify real engine output and listener acknowledgments.

The live baseline reported approximately 50 minutes of requested speech and an
estimated 406 minutes of room occupancy per hour (`over = 6.78`). Inspection found
that the task-cost ledger includes queue waiting: concurrently waiting producers
can count the same serialized model work more than once. This is evidence of a
congested pipeline, not a physical hardware ceiling. The capacity API now labels
its basis `observed_task_latency`, `includes_queue_wait=true` and
`physical_ceiling=false`. Historical latency samples remain historical facts;
new bounded-admission measurements will replace them as the ledger advances.
Neither this estimate nor the number of software booths establishes the fresh
schedule's sustainable throughput. If engines or outputs are unavailable, the
system retains and reports debt; it does not claim unheard lines completed.

## Legacy inventory and restart recovery

The deployment check found 1,352 persisted pantry clips totaling about 22,865
seconds, with every referenced audio file present. However, the seven complete
larder rounds and other older shelf entries only carried the earlier `ok` tint
stamp. They lacked the newer enforced coverage/evaluation evidence, so the
honest ready reserve fell to 96.8 seconds (six exempt track-talk clips). The
audio was not deleted or lost during restore.

Rechecking the actual original/rewrite pairs at the active 88% strength found
one passing legacy ad and no completely passing larder or news round. Many
Speakerbox turns were unchanged; other turns failed the meaning, rhyme or source
copying screen. Treating all old `ok` stamps as current proof would conceal this
debt. The spelling/content evaluator is a conservative screen, with its limits
included in each report, rather than a semantic or phonetic certainty.

`tint_recovery_clock` now inspects persisted pairs off the event loop and
restores current proof only after every selected line passes with the original
source passages. Missing pairs, missing passages and genuine failed lines
remain owed. Every take stays intact while a rewrite is unproved. Valid old
candidate lines retain their original positions in resumable progress; a failed
early retry no longer discards good unvisited tail candidates. Changed words
reopen their recording plan, where unchanged line hashes reuse existing audio.

The recovery worker gives one eligible row a turn, respects the writer's
pressure and operator interruption gates, records attempts and cooldowns, and
continues after failed rows. It does not wait for the shelf to look full before
repairing required tint. Startup also clears stranded tint ownership, and
`/api/dj/pending` now reports real readiness instead of trusting `prepared=True`.

Conversation parsing retains every explicit speaker and every final turn,
including a host continuation and a final sentence without punctuation. Draft
validation can refuse incomplete writing while retaining its whole text for
repair; parsing itself no longer deletes words or assigns them to another voice.

Live verification also confirmed 45 persisted outcome reports with three
indexed through the installed `nomic-embed-text` model and actual neural search
results. An actual post-restart delivery reached `ended` with one scheduled and
one acknowledged line. These are observed capabilities, not a claim that every
historical broadcast met its content contract.

## Writer admission and deployment evidence

The global two-request model gate previously hid a queue in front of each
single-model lane. Empty caller clocks could repeatedly launch the same producer,
and some observed waits reached 671 seconds for less than a second of model work.
Preparation now coalesces each road's in-flight job. Model admission allows two
station jobs per model (one active and one waiting) and one separately bounded
repertoire job. Deferred tint leaves its accepted script, recordings and resumable
work intact, records a waiting reason and retries later. Interactive requests
retain their own admission behavior. `/api/recording-room.writers` exposes actual
active jobs, model waiters and deferred counts. Preparation deadlines are local
to their coroutine, including legacy deadline setters, so one clock cannot stop
an independent response recorder or writer with its expired deadline.

After restart the live e2b model had one active station writer, one station tint
waiter and one repertoire waiter; 75 additional producer attempts were deferred.
Recent completed waits measured 2.8–45.6 seconds, with 2.8–35.8 seconds of work.
A later snapshot showed e2b and 31b doing work concurrently. These observations
verify bounded station admissions; they do not exclude queues from other clients
of the model service.

A real four-line recorded audition, delivery `9d4fee5cdee44284`, used these
unchanged current-cast recordings and exact decoded sample offsets:

| Order | Presenter / voice | Words | Stream interval (seconds) |
| --- | --- | --- | --- |
| 1 | DJ / `vl_a5cc23e4` | I'm listening. | 0–1.772125 |
| 2 | Cohost / `vl_62f8434c` | Go on. | 1.772125–3.181167 |
| 3 | DJ / `vl_a5cc23e4` | I hear you. | 3.181167–4.916 |
| 4 | Cohost / `vl_62f8434c` | Yeah. | 4.916–6.215583 |

Listener `pb0mjkaxf5` reported advancing positions 0, 1.773, 3.633, 5.501 and
an `ended` event at 6.215583 seconds, audible volume 0.224. The delivery audit
reported four scheduled lines, four acknowledged lines, no unconfirmed IDs and
complete=true. No synthetic receipts were submitted. The initial operator HTTP
request exceeded its 120-second timeout before the stream published; the old
audition route awaited the floor without a bound and the disconnected request
continued. The API now cancels its own waiter after 30 seconds and returns an
explicit rejection without queuing audio or interrupting the current round.
The precise earlier floor owner was not retained, so its identity is not claimed.

A final 60-second pause check restored the original unpaused state in `finally`.
The preparation allowance rose to three; one XTTS preparation lane was active
at entry. Cohost ready response recordings rose from 18 to 19 (source recordings
10 to 11), while DJ recordings stayed at 19 (11 source recordings). Written
larder entries increased from seven to eight. Whole-program ready seconds stayed
107.8 and the ordinary recording-room take counter stayed zero; response-bank
recordings have their own counter. One legacy caller rewrite failed the required
tint screen and the worker advanced to another. This proves continuing paused
writing and a finished response recording, while whole-round tint repair and
simultaneous independent voice-engine output remain unproven in that interval.

Live neural memory later held 46 outcomes with four indexed and actual neural
retrieval. Legacy failed/unknown tint still represents substantial outstanding
program inventory; the implementation preserves and retries it without awarding
unearned coverage. Admission, cancellation, deferred tint preservation, exact
audition offsets, unready/wrong-voice rejection and busy-floor cancellation have
dedicated regressions in the writing admission, tint recovery and audition tests.

The later #1060 recovery also exercised an actual interrupted delivery across
deployment. A 13.3685-second WAV with an unfinalized streaming header had been
misread as 89,478 seconds, placing the next accepted caller nearly 25 hours in
the future. Actual PCM byte counts now determine WAV duration. FIFO reservation
repair preserves existing delivery IDs and words, and a saved recovery queue
retains pending content until actual completion. Original caller delivery
`406cf37adba44060` survived restart unchanged and subsequently reached `ended`
with all ten scheduled lines acknowledged and no unconfirmed rows. Its recovery
file was cleared only after those receipts. The ordinary show then published a
different ten-line call, `6d5a2a0b299749de`, which began advancing audibly. The
complete integration suite passed 249 tests before that deployment. These are
App playback observations under the operator's current App routing.
That second call subsequently ended with all ten lines acknowledged, followed
by an audible ordinary single host line. Without a submitted skip, the music
progressed naturally from Comet2 to Gameboycolor. All eight actual emergency
continuity recordings finished preparation. A later natural speech gap triggered
the first reserve pair without a manual audition: delivery `2904e30a355e4401`
ended with two scheduled and two acknowledged lines over 10.978583 seconds.
The DJ spoke first, followed by the cohost at 5.513792 seconds. Both remain
explicit emergency rows without ordinary content-quota credit, and a different
pair subsequently played after the one-minute cooldown.
