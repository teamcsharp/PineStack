# The rhyming, the ten-second rule, and the calls that finish

Four parallel scans of the live station on the night of 2026-09-08, each measured on the real
material: four days of aired lines (6,000), the crystal's own 23,836-word lexicon, the stored rounds
and the 400 gold bars. The operator's asks, in their words: *"I dont want to hear them rhyming just
with must repeatedly… using the rhyming words from the doom crystal… hosts and callers competing to
make the dopest raps"*, *"these phone calls to complete. Currently they cut off partway… I dont like
hearing the customers just vaporized"*, and *"at longest a 10 second intermission… a deep repetoire
of dialogue to fill in all the dead air"*.

## What was actually wrong

**The repetition was not the writer.** Over four days, **17 lines carried 1,085 of the 6,000
airings** — one couplet 108 times, another 100. Every one of the eight lines that aired more than a
hundred times is a *continuity reserve* line: a bank of 28, tried before the bank of 400. The
freshly written bars are varied (2,629 distinct landings over 6,496 endings, 63% used exactly once).

**But the writer landed on furniture, and the grader made it.** Only 13.2% of landings were a
distinctive crystal word; 82% carried no syllable past the stress; a proven multisyllabic pair
appeared in **0.0%** of accepted turns. The cause is measured: bars written in the crystal's register
fail the real grader **four times in six**, and *every* failure is the meaning contract's anchor
floor, not one a rhyme fault. The rule that satisfies both gates — keep the source's words in the
body, spend the crystal on the landings — **had never been stated in the prompt**. Written to that
rule, the same sources pass three times in four.

**The rhyme suggestions were alphabetical.** `rhyme_options_for` walked a *sorted* vocabulary and
stopped at the first forty hits, so **70% of every word it offered began with a, b or c**: "rhymes
with 'be' — ability, adhd, albee, anarchy, apology, avi, bbc, brea". A monotony generator upstream of
everything the listener hears. And the fluid-acceptance block told the writer, in as many words,
*"do not add an unusual style word"* — the operator's ask reversed, forty lines after the strength
demand says "all the way".

**The calls were paged.** An eleven-turn call was split 2/4/5, and the air *stopped at each boundary
to wait for the next page's text-to-speech*. **18 of 62 calls that rang on air (29%) never said
goodbye**, and every one of them has a hole of 36 seconds or more inside the call — 121 seconds in
one case — while the clean ones are all under twenty. The escape hatch already existed: a round
whose every take is on disk airs as one piece. Calls that had all their audio finished properly;
calls still rendering died at page two.

**The ten-second rule was missed in 56% of intermissions** (2,321 of 4,143; 93% of elapsed on-air
time sits inside a violation; median 13 s, p90 103 s). Between *rounds* the rule was met **zero times
in 1,601 gaps**. The reason is not an empty bank: a run of gold bars holds a **6-second median gap
(86% inside ten seconds)**, while a run of continuity holds a **32-second mean (46%)** because it is
rate-limited to one airing a minute. The deep bank was tried third, behind the shallow one, and was
forbidden entirely while a round held the floor for a render — so 52 minutes of finished rhymed audio
sat on disk through 20% of all on-air time.

## What shipped

**The rhyme dictionary** (`pine_rhyme.py`, `data/rhyme_families.json`, zero model asks)
1. The crystal's **rhyme families**: every crystal word grouped by its pronunciation tail from the
   final stressed vowel, so a family perfectly rhymes *by the grader's own reading*. Measured on
   DOOM: **6,863 families over 17,288 words, 6,069 of them multisyllabic**; 9,298 words have five or
   more perfect partners inside the crystal. Built in 10 seconds in the worker thread that already
   reads the crystal's vocabulary, 2.7 MB on disk, memoised, a warm ask 0.01 ms against the 442 ms
   the old scan cost.
2. Ranked by **distinctiveness**: frequent in the crystal, rare in ordinary English (WordNet tagged
   counts), more syllables after the stress, never a function word and never the station's own
   furniture. The furniture list is derived, not guessed — the words the air over-uses against the
   crystal's own frequency. `station` now answers *meditation, inspiration, intoxication,
   reincarnation, personification* where it used to answer *abomination, aggravation, alliteration,
   application*; `it` answers *lit, shit, spit, wit, quit, writ, split*.
3. **Landing pairs before the first ask**, not only on repair: *anchored* pairs first, which keep a
   word the source already said and only choose what answers it — `serious/delirious` (three
   syllables), `talking/walking`, `lifted/gifted` — then the crystal's own ready-made couplets.
4. Membership is always the live `_crystal_vocab()`; the artifact supplies only sound, frequency and
   provenance, so changing crystals is safe and the scan remains the fallback.

