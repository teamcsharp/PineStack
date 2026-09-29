# System Three exchange handoff — 2026-09-28

## Operator contract

Every spoken segment must run its configurable System Three segment graph and associated roulette tables. A complete exchange has at least three spoken turns by at least two speakers; later turns respond to preceding turns and carry their roll stamps. Fixed recordings, songs, finished ads, and station IDs stay intact as source material, followed by generated conversation. If the full exchange or its voice takes are not ready, wait for a prepared complete exchange.

## Root cause measured

The 7:52 PM "Sponsor's Copy" entry in `data/script_ledger.jsonl` (line 32475; `data/air_log.jsonl` line 35948) aired one line for 166.01 seconds. System Three SQLite conversation `343a3656ffd0489e` had planned seven `ad_spot` turns, but only one line was bound; `bind_line` assigned that opening to final turn `t06`. The graph and rolls existed. The single-line broadcast path never wrote, rendered, or aired the replies. Produced ads also bypassed that path.

## Changed in this workspace

- `system3_runtime.py`: bind the source to opening turn `t00`, expose `system3_line_chapter`, and commit a chapter only when its ordered plan has at least three turns and two speakers.
- `app.py`: for `dj_speak` line roads, write graph-following replies, preserve the source opener, pre-render all voice takes, and hold the opener if preparation fails. Air replies with the same `sid` under the same floor. Route stored produced ads through the same chapter preparation. Reject incomplete graph rounds in `speak_turns`.
- `tools/system3_turnchain_patch.py`: recognize the extended `_banter_beats` signature in its idempotence check.

## Next system: finish and verify

1. Audit every path that can publish a script or audio row without `dj_speak`, `speak_turns`, or `_air_produced_ad`: manager pages (`_s3_split_page`), music, SFX, station IDs, manual replies, and direct page-feed calls. Associate each fixed source item with a graph chapter and complete replies; do not rewrite source media.
2. Replace the current one-attempt hold in `_s3_prepare_line_chapter` with a durable pending/prepared shelf. The user's rule is to **wait**, so a failed write or render must be retried and must not silently drop the segment or move past it. Admission should reserve and deliver all turns atomically across box/page routes; a later transport failure must not leave a one-line broadcast.
3. Confirm graph mapping for each road and operator customization from the tables. Validate per-turn `system3.turn_id`, speaker, `sid`, and roll/intonation in the live ledger. A graph plan or stamp alone is not proof of aired conversation.
4. In particular, test `ad_spot` with a long fixed opener like the 166-second case, and test a short station ID, a produced ad, a normal `dj_speak` line, and a prepared `speak_turns` round. Require three or more aired rows, at least two speaker identities, linked `sid`, and completed planned turns. Check audio actually plays in order on PineTab, not just that script rows exist.
5. Review voice and segment time budgets. The current implementation pre-renders replies and may extend a 166-second item beyond its scheduled slot. Account for those replies when the scheduler places a segment.

## Deployment and evidence

`spark-agent` is bind mounted at `/app`; editing this share changes the container files, but Python code loads after `POST /api/service/restart` with body `{"name":"spark-agent"}`. The page at `/` embeds the local API key when autofill is enabled; keep it out of logs. Verify `/healthz`, then check new `data/script_ledger.jsonl` rows and `data/system3.sqlite3` against the full exchange contract. Do not count code edits or health checks as proof of a live three-turn exchange.
