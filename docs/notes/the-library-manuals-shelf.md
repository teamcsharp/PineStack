---
name: the-library-manuals-shelf
description: "#1158 the Library — /samples/Manuals auto-assimilated; routes are /api/manuals (NOT /api/library, taken); only documentation may open the shelf"
metadata: 
  node_type: memory
  type: project
  originSessionId: 28b1e1d4-a704-46fe-bb4f-340d34fe0491
  modified: 2026-09-10T13:28:55.419Z
---

Built 2026-09-10 (#1158). Full write-up lives in `docs/Library.md` — read that
first. What is not obvious from the code:

- **Route namespace:** `/api/library` is the MUSIC library and `/api/shelf` is
  the DJ shelf. Both were already taken; the Library's doors are
  **`/api/manuals/*`** plus `GET /manuals/read/{slug}/{n}`. The engine module
  is still `library.py` — the names deliberately disagree.
- **The share needs no new mount.** compose binds the whole quickswap share
  read-only at `/samples`, so `//10.89.1.125/QuickSwap/Manuals` is just
  `/samples/Manuals` in-container. **The host mounts it READ-ONLY** — to drop a
  test document you must write from Windows (`//10.89.1.125/QuickSwap/Manuals`
  is writable from there), not over ssh.
- **PDF text: compare WORDS, not characters.** `pdftotext -layout` pads with
  spaces to hold page geometry, so its char count is ~2× pypdf's while the
  recovered vocabulary is identical (pypdf actually finds more unique words).
  I nearly added poppler to the container over that illusion. pypdf is in
  `requirements.txt`; the container has no poppler and does not need it.
- **Only documentation may open the shelf** (`is_reference`, setting
  `library_reference_folders`, default `["/samples/Manuals"]`). With the 321
  speakbox transcripts indexed, *no* similarity floor separates a real question
  from "write me a poem about rain" — every false positive came from a
  transcript, every true one from a manual. Do not "simplify" this away.
- **Reciprocal-rank fusion: one contribution per key PER LIST.** Summing every
  rank a key occupies scores documents on chunk count, not match quality —
  that is why the MPC Bible won every query before the fix.
- Vectors are per-document `.npy` + `.jsonl` shards, mmap'd, matrices cached
  separately from row text (LRU 150) — deliberately not one big json, see
  [pulse-library-and-firmware-down](pulse-library-and-firmware-down.md) for the 625 MB / 11.4 s GIL freeze.
- The ingest clock is started by `_startup_library` with `fire_and_forget`,
  **not** in `dj_start` — clocks registered there die with the show, and the
  shelf must keep reading while the radio is off.
- Not committed as of 2026-09-10: the wiring lives in `app.py`, which the
  parallel session is also editing — see
  [parallel-session-commitment-ledger](parallel-session-commitment-ledger.md).
