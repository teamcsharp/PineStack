# The deep scan: driving the cut lines toward zero, and stacking the dialogue

Five parallel scans of the live station on the evening of 2026-09-08, each measured on the real
rows: the rhyme cuts, the meaning cuts, the sources that reach the crystal, the lifecycle of a cut,
and the stack and continuity themselves. Read-only snapshots: 215 pending rows (199 tint, 8 call
contract, 8 segment brief), 600 machine-handled notes, the stores, and the station's own status
surfaces taken at 18:25 CST while it was paused and banking.

## What the queue was made of

| the 199 tint cuts | rows |
|---|---|
| a rhyme fault (63%) | 125, of which 81 rhyme only |
| a meaning fault | 116, of which 108 under the meaning grade |
| a verbatim speakbox passage the crystal was asked to rap | 45 (23%) |
| the round it belonged to no longer exists | 114 (57%) |
| the round was accepted without that line | 39 |
| the round already carries an accepted bar for that line | 19 |
| an older cut of a line that has a newer cut | 22 |
| struck out (12 asks, no bar) | 13 |
| made by the operator's own two recoveries in flight | 12 |

**Nothing drained the queue but the operator.** A pending cut left only by a later pass of the same
round, the boot-time re-grade, or a decision; the round airing, expiring, being replaced or struck
out cleared nothing.

## What the readers were getting wrong

- **The repair hint was lying two times in three.** Of the 1,884 words the stored hints offered as
  rhymes, 194 were perfect rhymes, 130 near, and **1,205 were not rhymes at all** ("rhymes with
  'heat' — basket, bed, bread"; "rhymes with 'real' — angel, belt, cell"). The suggestions were
  picked by the spelling reader, whose vowel classes merge *heat* and *bed* and whose digraph rules
  are unreachable code. Every one of those junk pairs also *passed* the grader, because it is the
  same reading — a false-pass generator inside the prompt.
- **Twelve percent of the refused bars rhymed to the ear**: a slant the dictionary would not prove
  identical (proof/move, down/found, lit/shift, stay/ways, next/test, loud/sound, breathe/perceive)
  or a landing hidden behind a vocative tag ("…against decay, **man**; …behind the play").
- **The meaning cuts were the contract's form checks**, not lost meaning: rhetorical negations
  ("not just structural", "nothing more", "isn't it,", "can't shake"), questions asked on the way to
  a statement, the station's own name counted as a missing name, and a caller's introduction the
  regex could not read ("Salem, I am calling from…", "Howlin' Wolf here").
- **Twenty rows landed the same word twice** and the hint said "'worse' and 'worse', which do not
  rhyme" instead of naming the repetition.

## What shipped

**The rhyme reader and its hint**
1. `crystal_rhyme.rhymes_with` and `near_tails`: the pronouncing dictionary decides what a rhyme
   is. `rhyme_options_for` offers perfect pairs first, near pairs second, and falls back to the
   spelling reader only for a landing the dictionary does not carry.
2. The **near reading** (`terminal_near_rhymes`, used by `rap_rhyme_evidence`): the same final
   stressed vowel with codas equal once voicing and manner fold, or differing by one inserted
   consonant that is not a liquid. Perfect pairs unchanged; two fragments of three words or fewer
   still need a full coda; *calm/harm* and *being/feeling* stay refused. Measured cost: five more
   of 229 plain prose turns read as rhymed.
3. `_rap_untag`: a vocative tag after the bar's last comma no longer hides the landing. The spoken
   line is untouched.
4. The hint names the model's **own** bar ends (split on " / ", a semicolon or a sentence end, not
   on every comma — 26 of 163 hints named a comma clause), and says "both bars land on the same
   word" when they do.

**The meaning contract** (all accept-more; `VERSION` stays 3)
5. Six more rhetorical frames: a negated clause closed by a positive tag, *nothing more/but/less*,
   a tag closed by a comma, the transcript answer tokens *no yes*, the negative rhetorical opener,
   *no matter how/where/who*; and the #1076 fillers now read on the source side too.
