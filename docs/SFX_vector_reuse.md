# SFX vector reuse — the SFX Guy's section, and how to use it from outside

The SFX Guy keeps a library of about 360,000 playable clips (mp4 and mp3)
and his own dialogue (recorded takes, quips). This document says where that
knowledge now lives as one **sectioned, isolated, portable database**, how
he maintains it, how another application connects to it and asks for
clips by words, mood, intent or situation, and how it is backed up,
quarantined, restored and re-pathed in another project.

Written 2026-09-27 for the operator's request: "sync and connect dialogue
and relevant mp4s by lexical, semantic, action, situation, emotional,
intent, theme / topic, metaphorical similarity, visual / style fit ...
accessed by outside applications for query and interconnection ...
sectioned, isolated, maintained and a direct path that can be preserved and
compressed for backup."

## 1. Where it lives

```
spark-agent/data/sfx_vectors/            THE SECTION (one directory, nothing else in it)
    sfx_vectors.sqlite3                  clips, vectors, facet tags, dialogue, full-text index
    facets.json                          the categorisation: anchors per facet (editable)
    manifest.json                        schema, embed model, dims, ROOTS, counts, timestamps
    keeper.json                          the keeper's progress through the station's ledgers
spark-agent/data/sfx_vectors_backups/    compressed tarballs, one per backup / quarantine / export
```

Code: `sfx_vectors.py` (the section; **no station imports**; runs on its
own), `sfx_vectors_runtime.py` (the station wiring: keeper + HTTP doors),
`tools/sfx_vectors_patch.py` (the one guarded install line in `app.py`),
`tests/test_sfx_vectors.py`.

The section never touches the clips themselves. It holds **paths**, not
media. Every path is stored as a *root name* plus a *relative path*:

| root | on this station (the container) | what |
|---|---|---|
| `samples` | `/samples` | the clip share (`\\10.89.1.125\QuickSwap`, read-only) |
| `made` | `/app/data/sfx` | clips the station made itself (Workshop, glue, edits) |
| `comfy` | `/comfy-output` | ComfyUI renders |
| `voice` | `/app/data/voice_media` | rendered dialogue takes (his speech bank audio) |
| `app` | `/app` | anything else under the station |

Restoring the section somewhere else is a matter of naming the roots again
(section 6). Nothing inside the rows changes.

## 2. What is in it

