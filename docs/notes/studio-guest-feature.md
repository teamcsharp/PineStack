---
name: studio-guest-feature
description: "Studio guest (#568/#1135) — guest rides the THIRD seat; \"guest\" schedule kind airs the interview, live-only, falls back to banter"
metadata: 
  node_type: memory
  type: project
  originSessionId: f40c3481-2fd4-4f66-bcbb-4da52e02f40a
  modified: 2026-08-25T13:17:26.925Z
---

The studio guest (#568) is seat-level plumbing: `set_guest()` writes
`guest_mode`/`guest_id` + `third_name`/`third_persona`/`third_voice`, so
while a guest is active the THIRD seat IS the guest and `dj_banter`
includes them in EVERY round (`hosts = ("dj","cohost") + ("third",) if
third_name`). Storage: `data/guests.json`. API: GET/POST/DELETE
`/api/dj/guests`, POST `/api/dj/guest/activate` `{on, id}`, POST
`/api/dj/guest/send-home` (plays the goodbye round, then clears the
seat), POST `/api/dj/callers/{id}/to-guest` (promote a caller).

#1135 (2026-08-25) added the schedule half: a `guest` kind in
`SCHEDULE_KINDS` ("Studio guest") so the hourly schedule can name an
interview segment. Wiring:
- Torrent chain branch (`elif kind == "guest"` beside manager/gallery):
  when `active_guest()`, runs `dj_banter(angle=<interview brief naming
  the guest>)`; empty chair → logged, plain banter covers (never dead
  air, never a missed hour).
- `CANNOT_PREPARE["guest"]` — live-only, like recap/deep: keeps
  hour_needs, the commitment desk, and the pantry from demanding banked
  stock in the wrong guest's voice. Already excluded from ballast swaps
  (road not preparable) and from SLOT_POSTPONE.
- `SCHEDULE_PROMPT_SEED["guest"]` seeds the prompt desk.

**How to apply:** the panel's schedule editor lists kinds from
`/api/schedule/kinds` (zero hardcoded kinds client-side), so new kinds
appear automatically. To verify a guest airs: seat one via activate,
add/enable a "Studio guest" entry in the active preset, watch the
pipeline log for the #1135 line. See [hour-contract-two-truths](hour-contract-two-truths.md),
[parallel-session-commitment-ledger](parallel-session-commitment-ledger.md).
