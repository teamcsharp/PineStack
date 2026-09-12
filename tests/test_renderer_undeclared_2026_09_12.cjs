/* THE CHECK THAT WOULD HAVE CAUGHT THE EMPTY PRESENTATION VIEW.
 *
 * 2026-09-12, from a photograph of the tablet: the Presentation view drew
 * its player, its playlist and its script, and nothing else. The feed, the
 * running order, the gallery, the library and the wall were all blank, and
 * the view's own budget line read "0 asking (peak 0)" - it had never put a
 * single question to the station, on a station that was live and answering
 * all three of those routes with plenty of content.
 *
 * One name did that. paintFeed read `feedDrawn`, which was never declared
 * anywhere. In a "use strict" file that is a ReferenceError the instant the
 * line runs, and every pane on that view is painted by ONE subscriber, so
 * the four calls after it never ran - and the shared feed swallows a
 * subscriber's throw on purpose, so that "a bad pane never stops the beat".
 * The swallow sits upstream of everything it was hiding.
 *
 * No test could have caught it. The suite requires the modules that export
 * for CommonJS; the pane-painting code is browser-only and is never loaded
 * at all. So this is the check that needs no DOM: read every renderer file
 * and find identifiers that are READ but never declared.
 *
 * KNOWN is not an allowlist to grow. It is the list of reads that are known
 * and deliberate today, each with the reason. Anything else fails, which is
 * the whole point: the next `feedDrawn` fails here instead of quietly
 * emptying half a screen.
 */
const { test } = require("node:test");
const assert = require("node:assert/strict");
const path = require("path");

const { scan } = require("../tools/undeclared_reads.cjs");
const RENDERER = path.join(__dirname, "..", "desktop", "renderer");

/* file -> name -> why this one is not a fault */
const KNOWN = {
  "renderer.js": {
    /* Guarded at the call site by its own try/catch with the comment
     * "rail-only": the rail build defines setStatus, the panel build does
     * not, and the call is optional by design. */
    setStatus: "optional, guarded by try/catch at the call site",
    /* #984 wired the Now cell's click to a function nobody wrote. Clicking
     * "Now" throws today. What it owes, per index.html, is "the artist, the
     * album, a search, and a corner of the shelf put on for however long
     * you say" - a request desk, not a one-liner, so it is recorded here
     * rather than guessed at. Delete this entry when it is written. */
    nowCellOpen: "#984 never implemented - the Now cell's click still throws"
  }
};

test("no renderer file reads an identifier it never declares", () => {
  const { files, found } = scan(RENDERER);

  /* The check is worthless if it silently stops seeing the files. */
  assert.ok(files.length >= 30,
    "expected the renderer directory to hold its scripts, saw " + files.length);

  const unexpected = found.filter(
    (hit) => !(KNOWN[hit.file] && KNOWN[hit.file][hit.name]));

  assert.deepEqual(
    unexpected.map((hit) => hit.file + ":" + hit.line + " " + hit.name),
    [],
    "An identifier is read but never declared. In a strict file that is a\n"
    + "ReferenceError the moment the line runs, and if the caller swallows\n"
    + "exceptions it will be a silent one - every pane painted after it in\n"
    + "the same function stops. Declare it, or add it to KNOWN with the\n"
    + "reason it is deliberate.");
});

test("the known-outstanding list has not quietly grown", () => {
  const { found } = scan(RENDERER);
  const known = found
    .filter((hit) => KNOWN[hit.file] && KNOWN[hit.file][hit.name])
    .map((hit) => hit.file + " " + hit.name)
    .sort();
  assert.deepEqual(known, ["renderer.js nowCellOpen", "renderer.js setStatus"]);
});

/* The specific name, pinned by itself, so the regression has a headstone. */
test("presentation.js declares feedDrawn, the name that emptied five panes", () => {
  const { found } = scan(RENDERER);
  const still = found.filter(
    (hit) => hit.file === "presentation.js" || hit.file === "presentation-source.js");
  assert.deepEqual(still.map((hit) => hit.name), []);
});
