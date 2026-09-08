# #1080 — what it takes for System2 to cover the hour

Request (2026-09-08): *"do an investigation into what it takes to have system 2 able to satiate
these requirements"* — the scheduler's "what the hour owes" panel showing manager 0 of 2, caller 0 of
4, news 0 s of 2880 s, gallery 5351/3240 (covered), ad 221/2160, banter 0/2160, track_talk 0/1080.

Every number below is either a live field read at 06:36 CST on 2026-09-08 (`[live]`, the bodies are
in the session's `live1080/` folder), a measurement from the earlier audits of this request family
(`[audit]`, `docs/inbox-1068-1069-1070-2026-09-08.md` sections 4c–4f), or an estimate (`[est]`) that
says what it rests on. Nothing marked `[est]` should be quoted as a measurement.

## 1. Demand — what the hour asks for

The obligations are six-hour totals (`prepare_hours` = 6), so an hour owes one sixth of each:

| road | owed / 6 h `[live]` | per hour | held `[live]` | last hour's attainment `[live]` |
|---|---|---|---|---|
| caller | 6120 s | 17.0 min | 0 s | 12 % |
| gallery | 3240 s | 9.0 min | 5439 s (covered) | 16 % |
| news | 2880 s | 8.0 min | 75 s | 22 % |
| ad | 2160 s | 6.0 min | 130 s | 49 % |
| banter | 2160 s | 6.0 min | 0 s | 39 % |
| manager | 1440 s | 4.0 min | 1931 s (covered) | 74 % |
| track_talk | 1080 s | 3.0 min | 0 s | 0 % |
| **total** | **19,080 s** | **53 min** | | hour score **25.0** |

`/api/coordinator/capacity` says the same thing from the other side: *"the running order asks for 50
min of written speech an hour; observed task latencies estimate about 454 min of room against 60
available. a phone call alone wants 320 min of it"* (`over: 7.58`) `[live]`. That estimate counts
queue waits, which several producers count at once, so it overstates the physical deficit — but the
direction is right.

**In lines and asks.** A finished round of eight turns airs for roughly 60–90 s `[audit]`. Under the
hold every turn must pass the grader, and the measured shape of a round's tint is: one whole-round
ask, one batched re-ask over the refused turns, then a per-line ask for what is still refused
(three asks per line under the hold). With 33 % of graded turns refused and 76 % of turns getting a
repair `[audit, 1076 §1]`, a round costs about 2 round-level asks + 5–6 line-level asks ≈ **8 deep
asks per ~70 s of air** `[est]`. 53 min/h of owed dialogue is then about **45 rounds/h ≈ 360 deep
asks/h** `[est]`, before the ads, memos, station IDs and gallery lines that ask one line at a time.

## 2. Supply — what the lanes can do

| stage | measured | asks/h it allows |
|---|---|---|
| deep tint (gemma4:31b), one runner slot `-np 1`, one app permit | ~17 s working, 35–60 s per ask with the queue `[audit, 1075 §2]` | 60–100 with queue, ~210 by working time alone |
| fast writer (gemma4:e2b) | ~2 s working, ~19 s queued `[audit]` | not the ceiling |
| recorder (XTTS, one preparation render per engine) | 30–80 s per round of ~70 s air `[audit, #1123 note]` | ~0.4–1.1 × real time |
| deferrals since the 10:44Z restart `[live]` | 31b tint 256, e2b station 180 in ~1 h 50 min | ~140 refused tint admissions an hour |

Demand over supply on the deep lane as it stood: **360 asks/h against 60–100 admitted** — a ratio of
**3.6–6 ×** `[est]`. That is the whole story of the panel: every road that needs the deep model is
short by about the same factor, and the two roads that were covered (gallery, manager) were living on
stock made before the hold.

Where each road's bottleneck sits `[live + audit]`: caller, banter and track_talk — the deep tint lane
(caller also carries the highest per-entry cost, 368 s); ad — the same lane, one line at a time; news
— not the lane: it has "arrived bare 3604 times" with a miss streak of 26 while holding 75 s; its
inputs (the wire, the prep life) run dry before the tint is asked. That needs its own look and is not
solved by throughput.

## 3. Levers, ranked by seconds of air gained per hour

| # | lever | expected effect | cost / risk | status |
|---|---|---|---|---|
| 1 | **One cacheable prompt prefix** (#1081): rules → world → passages first, the passage sample held for 20 min, road and line after | the runner reuses the KV cache for the shared prefix; a 16 KB prompt is ~4k tokens and the deep model's prompt processing is a large share of its ~17 s working time — **−30 to −45 % per ask** `[est]`, measurable in `model_calls.jsonl` as `prompt_eval_ms` against `eval_ms` | none in quality; the same five passages for 20 minutes | deployed |
| 2 | **Two decode slots on the host** (`OLLAMA_NUM_PARALLEL=2`) with `OLLAMA_LANES=2` in the app | decode is memory-bandwidth bound, so two sequences per weight read — **×1.5–1.8 lane throughput** `[est, batched-decode literature]`; runners confirmed `-np 2` at 12:00Z | KV memory doubles per model (2 × 32k context); a single ask gets a little slower | deployed |
| 3 | **Strike cap + fault memo** (#1082): a line struck out after 12 answers; the first ask carries earlier faults | six lines were 30 % of all tint events `[audit]`; **−20 to −30 % of asks** stop being wasted `[est]` | a line that will not rap is cut or its call retired | deployed |
| 4 | **Third tint permit for due System2 work** (a slot starting within 20 min) | no throughput; ordering — the hour's own segment is not queued behind a memo for tomorrow | one more concurrent ask when the schedule is short | deployed |
| 5 | **Single-line roads on the fast model's tint lane** (ads, memos, IDs, gallery lines), as the Gazette already does | the fast lane is idle-ish; its bars pass less often (16/78 first pass on the paper `[audit 4c]`) but at ~5 × the rate — net more bars per hour for those roads `[est]` | weaker rhymes on those roads; a settings change per road | next, if the deep lane still queues after 1–3 |
| 6 | **Legacy keepers off** (`legacy_keepers: false`) | the keepers and System2 both write into the same lane; the deferral counts show both — **−20 to −40 % contention** `[est]` | less stock while System2 alone fills; do it once System2's hours read "covered" two hours running | your call |
| 7 | **Shorter caller scenes** (`generation_turns` 6 → 4) | the caller road owes 17 min/h at 368 s of build per entry; two fewer turns is a third fewer asks per call | shorter calls | your call |
| 8 | **Coverage target below 100 on ads/gallery** | refused lines air plain instead of being cut/retried | plain lines on air, against the hold's rule | not recommended |
| 9 | **A second box for the deep model** | linear | hardware | the only lever past ~2 × |

## 4. The plan

1. Done tonight: 1, 2, 3, 4. Together they are worth roughly **×2.5–3.5 on the deep lane** `[est]`,
   which is the size of the gap in §2. After them the recorder (one XTTS render at a time, ~0.4–1.1 ×
   real time) becomes the next ceiling; at 53 min/h of owed air it runs near full.
2. Measure for two hours before touching anything else: `prompt_eval_ms` vs `eval_ms` per call in
   `data/model_calls.jsonl`; `/api/tint` → `coverage.refused` share and `fault_memo.repeat_lines`;
   `/api/orchestrator/logic` → `pipeline.writers.deferred_by_category` and `hour.score`;
   `/api/system2/status` → slots ready vs debt.
3. If the deep lane still shows deferrals above ~40/h: lever 5 (single-line roads to the fast lane),
   then lever 6 (keepers off).
4. Caller scenes to four turns (lever 7) if caller is still the road furthest behind.
5. News is a supply-of-input problem, not a lane problem; it needs the wire probe (#1156) read
   against the prep life, separately.

**What stays structurally out of reach on this box:** all seven roads covered *and* the hold at 100 %
*and* the deep model on every line *and* the legacy keepers writing beside System2. The deep lane's
ceiling after tonight is about one hour of tinted air per hour of wall clock with nothing to spare;
any two of those four can be had, not all four. The honest choice is which one gives: the fast model
on single-line roads (weaker rhyme on ads and memos) is the cheapest.

## 5. What System2 itself must do differently

- **Two preparations at once when there are two lanes.** `system2_runtime.py` `prepare()` (line
  ~466) holds one `_prepare_lock` and returns while it is held; with `OLLAMA_LANES` = 2 a second
  preparation on a *different road* could run beside it. Today the second lane is filled by the
  legacy keepers, which is the wrong producer to give it to.
- **Due-first claim order is already right**: `system2.py` `claim_job` (line ~532) orders by
  deadline; the third permit (lever 4) makes the lane agree with it.
- **Job sizing**: a caller job is one scene of `generation_turns` (6) turns ≈ 8 deep asks; with the
  lease renewed every five minutes (`renew()`, ~line 495) a long scene no longer loses its result,
  but a 4-turn scene would land twice as often on a short lane (lever 7).
- **Candidate binding**: expired candidates are marked and refused (#1074); a struck-out line's row
  is no longer viable (#1082), so the planner writes its replacement instead of waiting on it.
