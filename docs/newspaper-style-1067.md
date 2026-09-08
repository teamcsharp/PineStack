# Newspaper reference style — request 1067

The supplied reference (`data/pine_uploads/1788757319-f59a91f6.png`) uses tall
cream sheets, a blackletter masthead, narrow ruled columns, small red accents
and a prominent photograph with its headline in white. The ordinary broadsheet
now follows that layout, with a 1100 × 1705 portrait page, five inside columns,
the lead photograph beside a narrow text column, and the edition index/statistics
in the outer column. The complete station name remains above the display word
“Gazette”; custom mastheads are preserved. Tabloid remains a separate view.

Article bodies, headlines, source metadata and images are shared between the
two styles. This change does not rewrite archived articles or replace their
image captions. Long articles continue at paragraph boundaries. Render version
7 refreshes previously cached HTML on normal reads. Narrow windows now center
the painted page after scaling, fixing an off-screen origin in the old fitter.

The bundled UnifrakturMaguntia face is embedded in the HTML so clipboard
captures and offline previews do not depend on an installed font or a public
font server. The unchanged font and SIL OFL 1.1 licence are stored in
`frontend/fonts/`, sourced from the [official Google Fonts directory](https://github.com/google/fonts/tree/main/ofl/unifrakturmaguntia).
Both assets are included by the existing desktop `frontend` resource rule.

Verification before deployment: 26 newspaper Python tests and six newspaper UI
checks passed. Tests include preservation of every paragraph in a long lead,
one copy of its image, unchanged input data, escaped/custom station mastheads,
font-file fallback, and the separate tabloid/text-only lead paths. The existing
23-article edition `2026-09-07-03` was rendered without station writes. Hidden
Electron/Chromium inspection measured eight ordinary pages, thirteen tabloid
pages, all 23 images loaded in each style, no overflowing text flows, and a
438-pixel headline/caption overlay fitting its 835-pixel photo panel. The
ordinary page remained inside a 390-pixel window. Front/inside/narrow captures
are in `%TEMP%/pine-newspaper-1067`; source render files are under
`data/paper_verification/1067`.

The API keeps its existing schema: `/api/paper/{id}` supplies shared article
data, `/api/paper/{id}/html?style=broadsheet|tabloid` supplies the typeset preview,
and `/api/paper/slideshow?style=both` presents both. There is no crop endpoint.
Normal image-copy captures all rendered sheets, including their bundled font.

The native PDF now uses a 220 × 341 mm portrait broadsheet with five columns,
cream pages and the embedded blackletter masthead; tabloid stays A4 portrait.
It uses its own text flow and retains the headline beside the photograph, so
its page composition is not pixel-identical to the HTML. Some native inside
pages retain unused columns from the existing article grouping. Three further
PDF tests verify actual output, complete paragraph markers, one copy of each
article/image, captions, page bounds, embedded/custom mastheads and fallback.
The final targeted total is **29 Python tests and six UI checks**, all passing.

Deployment completed on 7 September after two observed quiet samples, with no
current speech or remaining stream time. Health returned 200. Authenticated
normal preview/PDF reads of `2026-09-07-04` then verified HTML render version 7
and refreshed PDF version 2. All 23 article records remained byte-equivalent
as JSON data before and after rendering; no new edition was requested.

The actual live HTML rendered seven ordinary sheets and twelve tabloid sheets.
Both loaded all 23 images with no overflowing text flows. The ordinary feature
overlay measured 456 pixels inside its 835-pixel image panel, and its scaled
page stayed inside a 390-pixel viewport. Both actual downloaded PDFs had the
same respective page counts and no text blocks outside their page bounds;
the ordinary PDF contained the embedded Unifraktur font. Live API artifacts
and hashes are under `data/paper_verification/1067/live`; browser and PDF
measurements are in [browser evidence](newspaper-style-1067-browser.json) and
[PDF evidence](newspaper-style-1067-pdf.json). The actual [front page](newspaper-style-1067-front.png)
and [inside page](newspaper-style-1067-inside.png) were visually inspected.

Request #1067 was completed through the normal inbox resolver with this evidence.
The existing #1061 archive and its earlier publication remain untouched.

Final integration verification passed **344 Python tests in 34.243 seconds**
using a fresh isolated data directory, after correcting unrelated tint-test
isolation. Six newspaper UI checks and the changed-file whitespace check also
passed. The resolver's final read reported an empty inbox.
