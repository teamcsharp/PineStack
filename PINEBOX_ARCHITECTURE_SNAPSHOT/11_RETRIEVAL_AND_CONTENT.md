# Retrieval and Content Injection

## Systems

| Source | Ingestion/chunking | Embedding/index | Retrieval/filtering | Prompt insertion/cache/refresh |
|---|---|---|---|---|
| General library | `library.scan/plan/ingest_one`; `library_extract.read_document`; paragraph/page chunks | Ollama embedding callback; per-document matrix/row shards plus vocabulary | hybrid `_vector_rows` + `_word_rows`; top-k, per-doc cap, named-doc/reference boosts | road helpers; in-memory shard cache; ingest clock/wake |
| Speakbox | files under configured Speakbox/minds roots; custom chunk ledger | `nomic-embed-text`; `speakbox_vectors.json` + metadata | `speakbox_search/quote`, mind/document filters, cooldowns, document lock | prepend/append/full-swath prompt paths; periodic reindex |
| Crystal minds | extracted/source documents registered as minds | same Speakbox vector path plus crystal material/stanza caches | active crystals only; contiguous stanzas and sampled material | tint prompt; held material window stabilizes prompt prefix |
| Segment prompt documents | `segment_prompts._chunk_from_document` | uses host document/chunk ledger, not a separate vector DB | name/kind matching, avoid lists, topic/caller/plot expansion | `segment_prompts.expand/govern`; memo/use ledger |
| News | feeds/search plus article extraction/cache | no persistent vector DB found | headline eligibility/freshness, story choice, dossier | news road prompt; covered/said ledgers prevent reuse |
| Track material | music metadata, lyrics, SearXNG research, notes cache | no dedicated vector DB | current track binding and cached notes/lyrics | track-talk prompts; lookahead cache |
| Callers | caller books, cases, stories, themes, topic cooker | JSON books | eligibility, RNG, repetition/contract rules | caller prompt and persona/voice binding |
| Response/gold/SFX speech | curated JSON/SQLite banks | fingerprints/metadata | category, repetition, cadence, random eligible choice | inserted into spoken output/assembly |
| Station lore/director | active prompt, director notes/beats, prompt book | JSON | kind/scope/occurrence filtering | deterministic prompt clauses |

## Library Details

- **OBSERVED:** `library.py:page_chunks` and `doc_chunks` build bounded text chunks from extracted pages.
- **OBSERVED:** `shard_write` persists vectors and row metadata per document; `vocab_write` supports lexical retrieval.
- **OBSERVED:** `search(query,k=6,per_doc=2,...)` merges vector and word candidates, enforcing document diversity.
- **OBSERVED:** PDF, EPUB, DOCX, text, HTML, and ZIP content are supported by `library_extract.py`.
- **OBSERVED:** Retrieval failures generally return no context rather than blocking air.

## Speakerbox Compatibility

The request uses **Speakerbox**; current PineBox terminology and code use **Speakbox**.

**OBSERVED:** Existing Speakbox already provides source ingestion, chunking, embeddings, semantic/lexical retrieval, document/mind selection, use/cooldown ledgers, source provenance, and prepend/append/full-swath injection dials.

**INFERRED:** This is highly compatible infrastructure for a proposed Speakerbox mechanism if that mechanism can consume text chunks plus source metadata and can honor current cooldown/document-lock semantics.

Potential conflicts: current injection decisions are distributed across `dj_banter`, `speakbox_quote`, crystal material, and segment prompt expansion; a second injector could duplicate source text or bypass source/repetition records. Exact insertion contracts and provenance requirements remain **UNKNOWN** until the System 3 design is available.

