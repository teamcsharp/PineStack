---
name: pine-box-gazette
description: "#1019 the Gazette - hourly newspaper off the station's own log (hermes-paper-agent contract in-process); desks, check codes, editions on disk, 📰 window, chat commands, recap tie-in"
metadata: 
  node_type: memory
  type: project
  originSessionId: d9d26bfc-bb6b-4b90-8e3e-380675d32124
  modified: 2026-09-04T23:21:57.237Z
---

#1019 (2026-09-04) built **the Gazette**: a newspaper printed on the hour
off the station's own hour, the way `vaelkeep/hermes-paper-agent` builds
one, but in-process in `app.py` (block "#1019: THE PINE BOX GAZETTE",
just above the Comfy Doctor's `/api/comfy/doctor` routes).

- **Editions** live in `data/paper/editions/<id>/` — `articles/NN-slug.md`
  (YAML frontmatter + markdown), `edition.json`, `edition.html`. Hourly id
  is the hour COVERED (`2026-09-04-17` = the 5 PM hour, printed at 6:00:20);
  an extra carries the minute (`…-17x1805`). `PAPER_KEEP` = 336 editions.
  `data/paper/paper.json` is the owner's masthead (seeded once; the
  container owns the file — it cannot be deleted over the SMB share).
- **Desks in order**: data desks by code (`_desk_records` off
  `played.json`, `_desk_adverts` off `ad_airings`, `_desk_engineering` off
  `_HOURS[-1]` + `system_stats`, `_desk_weather` off Open-Meteo via
  `WEATHER_DEFAULT_LOCATION`/`ha_home_location`); prose desks through
  `paper_write` → `call_ollama` directly (NOT `ask_model`, which collapses
  newlines and eats the HEADLINE/DECK/PULL/BODY shape) with a templated
  fallback each; `_desk_lead` last, `priority: 1`. `_RADIO["chat"]` is the
  transcript source and is in-memory, so the catch-up edition after a
  deploy has "0 lines said" — the air/gallery/upstairs desks skip.
- **Check/fix**: `paper_check` implements the upstream codes; `paper_fix`
  by code; the press refuses on marks (`ok: false`, nothing written).
  `story_short` lint is left standing on purpose.
- **Doors**: `GET /api/paper` (shelf + console), `POST /api/paper/print`
  (`{"kind":"hourly"}` reprints the hour just gone), `GET
  /api/paper/<id>`, `/html`, `DELETE`. `paper_pulse()` rides `/api/dj`
  (memory only — the poll is 2 s). Panel: `paperOpen()` window, 📰
  `#paperBarBtn` beside `#cloudBarBtn`, `PINE_3JS` key `paper`.
- **Chat**: `parse_paper_command` → `print` / `read`, detected right after
  `broadcast_cmd` and branched BEFORE `tune_requested` (so "make a
  newspaper" is never a render). `paper_recap_clause()` is appended to
  `dj_recap_round`'s angle.

**Why:** the operator wanted a live, scrollable, stored newspaper feed of
every segment every hour, generated on the fly when prompted, wired into
the FM's own systems.

**How to apply:** new material for the paper goes in `paper_material`
(one gather) and a new desk function; keep data desks code-only. A
standalone harness (`paper_test.py` in the session scratchpad, stubs
every app.py global, writer off) was the fast way to exercise the whole
press without a deploy — recreate it from the module's globals if it is
gone. Live first press: 7 stories, clean, 22 s. See
[pine-inbox-workflow](pine-inbox-workflow.md), [spark-agent-environment](spark-agent-environment.md).