**clips** — one row per playable clip of the station's clip book
(`data/sfx_clips.db`): `sid` (the station's 16-hex clip id), `root`,
`rel_path`, `name` (the wordy file name), `folder`, `video`, `seconds`,
`said` (the transcript the background renamer / indexer produced),
`seen_desc` (thumbnail tags from the vision model), `aired` (how often he
played it) and `last_aired`.

**clip_vec** — the clip's vector: `name | said | seen_desc | folder`
embedded with `nomic-embed-text` (768 dims, unit length, float32) on the
station's own Ollama. Coverage grows in the background (section 4); the
manifest's `counts` say how far it has got.

**facet_tags** — `(sid, facet, tag, weight)`: the categorisation.

**anchor_vec** — every anchor's vector (section 3).

**dialogue** — his lines: `take` rows from the speech bank
(`data/sfxguy_speech.json`: the text, who, the voice, and the audio file it
was recorded to, under the `voice` root) and `quip` rows from the quip
shelves (`data/sfxguy_quips/<voice>.json`). Each can point at a clip
(`clip_sid`) when it was a reaction to one. **dialogue_vec** holds their
vectors. **clips_fts** / **dialogue_fts** are SQLite FTS5 indexes (porter
stemming) for lexical search.

## 3. The facets, and how each one is reached

| facet | how a clip gets it | how a query uses it |
|---|---|---|
| **lexical** | the words of the file name, the transcript and the thumbnail tags, in an FTS5 index (porter stems) | the query's words, bm25-ranked, normalised to 0..1 |
| **semantic** | the clip's vector | the query text is embedded; cosine (a dot product of unit vectors) |
| **action** | anchors | |
| **situation** | anchors | |
| **emotional** | anchors | |
| **intent** | anchors | |
| **theme / topic** | anchors | |
| **metaphorical similarity** | anchors | |
| **visual / style fit** | anchors (plus the thumbnail tags in the lexical index) | |

**Anchors** are the categorisation itself. `facets.json` holds, per facet,
a list of `[tag, description]`, e.g. under `intent`:
`["warn", "warning someone, telling them to stop before it is too late"]`.
Each description is embedded once. A clip is tagged with the anchors its
own vector sits closest to: per facet the top 3 above a cosine floor of
0.42 (`sfx_vectors.FLOOR`), the cosine kept as the tag's `weight`. The
same anchors read a **query**: "something furious and threatening" lands
on `emotional:anger` and `intent:threaten`, and those tags then boost the
clips that carry them.

This is honest about what it is: the facets are **anchor similarity in
the embedding space**, not a model reading each clip. It is what makes
tagging 360,000 clips feasible (pure arithmetic, no model call per clip),
it is fully reproducible from `facets.json`, and it can be widened or
renamed by anyone: edit the anchors (section 5) and every clip is tagged
again by the keeper. A future pass that asks a language model to tag the
clips he actually airs can write the same `facet_tags` rows with
`how = "model"`; the query does not care where a tag came from.

The default anchor set (about 130 tags over seven facets) is in
`sfx_vectors.DEFAULT_FACETS` and written to `facets.json` the first time
the section opens.

## 4. How the SFX Guy maintains it (the keeper)

`sfx_vectors_runtime.py` runs one keeper task, every 30 s, on its own
worker thread (never the event loop — the station's standing rule):

1. **scan** — new and changed rows of the clip book (`sfx_clips.db`:
   new files, new transcripts, new thumbnail tags) are copied into the
   section. A changed transcript drops the clip's vector and tags so they
   are made again.
2. **air** — `data/sfx_history.jsonl` is read from where it left off; each
   play bumps `aired` and `last_aired`.
3. **speak** — every ten minutes the speech bank and the quip shelves are
   synced into `dialogue`.
4. **embed** — anchors first, then clips (the ones he has aired first,
   then the wordy ones — a transcript or thumbnail tags — then the rest),
   then dialogue; 48 texts per Ollama request, at most four requests a
   tick, and **only while the writing desk is idle** (`_OLLAMA_GATE`
   unlocked). He never takes the model from a round being written. On a
   busy station coverage therefore grows slowly; the status counts it.
5. **tag** — embedded, untagged clips are tagged against the anchors
   (up to 3,000 a tick; arithmetic only).

`GET /api/sfx/vectors/status` shows the counts, the backlog
(`clips - clips_embedded`), the last tick, failures (with the last one
named) and whether the desk is busy right now.

## 5. Connecting from outside

All doors are on the station (`http://10.89.1.246:8096`). Reads take the
read key; writes take the admin key (`Authorization: Bearer <key>`, the
same `SPARK_AGENT_API_KEY` every other station door uses).

**Ask for clips.**

```
GET /api/sfx/vectors/query?q=<words>&facets=<facet:tag,...>&video=yes|no|any&k=12&max_seconds=0
```

`q` is any words: a line just said, a mood ("gleeful and smug"), an intent
("a warning"), a situation ("in a car at night"), a theme. `facets` narrows
to clips carrying at least one of the asked tags (and boosts them),
`video` keeps only video or only audio, `max_seconds` caps the length.

The answer:

```json
{"query": "furious threat in a car",
 "query_tags": {"emotional": [["anger", 0.61]], "intent": [["threaten", 0.58]], "situation": [["car", 0.55]]},
 "embedded": true,
 "results": [
   {"sid": "60fc1b527bda5191", "score": 1.83,
    "why": {"semantic": 0.71, "lexical": 0.42, "facet": 1.14},
    "path": "/samples/samples_grabbed/10hrTIKtok/3248 you ever touch my car again.mp4",
    "root": "samples", "rel_path": "samples_grabbed/10hrTIKtok/3248 you ever touch my car again.mp4",
    "name": "3248 you ever touch my car again", "folder": "10hrTIKtok",
    "video": true, "seconds": 6.69, "aired": 3,
    "said": "you ever touch my car again and i swear",
    "facets": {"emotional": [["anger", 0.63], ["contempt", 0.47]], "intent": [["threaten", 0.60]],
               "situation": [["car", 0.52]], "theme": [["cars", 0.55]]}}],
 "considered": 88, "counts": {...}, "roots": {"samples": "/samples", ...}}
```

`why` says what made each clip win (the three parts are weighted 1.0 /
0.6 / 0.5 by default). `path` is the path **on this deployment**; an
application on another machine uses `root` + `rel_path` and its own map
of the roots (the same map the manifest carries). The file name is the
first thing the SFX Guy knows about a clip, so it is always returned.

**One clip, with everything he knows about it, and the lines he said over it:**

```
GET /api/sfx/vectors/clip/{sid}
```

**The categorisation:** `GET /api/sfx/vectors/facets`. **Change it:**
`PUT /api/sfx/vectors/facets/{facet}` with
`{"description": "...", "anchors": [["tag", "description"], ...]}` — the
changed anchors are embedded again and every clip is re-tagged by the
keeper (the count of tagged clips drops to zero and climbs back).

**The manifest:** `GET /api/sfx/vectors/manifest`.

**From Python, on the station's own roads:** `sfx_vectors_suggest(text,
k, video)` (lexical + facets, synchronous) and
`await sfx_vectors_suggest_async(text, k, video, facets)` (with the
semantic part) are in `app.py`'s namespace after install, for any road
that wants a recommendation. Neither is wired into the air path in this
first version: the SFX Guy's live matcher (`sfx_match_sting_pick`) is
unchanged, so nothing on air moved without a measurement first.

**Without the station at all** — from a backup in another project:

```sh
python sfx_vectors.py --root /where/it/was/restored query "a furious threat in a car" -k 10 --video yes
python sfx_vectors.py --root ... query "sad and slow" --facet emotional:sadness --facet visual:slow_motion
python sfx_vectors.py --root ... clip 60fc1b527bda5191
python sfx_vectors.py --root ... manifest
python sfx_vectors.py --root ... tag            # tag any un-tagged clips against the anchors
```

The CLI embeds queries with Ollama (`--ollama http://host:11434`, model
from the manifest). With `--fake-embed` it runs with a deterministic
stand-in (tests; a dry run with no Ollama — lexical and tag search still
work, the semantic part does not). Or open `sfx_vectors.sqlite3` with any
SQLite client: the tables above are plain, the vectors are float32 blobs.

