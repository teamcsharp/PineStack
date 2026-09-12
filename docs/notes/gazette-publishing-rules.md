---
name: gazette-publishing-rules
description: "Gazette layout - the missing lang attribute, why hyphens:auto can never work here, the containment pass, and the probe that measures it"
metadata: 
  node_type: memory
  type: project
  originSessionId: f4b2638b-0dd8-4966-a3f9-1284a5d562a7
  modified: 2026-09-10T20:56:03.186Z
---

2026-09-10 (#1158). The Gazette's layout faults are measurable, so measure
them: **`scratchpad/paper-probe.cjs`** loads an edition in headless Edge
over CDP and reports every box clipping its own content, every box whose
ink leaves the sheet, and every word broken across two line boxes. A
second probe turns each wrap rule off in turn to say whether a break was
a hyphenation or a guillotine. Baseline was 4 clipped boxes (worst 53px of
body copy cut mid-sentence), 1 escape, 5 guillotined words; both styles
now read 0/0/0.

**`hyphens:auto` cannot work in this paper and never could.** Two reasons,
either fatal: the document had no `lang` (Chromium picks its dictionary
from it), and the renderers this paper is actually read in — headless for
the gallery shot, an Electron webview in the desktop app, print-to-PDF —
**ship no hyphenation dictionaries at all**. So the publishing rule here is
not "hyphenate better": display type never breaks, and a word too wide for
its column needs a WIDER COLUMN (`table-layout:auto`, not `fixed`), not a
smaller word. `overflow-wrap:anywhere` is right for a debug panel and
wrong for a newspaper.

**The fitter measured flows and not the boxes holding them.** `_PAPER_FIT_JS`
trimmed `.flow` honestly and never looked at `.pgbody` or the `.front`
grid, both `overflow:hidden`, so a short estimate silently guillotined
copy. The containment pass now asks every clipping box: trailing adverts
out, type squeezed 4%, then the box reduced to 84% at worst. **`.front` is a
GRID and `.page` is a FLEX COLUMN** — wrapping their children in one div to
zoom it destroys both (measured: 53px over became 324px over). Boxes the
packer gave a height to take `zoom` + `height/zoom` on themselves; only
`.pgbody`, whose height comes from the flex, takes the wrapper.

`PAPER_RENDER_VERSION` gates the on-disk render cache — **bump it or you are
testing the old HTML**, including the old fit JS and CSS.

Copy: `_paper_subedit()` is the single sub-editor's read (do NOT call it
`_paper_words` — that name is taken by a word counter, and shadowing it
returns an int into a join). A painting nobody named is "Untitled No. 64".
`_paper_sponsor()` takes the NAME of what was advertised rather than the
first N characters of how it was described.

The Image button collects the edition as a SQUARE contact plate under 1 MB
(`paperGridPlan` / `paperFitBytes`), saved and put on the clipboard — a
tall column of 12 sheets is 900x15,700 at 8-14 MB and nothing will show it.

See [pine-box-gazette](pine-box-gazette.md), [panel-ui-debugging](panel-ui-debugging.md).
