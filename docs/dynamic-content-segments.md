# Dynamic content segments

Book Time and Station supercut are reusable scheduled content templates. The
initial running order places Book Time at approximately :15 and :45 for 7.5
minutes each, and a 45-second station supercut at approximately :58 in a 75-second clock entry. Book Time
can be configured within the requested 5 to 10 minute range; the supercut can
be configured from 30 to 60 seconds.

The scheduler's prompt editor uses the existing named alternative shelf in
`data/segment_prompts.json`. An alternative holds its system instruction in
`text`, a separate `generation_prompt`, its enabled switch and weight, and a
small `config` object. The existing fixed, cycle and weighted random modes
select saved alternatives. Saving or changing an alternative invalidates the
prompt memo for that kind so subsequent generation reads the current words.
It does not rewrite already authored, recorded or aired material.

The defaults are installed only when that kind has no saved alternatives.
Operator changes are never replaced by a startup seed. `dynamic_segments.py`
exports detached template copies and a pure `overlay_hour` helper that cuts
clock windows out of an hourly template, preserves unaffected entry IDs and
metadata, retains a clipped entry's prompts and pins on its remainders, and
keeps the hour at sixty minutes. Applying the same overlay again makes no
additional changes. The runtime activation endpoint saves a recurring overlay beginning at the
next full local hour. It preserves the current hour, stock reservations,
queues and already aired receipts. The underlying hourly presets and hour
overrides retain their prompts and metadata.

Book tokens are available to the FM prompt and H3 render prompt paths:

| Token | Content |
| --- | --- |
| `{book}` | Real library title |
| `{booktopic}` | Topic from the selected book section |
| `{bookchapter}` | Chapter or PDF section identifier |
| `{booksegment}` | Selected source passage for discussion |
| `{booksentence}` | One short exact source sentence |
| `{booksentences}` | A short set of source sentences |
| `{sentence}` | Sentence roulette focus, bound to the selected book inside Book Time; other uses remain unchanged |
| `{stationname}` | Configured on-air station name |

Related tokens in the system instruction and generation prompt resolve
against one source draw. A token used without `{book}` can choose a random
book source; `{book:Exact library title}` or `{book:library-id}` and the saved
`book_binding` control can constrain the selection. For example,
`Discuss {booktopic} from {book}, chapter {bookchapter}, and quote
{booksentence}` selects one source for the whole prompt.
Scheduled Book Time keeps its source for the occurrence and chooses another
title for the next segment. Previewing prompt fields does not spend the draw,
advance an alternative, or change Book Mode or its listening receipts.

Extractor cache upgrades preserve frozen episode receipts and title history.
After a restart, the first persisted source receipt for an episode remains
authoritative before prompt expansion. Conflicting drafts keep their original
script, source and audio but are excluded from the episode and repaired using
its original book.

The Book Time default welcomes listeners once, has both DJs introduce
themselves, names the book and chapter, discusses a source section using
short attributed quotations, and closes with their takeaways and a return
to the show. Continuation writing must preserve that occurrence's title and
follow its current opening, discussion or closing phase. A continuation
round does not repeat the whole welcome.

Book Time readiness requires both host seats, enough conversational turns
and events for the duration, measured voice and playable audio coverage,
and actual authored and recorded opening and closing evidence. Each host's
self-introduction must match the A/B actor names frozen in the System3
conversation, retaining any cast aliases. A completed episode also needs an
exact bounded quotation from its source receipt in the frozen recorded words;
a title, topic or paraphrase does not satisfy that check. Index, contents and
other reference sections cannot serve as discussion sources. An older
occurrence bound to such a section is deferred for review with its original
script, recording and source receipt preserved; fresh eligible occurrences
continue normally. The
`book_time_bookends` helper inspects the frozen script's welcome, selected
title and station name, plus its Book Time closing and handoff; an assigned
phase flag by itself does not count as an opening or closing.

The SFX Guy supercut starts with Pine Box FM as the sponsor and item. The
system and generation prompts describe a source clip opening hook, a sales
sequence, a timely clipped stinger, and a verified closing station tag.
Readiness has no synthetic speech quota. It requires the measured audio
body and one complete source-only plan with source clips and verified
opening, sale, closing and station identity. Partial plans cannot combine
flags to claim a completed spot.