## 6. Backup, quarantine, restore, re-path

**Back up (one compressed file):**

```
POST /api/sfx/vectors/backup   {"label": "backup" | "quarantine" | "export", "crystals": true}
→ {"file": "sfx_vectors-quarantine-20260927-121500.tar.gz", "bytes": ..., "crystals": 4}
GET  /api/sfx/vectors/backups                 the tarballs on hand
GET  /api/sfx/vectors/backup/{file}           download one
```

The tarball holds a consistent copy of the database (`VACUUM INTO`),
`facets.json`, `manifest.json` and — when `crystals` is true — the
**crystals**: one JSON per crystal exactly as the station's own
`/api/crystals/{id}/export` writes it (every speakerbox chunk, its vector,
its votes, the tint), under `crystals/<id>.json`. That is the dialogue
material his rounds are tinted with, carried with the clips it plays
against. A *quarantine* is the same file under a label nobody overwrites:
the keeper never reads or writes a backup, and a backup never changes.

Or from the shell on the host:

```sh
python3 sfx_vectors.py --root data/sfx_vectors backup /somewhere/safe --label quarantine
```

**Restore somewhere else, with paths that resolve there:**

```sh
python3 sfx_vectors.py restore sfx_vectors-quarantine-20260927-121500.tar.gz \
    --into /new/project/sfx_vectors \
    --root-map samples=/mnt/quickswap --root-map made=/new/project/made --root-map voice=/new/project/voice
```

Everything comes back — clips, vectors, tags, dialogue, the connections
between them, the crystals — and `path` in every answer resolves against
the new roots. A restore refuses a non-empty directory; on the station
`POST /api/sfx/vectors/restore {"file": ..., "into": "restored-x", "roots": {...}}`
unpacks *beside* the live section for inspection, never over it — swapping
directories is the operator's own step, on purpose.

## 7. Limits, stated plainly

- **The embedder is part of the data.** Every vector (clips, dialogue,
  anchors, the crystals' chunks) is `nomic-embed-text`; the manifest says
  so. A query embedded with another model is not comparable. Another
  project needs the same model (Ollama pulls it) or must re-embed.
- **Coverage is not instant.** 360,000 clips at 48 a request, only while
  the desk is idle: the semantic and facet parts cover what has been
  embedded so far (aired and wordy clips first); the lexical part covers
  everything from the first scan. The status and the manifest's `counts`
  say where it stands.
- **Facets are anchor similarity**, reproducible and editable, not a
  model's reading of each clip (section 3).
- **The read-only share.** The `samples` root is a read-only mount; the
  section stores paths, never media, and a backup carries no clips.
- **The tablet and the desk are not in this.** Nothing here changes what
  airs; the SFX Guy's live matcher is untouched until a measured step wires
  `sfx_vectors_suggest_async` into it.

## 8. Verifying it is alive

```sh
curl -s -H "Authorization: Bearer $KEY" http://10.89.1.246:8096/api/sfx/vectors/status | python3 -m json.tool
curl -s -H "Authorization: Bearer $KEY" "http://10.89.1.246:8096/api/sfx/vectors/query?q=angry+cat&k=3"
```

`counts.clips` should equal the clip book's playable rows within a few
ticks of a restart; `clips_embedded` climbs while the desk is idle;
`metrics.failures` stays at 0 and `last_failure` names any that do not.
