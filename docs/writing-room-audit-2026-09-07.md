# Writing-room coordination audit — 2026-09-07

The paused station had substantial retained work but idle voice booths. A
read-only snapshot of `/api/orchestrator/rejections/context` reported 143
scripts, 123 awaiting tint, 95 waiting for recording, zero recordings in
progress, and 48 rows carrying a prepared flag. Those flags are not a claim
that all 48 rows satisfy current readiness. `/api/recording-room` independently
showed zero active voice engines while model writers remained active.

The operator's settings were unchanged: tint holding enabled, coverage 100%,
meaning grading, and DOOM strength 0.88. A SQLite read-only query found 170
unique review records and 218 occurrences in the observed 30-minute window,
covering 101 distinct gate/source/kind combinations. Of those records, 130
were tint rejections. Semantic preservation appeared in 92 records and missing
rhyme in 52; one caller source produced nine different rejected candidates.
The review feed therefore exposes both genuine failed writing and repeated
attempts at the same source. No review was approved or rejected by this audit.

| Finding | Consequence | Change |
| --- | --- | --- |
| `_ollama_category()` exempted every tint request from admission limits, while status advertised only the station cap of two. | Three or more same-model tint jobs could queue; the display obscured why the apparent cap was exceeded. | Tint now admits two jobs per model. Status includes each job's category, all category limits, and deferred counts by category. |
| `_tint_turn_yields()` parked single-line requests before registering them. | Waiting work was invisible and new rounds could repeatedly overtake it. | Admitted requests now enter the visible model FIFO directly. |
| A denied `ask_model()` request returned an empty string to tint helpers. | Restoring a cap alone would manufacture empty-output and unchanged-text rejections. | `WritingDeferred` bypasses model-output grading. `crystal_tint()` returns an explicit deferred result with original, completed and unvisited progress preserved; a deferred repass carries candidates already repaired in its earlier pass. |
| Paused-hour and caller-floor overrides could commission more scripts despite viable assigned unfinished rows. The separate banter keeper had its own bypass. | The writer could add more work while existing scripts still needed the same model and recording rooms. | Both fresh-writing doors consult `prep_has_assigned_work()`. Unusable stock still permits a replacement; ready stock does not block new demand. |
| After a whole pass and two batched repairs, the outer loop invoked the per-line repair stack again. That stack already includes fidelity and evaluator repairs. | A stubborn source could multiply model visits inside a single round. | Once batching has run, the per-line stack runs once. Failed lines keep their failed evaluation and retained recovery evidence; accepted lines keep their exact text. |

The recording-selection audit was handed to the newspaper agent. Its concrete
finding was a first committed ad or station-ID row whose failed tint returned
before later rows reached voice. The same owner handled persisted `tinting`
and `preparing` flags in raw shelf rows and stale `repairing` audit states
after restart. These are separate from admission and must be checked together
when verifying recovery.

The new coordination tests use mocked model transports and isolated data.
They check bounded admission, visible waiters, no fabricated rejection on
deferral, retained successful and unvisited candidates, restoration of the
borrowed deadline, one nested repair stack after batching, both fresh-writing
doors, and replacement of genuinely unusable work. Rejection-review tests
remain in the full suite; no live generation or TTS is used by these checks.

The capacity endpoint reported a 10.38 ratio from observed task latency during
the snapshot. It explicitly included queue wait and marked `physical_ceiling`
false. That is a congestion estimate, not proof that the hardware needs ten
hours to perform an hour's useful work. The integrated audit subsequently
corrected `prep_measure()`: declared admission deferral does not count as a
production failure, including deferral returned by a child tint task. Other
jobs' audio and on-air Piper activity no longer become this task's measured
gain or engine cost. Unknown gain is disclosed and prior samples remain
intact. Elapsed task costs can still contain waits; a controlled service-time
benchmark is not claimed.

The [integrated audit](pipeline-audit-2026-09-07.md) records deployment, actual
bounded category counts, newly recorded voice takes and real listener
acknowledgments. These changes preserve the operator's strict editorial
settings; they cannot guarantee that an unsuitable rewrite passes them.