The new prompt store fields are compatible with existing alternatives:
a legacy text-only alternative still behaves as before, while an older
editor rewriting `text` without the new fields preserves an existing
`generation_prompt` and `config`. Saved configuration is bounded and JSON
safe. The controls currently cover duration, sponsor, item, station,
optional book binding, clock positions, title uniqueness, source-only
composition, and quote/discussion style.

`segment_prompts.expand_pair` is the host integration point for coherently
previewing or resolving both fields. Its book hook is called once with
both texts, kind, occurrence key, stamp flag, and configuration. The selected
source and rolls are retained in prompt usage provenance and the round
stamp. `occurrence_view` retrieves the already selected words and controls
without making another roulette draw.

Runtime endpoints follow the station's existing authentication:

- `GET /api/dynamic-segments` reports saved prompt shelves, recurring clock
  windows, actual upcoming occurrence source and measured coverage, availability
  and queued preparation requests. Invalid edited clock positions are shown as
  a configuration error without hiding the saved shelves.
- `POST /api/dynamic-segments/{kind}/preview` accepts `text`,
  `generation_prompt` and `config`. It resolves both fields together using a
  preview RNG that respects operator weights without spending live roulette.
- `POST /api/dynamic-segments/activate` commits the current configured windows
  from the next hour after validating the complete sixty-minute overlay.
- `POST /api/dynamic-segments/{kind}/prepare` requests preparation through the
  existing production worker; it does not start a second concurrent writer.

The active System2 adapter treats an episode as one source-bound performance
with one verified playback handoff. Every book part retains the same title,
chapter, exact source receipt and prompt configuration. Generic banter stock
cannot fill Book Time, and a book occurrence cannot fill an ordinary slot.
An independent native timer checks cached ready Book Time and supercut
allocations every half second, so a generic conversation writer waiting on the
model cannot prevent a scheduled playback attempt. It calls the existing native
dispatcher with the exact due slot ID. A clock rollover, pause, disabled station
or priority event during refresh cancels that attempt before reservation or
publication. Existing media checks, whole-performance fit, reservation ownership,
listener acknowledgments and replay protection still control delivery. Only a
published performance from this timer retains its completion owner if the timer
stops; unpublished work is canceled and released normally.

Book Time owns a 450-second wall window by default. Preparation reserves a
bounded transport overhead inside that window and requires the remaining
content budget as measured spoken audio, both hosts and actual bookends.
Transport gaps never count as speech. A measured shortfall adds source-bound
discussion before the frozen closing; an overlong discussion can be re-authored
before air, preserving the opening, closing and original stored WAVs. Final
bundled playback must fit the wall window with its actual ordered take count.

The supercut target controls source audio duration. Its clock entry also leaves
room for the existing transport guard and a bounded wait for the current
clip to finish: the default 45-second audio occupies a
75-second entry. Readiness still checks the actual source frames and complete
source-only structure; the guard is reported separately and does not count as
content. The original source clips and their cut provenance are retained.
Complete-catalog scoring runs in its own read-only worker and evaluates every
playable row. If it exceeds the six-second production wait, the same outstanding
scan is retained for the next visit so Book Time and other native production can
continue. Vector scoring uses bounded batches without loading another complete
vector matrix. Existing transcripts and metadata are used immediately; clips
whose audio has not been studied stay visible as pending analysis. Source audio
verification retains its separate sixteen-second budget after scoring completes.

Phase validation runs before recording as well as before publication. Only the
opening part may welcome listeners, and only the closing part may sign off.
An episode requires exactly one of each. A draft that closes early or repeats
the welcome remains available for review, is barred from recording/air and
gets a bounded worker retry for that same phase. Full custom prompts, the
continuation and the final phase instruction remain in the source context so
System3's shortened topic label cannot drop operator instructions.
System3 copy comparisons allow the validated opening's actual book title and
chapter heading and bounded exact source quotations. The station keeps the
original spoken words and source receipts. Only those attested spans leave the
comparison; copied reactions, long passages, other topic-card prose and invalid
receipts retain their original gates. This applies to generation, recovery and
final handoff under the frozen source context.

A recorded opening with swapped host introductions is withheld and repaired
for the same frozen eligible source. The original script, WAV keys and source
receipt remain available for review. A completed episode missing its bound
quotation likewise stays unready: the production worker can re-author a
discussion part with the exact bounded source quote, preserving its original
WAV and the one opening/closing. The replacement must be recorded before air;
quotation repairs are bounded to three accepted replacement attempts per
occurrence. Counts survive recording retries and are retained on stored
replacement rows.
