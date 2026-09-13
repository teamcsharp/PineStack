# PineStack

The Pine Box radio station: an AI-run broadcast that writes, voices, schedules and
airs its own programming, twenty-four hours a day, on a home network.

A pair of DJ personalities talk over records, take phone calls, read adverts and the
news, interview guests, and print a newspaper on the hour. Everything they say is
written by a language model, spoken by a cloning TTS engine, and placed in an hour by
a scheduler that has to keep the air full whether or not the writing room is keeping
up. The station runs on a Jetson-class box (the "Pine Box") with a desktop shell, a
browser panel, a public listener door, and a satellite speaker in the room.

This repository is the whole of it — `app.py` and its modules, the Electron desktop,
the tests, the vendored dictionaries — plus the written record of how it got here.

## Where to start

| If you want | Read |
|---|---|
| The story of the project, era by era | **[HISTORY.md](HISTORY.md)** |
| Every commit, dated, in order | [docs/commit-log.md](docs/commit-log.md) |
| The hard-won operating knowledge | [docs/notes/](docs/notes/) |
| How the pieces fit together today | [docs/README.md](docs/README.md) |
| How to rebuild it from nothing | [docs/recreation/](docs/recreation/) |

## How to read the commit titles

Commit subjects are written as sentences about the station, not as changelog entries.
`#1142 the bookkeeping was strangling the switchboard` is a real bug with a real
measurement behind it; the number is a request from the operator's inbox
(`data/pine_requests.md`, untracked — it is runtime data). A subject that reads like a
finding usually is one: it names the thing that was actually wrong, which is more
useful a month later than "fix scheduler race".

The same voice runs through [docs/notes/](docs/notes/). Those notes are the working
memory kept alongside the code for the life of the project — what was measured, what
turned out to be a lie, and which diagnostics cannot be trusted.

## Shape of the tree

```
app.py                  the station: loop, orchestrator, HTTP surface, playout
system2*.py             the writing engine (drafts, plans, media, runtime)
crystal_*.py            the "crystal" tint pass — the rhyme/voice transformation
rejection_*.py          the review queue: why a written line was refused
line_review*.py         grading and acceptance of written material
director.py             the running order and the hour sheet
station_flow.py         segment flow and the floor lock
newspaper_city.py       the Pine Box Gazette
desktop/                the Electron shell, renderer, launcher, firmware tools
frontend/               panel stylesheets
docs/                   design notes, audits, the recreation guide
tests/                  pytest suite
vendor/                 WordNet, CMUdict, three.js — vendored, not fetched at runtime
```

`data/` is deliberately untracked: it is runtime state (the music index alone is
15 MB), and it is where the station's live memory lives.

## Where this came from, and how to keep it current

The station is developed in a working repository on the house share, on a branch called
`master`. This repository's `main` is that history attached to the initial commit by a
single merge — nothing was rewritten, so every one of the 489 commits keeps its original
author, date and hash.

The history here is current as of `c1c0129` (2026-09-13). To push later work up from the
working repository, teach it about this one *once*, so the two branches share a tip:

```sh
git remote add pinestack https://github.com/teamcsharp/PineStack.git
git fetch pinestack main
git merge pinestack/main        # brings the initial commit and these docs into master
git push pinestack master:main  # fast-forward from here on
```

Do that while nothing else is committing to the working repository.