6. A negation the rewrite added within four words of the source's own negative prefix or suffix is
   that negation unpacked (*the endless cycle … goes unmet* → *demands that never end … won't lend*).
7. The rap spelling *nothin'*; *what on Earth*; the discourse tag kept as a question; a transcript
   swath with under two sentence ends per hundred words read as unpunctuated; three more pronominal
   *one* shapes and the counted pronoun group *the two of them*; twenty-four common sentence
   openers that only a loaded crystal used to excuse.

**The sources that reach the crystal**
8. `_tint_plain_passage`: a verbatim passage no bar-set can carry — 300 characters or more, a raw
   run-on, or a stub the harvest window cut mid-word — is **read plain**, not rapped. #838 says the
   operator's documents may not be reworded; the tint was the last door that did.
9. The two unbounded doors (the full swath and the seed put-back) now pass a raw passage through
   the same 240-character bound as the other three.
10. The harvest window opens on a sentence or a word, never inside one, and a stub whose first word
    the dictionary does not know is not fresh material — this is where "Mfortable.", "Sgard." (bound
    as a name) and "Ned me" were born.

**The queue drains itself**
11. A newer cut of a line supersedes the older, at the capture and in the sweep.
12. A bar that lands in the batched repass or on a resume supersedes that line's cut — two of the
    three accept paths never did.
13. A pending row whose round is gone (older than thirty minutes) leaves as a note that says so; a
    row whose round already carries an accepted bar for the line leaves as superseded.
14. The sweep runs every ten minutes, not once at boot, and yields the interpreter between rows.

**The stack and the air**
15. **The brief comes before the tint.** A round that never gets to the thing its entry is for is
    marked and replaced instead of being rapped: six recaps were written, rapped (25 minutes of the
    one deep lane) and recorded tonight, then held off brief.
16. **A rapped call can be ready.** A cut on a *host* line no longer kills a call (a cut caller
    answer still does — it orphans the host's question); and once a call has been rapped the three
    richness legs (grounded questions, the speakbox source entering, the topic in both mouths) are
    advisory. Six fully rapped calls with 66 accepted bars were being thrown away at activation.
17. The call contract reads a caller's introduction two words wide and past an apostrophe, counts a
    question answered when the co-host speaks between, greets within the first two host turns, and
    floors a three-voice call's caller share at 0.30 instead of 0.35.
18. While **paused**, banter banking is no longer gated to two stock rounds — the pause is for
    banking, and it was banking 261 seconds of air an hour.
19. `reflection_gather` runs off the event loop. It stalled the station 23 seconds once, and the
    host watchdog restarts the station at eight.

## Measured effect on the queue

Offline, over the real 199 tint rows, with no crystal vocabulary loaded (conservative):

| | rows |
|---|---|
| read plain (a passage no bar-set can carry) | 29 |
| pass today's grader | 34 |
| still refused | 136 (83 no rhyme, 53 meaning) |

The lifecycle roads clear another 155 rows (114 gone, 19 already rapped, 22 duplicates) with no
model call and no effect on the air. What remains is the model's own work: a couplet that lands no
rhyme after three asks, and a rewrite that dropped a fact.

## The bottleneck, in numbers

The air asks for about **44 ready rounds an hour**. The deep tint lane makes **8-12** (3.6-5.4
minutes of wall clock per round, one decode slot, the deep model on every line under the hold). The
recorder is **23% busy** and could voice 45; the writer scripts five rounds for every one the lane
can rap. Nothing downstream is short — the lane is the ceiling, and tonight it spent 174 deep
answers on the phone road for **zero** ready calls, 25 minutes on recaps that could not air, and
~220 refused fast-lane asks an hour on the newspaper.

Dials the operator can turn now, in order of what they return:

| dial | now | proposed | what it returns |
|---|---|---|---|
| the judgment's `prefer_road` / `drive_road` and the 2.0x caller and news factors | caller | off caller until the contract passes | +10-15 rounds/h of lane |
| `reuse_rest` (rest between airings of a kept round) | 3 h | 1 h (the code floor) | 59 rhymed recorded rounds carry ~65 min/h instead of ~22 |
| `paper_hourly` (the Gazette) | on | off while the stack is short | +2-4 rounds/h |
| `generation_turns` (System2) | 6 | 8-10 | ~15% more bars per lane-hour |

## What must not change

The hold and 100% coverage; the 96-hour keep and the retirement desk on every deletion road; the
never-silent chain (`sfx_fill_gap` in both watchdogs, the record kick, the 12-second talk watch);
`rerun_check` standing down past 35% blocked; the pause-honest clocks; one decode slot (two measured
0.96x); the phone contract's hard legs; identical landings refused; the fragment rule and the
long-line two-pair floor applying to near pairs too; a liquid is not a free insertion; and the
fact checks on long, fact-heavy sources — every name and number cut on a model-written turn was right.

One pinned test changed with its reason recorded: `test_rhyme_options_are_crystal_words_the_grader
_would_accept` now reads the grader's actual reading (the spelling proof **or** the dictionary), so
*late/weight* and *late/freight* count as the perfect rhymes they are.

## Where the reports are

`rej3/rhyme/report.md`, `rej3/meaning/report.md`, `rej3/sources/report.md`, `rej3/drain/report.md`,
`rej3/stack/report.md` in the session scratchpad, each with its scripts, its measured tables and its
verbatim examples.
