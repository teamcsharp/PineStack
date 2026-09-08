# Distinct image stories — request #1061

The 11 AM edition repeated spoken gallery descriptions and identical closing
copy in its image classifieds. The renderer also recycled those already printed
classifieds as sidebar filler, and its exhausted filler pool could start again.

Each selected image now receives its own randomly sampled passage from enabled
Speakerbox documents in the current mind. Sampling reads local text directly,
including after the writing deadline, and retains the exact passage, file, mind
and content hash. One bounded writer visit combines each visible subject with
its own source into a fictional local situation. Unavailable, malformed,
ungrounded or repeated writer copy uses separate local fallbacks with distinct
events, locations, actions and consequences. Spoken image-presentation patter
is removed before either path. People and animals remain residents or living
neighbours; goods retain their sale or service role.

City and classified desks share the resulting stories and claim each once.
Their actual bodies and source receipts enter subsequent DJ discussion context.
Printed image classifieds are no longer copied into filler, exhausted filler is
not restarted, and browser fitting deduplicates filler across each whole page.
The layout preserves complete classified headings and omits invented repeated
contact/price labels from resident and animal stories. Render version 6 rebuilds
cached layout; it does not rewrite the text of archived editions.

Verification passed 22 newspaper Python tests and six newspaper UI checks. Tests
cover model-free distinct source sampling after the press deadline, bounded
writer waiting, invalid/repeated copy fallback, retained people/animal/goods
roles, exhausted filler, and actual classified detail/provenance in DJ context.

`tools/newspaper-city-fixture.py` rendered the real 11 AM edition's twelve image
descriptions with twelve exact Speakerbox source passages and the writer
deliberately unavailable. It produced twelve distinct stories and 42 unique
sentences without publishing or changing station state. A hidden Electron check
using `tools/newspaper-city-smoke.cjs` inspected three rendered sheets, distinct
image cards and no repeated page fillers. The fixture and visual evidence are
under `%TEMP%/pine-newspaper-1061` (`result.json`, `browser-result.json`,
`city-page.png`). This is fallback and layout evidence, not proof of a live
publication or of every generated sentence's editorial quality.

The actual 12 PM edition independently published before deployment was inspected
through the normal API. Its twelve image stories still had nine repeated
boilerplate sentence occurrences, presenter patter and no source receipts. This
baseline is saved in `data/paper_verification/1061/2026-09-06-12/result.json`.

The first live extra, `2026-09-06-12x1324`, published 24 stories in about 98
seconds. Inspection exposed additional defects: the old frontmatter codec
stringified nested source receipts, the prose writer instructions conflicted
with the requested JSON batch, and fallback labels could use stray source
adjectives or truncate the visible subject. These findings were corrected and
the edition retained as evidence. The corrected regression fixture uses those
same twelve image names, full original stored descriptions and exact source
passages. It has twelve sources and 42 distinct sentences; all eleven classified
image assets load across three sheets without duplicate cards or page filler.
Its data is in `data/paper_verification/1061/corrected-fixture`; the visual check
is under `%TEMP%/pine-newspaper-1061-corrected`.

Additional regressions cover source receipt round trips and legacy recovery,
the JSON-only batch contract, actual awkward source topics and subject labels,
plural grammar, and a tint rewrite trying to copy another image's sentence.
Rejected duplicate tint retains the original copy and receives no tint credit.
An independent review confirmed these fixes and reran all 22 newspaper tests.

Final live verification completed after the 6 September restart through the
normal print API. Extra `2026-09-06-13x1441` published 23 stories and 22 plates.
Its twelve image stories used twelve distinct images and twelve source files,
with 39 unique sentences, no repeated sentences and no presenter patter. All
twelve source hashes matched; nine passages matched the verifier's exact-text
check. Eleven stories used the seeded fallback while the writer was busy.
Evidence is in `data/paper_verification/1061/2026-09-06-13x1441`; request #1061
was archived through the normal resolver with that evidence. No fixture was
substituted for live output. If the selected mind has no usable documents,
future image subjects cannot honestly carry source provenance; writer phrasing
also remains variable.
