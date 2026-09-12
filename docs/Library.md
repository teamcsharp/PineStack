# The Library — the operator's own documents, read and remembered

Pine Box FM, built 2026-09-10 (#1158). A document dropped into a watched folder is read, cut into
overlapping chunks, embedded through the local embedder and answerable in ordinary conversation a
minute later. Nothing is clicked and nothing is restarted.

Every number in this document was measured on the real shelf at `//10.89.1.125/QuickSwap/Manuals`
while it was built. Where a decision went one way rather than another, the measurement that decided
it is written down beside it.

---

## 1. The shape of it

```
  //10.89.1.125/QuickSwap/Manuals          (already mounted read-only at /samples/Manuals)
  /app/data/speakbox                       (the DJs' transcripts, bound in compose)
            │
            │  library.ingest_clock — every 120s, and NOT tied to the show
            ▼
  library_extract.read_document ──▶ pages  {n, heading, text, blocks, source_url}
            │                              (the same shape the gear corpus uses, so the
            │                               rankers and the viewer work unchanged)
            ├──▶ data/library/<slug>/doc.json          the pages
            ├──▶ data/library/<slug>/pages/*.html      EPUB chapters, sanitised, for reading
            ├──▶ data/library/<slug>/vocab.json        every distinct word in it
            └──▶ library.doc_chunks ──▶ _embed_texts ──▶ data/library/vec/<slug>.npy + .jsonl
                                        (nomic-embed-text, the DJs' own embedder)
            ▼
  library.search   vectors (meaning) + _te_page_score (letters), fused
            ▼
  generate_answer  one system message, cited by document and page
            ▼
  /v1/chat/completions · /api/test · the 📚 console · /manuals/read/<slug>/<n>
```

The engine is **`library.py`**; it imports nothing from `app.py` and is handed the embedder, the
page ranker and the data directory by `library_boot()`. The readers are **`library_extract.py`**:
pure stdlib apart from `pypdf`. `app.py` holds only wiring.

---

## 2. What it reads

`.pdf` `.epub` `.zip` `.docx` `.txt` `.md` `.rst` `.html`. `Thumbs.db`, dotfiles and anything over
400 MB are skipped.

**PDF** prefers poppler's `pdftotext -layout` and falls back to **pypdf**. The container has no
poppler (`python:3.12-slim`), the host does, and it does not matter: measured across all seven
manuals, poppler and pypdf recover the **same words**. The raw character counts differ by half only
because `-layout` pads with spaces to hold the page geometry — pypdf actually finds *more* unique
words, because it picks up diagram labels poppler drops. That measurement is why there is no apt
step in `compose.yaml`.

**EPUB** is read in spine order out of the OPF, with chapter titles from the epub3 nav or the epub2
ncx. Each chapter is also written out as sanitised markup for the reader pane — scripts, styles,
frames, event handlers and `javascript:` URLs do not survive — and its figures are extracted beside
it.

> The bug worth remembering: a 44-chapter book read as **one blank page**, because
> `<script src="js/book.js"/>` is self-closing. Routing a self-closing tag through
> `handle_starttag` raised the skip counter with nothing to lower it again, and every word after
> that tag in every chapter was dropped. Held by
> `test_epub_reads_every_chapter_past_a_self_closing_script`.

**ZIP** is a website bundle when it holds html, and otherwise a bag of documents, each read in turn.
A member already on the shelf under its own name is skipped by content hash — the OP-XY guidebook
zip on this shelf is exactly the two PDFs sitting loose beside it, and it is refused with
`every document inside (2) is already on the shelf` rather than indexed twice.

---

## 3. Chunking

`page_chunks` packs paragraphs, then sentences, then hard-cuts, to **900 characters with 150
characters of overlap**, never crossing a page boundary. The overlap is what keeps a fact that
straddles a boundary whole somewhere. Each chunk carries `{slug, page, heading}`, and the heading
rides along in the text that is *embedded* but not in the text that is *shown* — "press shift" under
"step components" should not read the same as the identical words under "mixer".

## 4. Where the memory lives

| Path | What |
|---|---|
| `data/library/index.json` | one row per document: state, size, mtime, sha, pages, chunks, note |
| `data/library/<slug>/doc.json` | the pages |
| `data/library/<slug>/pages/*.html`, `pages/img/` | EPUB chapters and figures |
| `data/library/<slug>/vocab.json` | every distinct word in the document |
| `data/library/vec/<slug>.npy` | float32, one unit row per chunk |
| `data/library/vec/<slug>.jsonl` | those rows' text and page, in order |

**Per document, and `.npy`, deliberately.** The DJs' one big `vectors.json` reached 625 MB and
parsing it for a chunk *count* froze the event loop 11.4 s (#1156) — the C json decoder holds the
GIL, so a thread does not help. `np.load(mmap_mode="r")` is instant, a deleted document is one file
removed, and a restart mid-ingest resumes at the last finished book.

Matrices and row text are cached **separately**: matrices are memory-mapped and cost almost nothing,
while the row text is held under an LRU of `SHARD_CACHE = 150` documents. Ranking touches every
document on the shelf, so it must not also parse every document's text to do it.

---

## 5. The background service

`library.ingest_clock`, started by `_startup_library` with `fire_and_forget` — **not** in `dj_start`
beside `speakbox_index_clock` and the rest. Those live and die with the show (`radio_stop` cancels
every task in `_RADIO_TASK`), and a document dropped in while the radio is off must still be read.
That is exactly when somebody is sitting here asking questions about it.

Each pass: scan the folders in a thread with `sfx_folders`-style guards → diff against the index by
`(path, size, mtime)` → forget what is gone → read what is new, one document at a time → sleep 120 s.
Every heavy step is on a thread; the host watchdog restarts the container past 24 s of blocked loop.

**Pacing.** The box runs one Ollama lane (`OLLAMA_LANES=1`). The shelf sleeps `EASY_SLEEP` between
embedding batches and `BUSY_SLEEP` while the radio is on and anything is queued or writing, so it
reads slower and the air does not gap for it. `POST /api/manuals/ingest {"now": true}` bursts.

Measured: the eight manuals — 1,862 pages, 5,225 chunks — were assimilated in **2.7 minutes**. A
newly dropped EPUB was on the shelf and answering questions **within 30 seconds**. A document
deleted from the share is forgotten at the next pass boundary (about two minutes when the shelf is
settled; longer during a bulk ingest, because a pass drains its queue before the next scan).

---

## 6. Recall, and what it refuses

`library.search` is hybrid: the vectors find the passage that **means** the right thing, the letters
(`_te_page_score`, borrowed from the gear corpus) find the passage that **says** "shift + step".
They are merged by reciprocal-rank fusion.

> Fusion bug worth remembering: one contribution per key **per list**, the best rank it reached —
> never one per row. Summing every rank a key occupied scored documents on how many *chunks* they
> had rather than how well they matched. A 44-chapter EPUB whose every chapter is one "page" folds
> twenty-five chunks into a single key and collected twenty-five contributions for them; measured,
> that put a transcript matching at cosine 0.39 **above** the manual matching the same question at
> 0.90, and it is why the MPC Bible won nearly every query before the fix.

**Three gates, in order.** Each exists because of a measured failure:

1. **`shelf_question`** — a question whose every word appears in every document is not a question
   the shelf can answer. "play some music" scored **0.63** against a book about music production and
   "what time is it" **0.55**, because a manual really is about music and really does discuss time.
   Similarity cannot separate those; specificity can.
2. **Only documentation may open the shelf** (`is_reference`, from `library_reference_folders`,
   default `["/samples/Manuals"]`). Once the 321 speakbox transcripts joined the eight manuals, no
   floor worked any more:

   | | cosine | word score |
   |---|---|---|
   | questions the shelf should answer | 0.63 – 0.76 | 4.3 – 9.8 |
   | questions it must leave alone | 0.53 – 0.65 | 0.0 – 2.0 |

   The cosines overlap. And "write me a poem about rain" (3.1) and "sing me a song about the sea"
   (4.4) beat "what are keygroup programs" (3.1) on *both* — because **every** false positive came
   from a transcript and **every** true one from a manual. A manual is written to be consulted; a
   transcript is a record of speech. So a transcript may *support* an answer and be searched
   directly, but it may never decide that an ordinary question was a documentation question.
3. **The floors** — `SEARCH_FLOOR 0.52` and `WORD_FLOOR 3.0` together, or `WORD_STRONG 8.0` with
   `WORD_COSINE 0.45` for an exact hit like "EP-133 fader".

Search runs in **two phases** for cost: phase one reads only documentation and decides whether the
shelf opens at all. Most questions are not for the shelf, and they stop there having touched eight
manuals instead of 330 documents. The rest of the shelf is read only once a real documentation
question has already opened it.

Measured after all of it: **14 of 14** — every documentation question answered, every general
question left alone, including "what is the capital of France", "write me a poem about rain",
"tell me a joke", "what should I make for dinner" and "how do I renew my passport".

## 7. Where an answer enters

One place: the gear-manual branch in `generate_answer`. The order is deliberate —

- the **gear manuals** first, so an OP-XY question answers exactly the way it always has;
- unless the question **names a document** on the shelf (`named_document`), which is the one case
  the Library outranks them. Measured: "what does the MPC Bible say about chopping a sample into a
  drum kit" was answered out of the gear corpus, because "MPC" is a device alias there, so the book
  the operator asked for by name never got a look. Two distinctive words of a title must line up, so
  "chop it on the MPC" is still the gear manuals' question;
- then the **Library**, and the Library also catches a gear device whose manual is not cached;
- then the **web**, because the box should read its own documents before it reaches outside.

`feature_meta["library_used"]` and `library_docs` ride back on every answer, so the panel can print
which document and page were used and whether the meaning or the letters found it.

## 8. The doors

| Route | What |
|---|---|
| `GET /api/manuals` | the shelf and what the assimilator is doing this second |
| `GET /api/manuals/doc/{slug}` | one document's pages (headings and lengths) |
| `GET /api/manuals/page/{slug}/{n}` | one page: chapter markup, or text |
| `GET /api/manuals/file/{slug}` | the original, streamed |
| `GET /api/manuals/asset/{slug}/{name}` | a figure lifted out of an EPUB |
| `POST /api/manuals/search` | the console's search box (ungated) |
| `POST /api/manuals/ask` | ask about the open document |
| `POST /api/manuals/ingest` | come round now / re-read one / forget one |
| `GET /manuals/read/{slug}/{n}` | one chapter, full width, on its own URL |

**No page was ever rasterised.** A PDF is shown by the browser's own viewer in an iframe, and
`#page=N` takes it to the page an answer cited; the gear corpus spent 609 MB on page PNGs. EPUB
chapters get `/manuals/read/...` instead, because a raw `.epub` only downloads.

Auth follows the gear manuals' precedent next door: the JSON roads want a read key; the raw assets
and the source file do not, because an `<img>` and an `<iframe>` cannot set an Authorization header.
`library_source_path` checks every requested file against the watched folders, so a doctored index
cannot turn an open route into a way to read any file on the box.

## 9. The console

📚 in the tray and in the 3JS gallery. Left: every document with its state, pages, chunks, figures
and any note, documentation first. Top: a search box (ungated — somebody typing into the shelf's own
search means it) and **Read new files now**. Right: the reader, and **Ask about this document**,
which reads the section around the page rather than one orphan page.

## 10. Dials

| Setting | Default | What |
|---|---|---|
| `library` | `true` | the whole feature |
| `library_folders` | `["/samples/Manuals", "/app/data/speakbox"]` | what is watched |
| `library_reference_folders` | `["/samples/Manuals"]` | which of them may **open** the shelf |

Saving settings re-wires the engine and wakes the clock; no restart. In `library.py`:
`CHUNK_CHARS 900`, `CHUNK_OVERLAP 150`, `EMBED_BATCH 32`, `VEC_MAX 300000`, `PER_DOC_CHUNKS 6000`,
`IDLE_SECONDS 120`, `SHARD_CACHE 150`, `WORD_DOCS 12`, `REFERENCE_BONUS 0.5`.

## 11. Reading the state

`GET /api/manuals` for the shelf; the `vector guides` row of the services census now counts the
Library. That row used to say "N manuals chunked and cached" and count `te_devices()` — nothing in
the gear corpus has ever been chunked or embedded (`te_lookup` scores pages by substring), so the
census was reporting a vector index that did not exist.

## 12. What is not done

- The 321 speakbox transcripts are indexed and searchable but cannot open the shelf (§6.2). If you
  want them answering general questions, add their folder to `library_reference_folders` — and
  re-read §6 first.
- Search costs a few hundred milliseconds and rises with the shelf; it runs in a thread, so it
  never blocks the loop, but it is not free.
- A deleted document is noticed at a pass boundary, not immediately.