**The prompt** (all inside the cacheable prefix, so zero cost per ask)
5. **"The style world does not replace the conversation's words; it furnishes what the conversation
   did not say."** Keep the source's nouns, names and numbers inside the bars — they are counted —
   and spend the crystal on the landings, the similes and the turn between bars.
6. **"The landing is where this station is heard."** Never `it, now, you, that, this, here, there,
   right, tonight, thing, time` or the station's furniture; prefer a landing carrying a syllable past
   its stress.
7. **Off the wall, inside the facts**: the style world may change *how* a thing is said, never *what*
   was said, and a flourish like "not one" or "never" is a denial the source did not make.
8. The fluid-acceptance block no longer forbids an unusual style word; it asks for one at the landing
   and keeps the two rules it was reaching for (no invented claim, no padding).

**The deep repertoire and the ten-second rule**
9. **The deep bank goes first.** The gap chain now spends the 400-bar gold bank before the 28-line
   continuity reserve, which becomes the emergency reserve its own docstring calls it.
10. **A gold bar may fill a gap under the floor**, on the floorless announce road a sting already
    uses. It is a clip that already exists; only the *written* liner still waits for the floor.
11. `GOLD_MAX` 400 → **2,000** (52 minutes → about four hours of finished rhymed air). Every accepted
    rendered bar is already harvested and its take already shielded from the media sweep; the cap was
    the only thing throwing them away.
12. The rests: `TALK_INCESSANT_QUIET_MOST` 12 → **8** (at twelve the first filler cannot land inside
    ten by arithmetic), the cover's own rest 4 → **3**, `SFX_GAP_REST` 9 → **6**,
    `GAP_STOCK_FIRST_AFTER` 40 → **12** (at forty it armed only after the rule had already been
    broken four times over). The 2-second watch tick, `GOLD_GAP_REST` and the one-hour continuity
    rest are unchanged.

**The calls**
13. **A phone call is never paged.** It waits for all of its audio and airs as one piece. The wait is
    paid off air, where the gap roads cover it; the alternative is paying it mid-conversation.
14. **A cut closing turn fails a call.** The caller's resolving turn and the host's sign-off are the
    two the listener needs to hear a call *end*; the sign-off is a host line, so the existing caller
    guard did not protect it.
15. **A start-of-round check may not abandon a round the listener is already hearing** — a slot that
    no longer fits or a repeat refusal now only refuses a round that has not begun.
16. **The station going off mid-round is not a completed round.** It used to fall through to
    "everything aired" and write a normal hang-up for a caller who never resolved.

## What is designed and not yet built

The **phone-call scenario engine** the operator asked for — adjustable scenarios, an RNG path map
over six beats, and randomly drawn conclusions that are verified to have aired — is specified in
full in `rhyme/calls/report.md` (the store shape, the endpoints, the beat weights, the lexical
conclusion check, the test plan) and is the next body of work. The material finding behind it: the
fallback call script is a fixed 11-turn skeleton with three draws — **512 possible calls, all with
identical connective tissue** — which is why `call_novelty` correctly refuses every new call once a
handful exist, which empties the caller shelf, which forces the live road, which is what paged the
calls. The truncation and the sameness are one fault.

## Measured effect

| | before | after |
|---|---|---|
| rhyme suggestions beginning a, b or c | 70% | 15% |
| a rhyme lookup | 442 ms | 0.01 ms |
| crystal rhyme families available | none | 6,863 (6,069 multisyllabic) |
| crystal-register bars passing the grader | 2 of 6 | 3 of 4 |
| the gap chain's first worded road | 28 lines | 400 bars (2,000 cap) |
| finished rhymed audio playable under the floor | none | 52 minutes |
| model asks added | | **zero** |

380 tests green. One pinned test changed with its reason recorded: `talk_quiet_limit` is 8.0, because
the operator's rule is ten seconds and twelve cannot meet it.

## What must not change

The anchor floor itself (accepted turns sit at a median recall of 0.75; the floor binds only on bars
that threw the source away — the fix is the prompt). The `/`-separated two-bar form. The #1081 cache
prefix: every per-line addition must land after the road line. Advisory stays advisory. `_RAP_END_EXCL`
stays at eleven words — the families show `it`, `that` and `you` are the crystal's *richest*, so make
those landings interesting rather than forbidding them. `rerun_check`'s exact leg and its 35% breaker.
The one-hour continuity rest. `dialogue_audio_ready`'s partial refusal — it is why a *shelf* call
never truncates. `_cut_caller`. The one-ask-per-call budget.

The four agents' full reports, with their scripts and verbatim examples, are in the session
scratchpad under `rhyme/{variety,dictionary,flow,calls}/report.md`.
