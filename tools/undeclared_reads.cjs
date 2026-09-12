/* FIND THE BUG THAT EMPTIED FIVE PANES.
 *
 * On 2026-09-12 the Presentation view showed the player, the playlist and
 * the script, and nothing else: the feed, the wall, the running order, the
 * gallery and the library were all blank, and the view's own budget line
 * read "0 asking (peak 0)" - it had never put a question to the station.
 *
 * The cause was one name. paintFeed read `feedDrawn`, which was never
 * declared. Inside a "use strict" file that is a ReferenceError the moment
 * the line runs; the five panes after it in the same subscriber never ran,
 * and the shared feed swallows a subscriber's exception on purpose so that
 * "a bad pane never stops the beat". One undeclared identifier, no error
 * anywhere, five empty panes.
 *
 * Nothing could have caught it: the suite requires the modules that export
 * for CommonJS, and the pane-painting code is browser-only, so it is never
 * loaded at all. This is the cheap check that does not need a DOM - read
 * every renderer file, and report any identifier that is READ but never
 * declared anywhere in that file.
 *
 * Deliberately crude, and it over-reports rather than miss the shape:
 * every hit is meant to be read by a person. tests/test_renderer_
 * undeclared_2026_09_12.cjs pins the list so a NEW one fails the suite.
 *
 *   node tools/undeclared_reads.cjs desktop/renderer
 */
"use strict";
const fs = require("fs");
const path = require("path");

const KEYWORDS = new Set(("break case catch class const continue debugger default delete do else " +
  "export extends finally for function if import in instanceof let new return super switch this " +
  "throw try typeof var void while with yield async await of static get set from as enum " +
  "true false null undefined arguments").split(" "));

const GLOBALS = new Set(("window document console globalThis self navigator location history screen " +
  "setTimeout clearTimeout setInterval clearInterval requestAnimationFrame cancelAnimationFrame " +
  "requestIdleCallback cancelIdleCallback queueMicrotask structuredClone reportError " +
  "fetch Headers Request Response AbortController AbortSignal FontFace " +
  "URL URLSearchParams Blob File FileReader FormData WebSocket XMLHttpRequest EventSource " +
  "localStorage sessionStorage indexedDB caches crypto performance Intl CSS DOMParser " +
  "Infinity NaN createImageBitmap ImageBitmap ImageData OffscreenCanvas " +
  "Math JSON Object Array String Number Boolean Date Map Set WeakMap WeakSet Promise Symbol " +
  "Proxy Reflect BigInt Error TypeError RangeError SyntaxError ReferenceError EvalError " +
  "RegExp Function parseInt parseFloat isNaN isFinite escape unescape " +
  "encodeURIComponent decodeURIComponent encodeURI decodeURI atob btoa " +
  "Image Audio Video Option Element HTMLElement HTMLCanvasElement Node NodeList Text Range " +
  "Event CustomEvent KeyboardEvent MouseEvent PointerEvent DragEvent WheelEvent MessageChannel " +
  "MutationObserver IntersectionObserver ResizeObserver PerformanceObserver getComputedStyle " +
  "alert confirm prompt matchMedia devicePixelRatio scrollTo print close open speechSynthesis " +
  "TextEncoder TextDecoder ArrayBuffer DataView SharedArrayBuffer " +
  "Uint8Array Uint16Array Uint32Array Uint8ClampedArray Int8Array Int16Array Int32Array " +
  "Float32Array Float64Array BigInt64Array BigUint64Array " +
  "AudioContext webkitAudioContext MediaRecorder MediaSource Path2D " +
  "module require exports process Buffer __dirname __filename THREE").split(" "));

const ID_RE = "[A-Za-z_$][A-Za-z0-9_$]*";

/* Is the slash at i the start of a regex literal rather than a division? */
function regexHere(src, i) {
  let k = i - 1;
  while (k >= 0 && /\s/.test(src[k])) k--;
  if (k < 0) return true;
  const c = src[k];
  if ("(,=:[!&|?{};+-*%~^<>".indexOf(c) >= 0) return true;
  if (!/[A-Za-z_$0-9]/.test(c)) return true;
  const word = (src.slice(0, k + 1).match(/[A-Za-z_$][A-Za-z0-9_$]*$/) || [""])[0];
  return ["return", "typeof", "instanceof", "in", "of", "new", "delete", "void",
    "case", "do", "else", "yield", "await"].indexOf(word) >= 0;
}

/* Blank comments, strings, template literals and regex literals so their
 * contents are never read as code. Spaces keep offsets and line numbers. */
function scrub(src) {
  const out = src.split("");
  const blank = (from, to) => {
    for (let k = from; k < to && k < out.length; k++) if (out[k] !== "\n") out[k] = " ";
  };
  let i = 0;
  while (i < src.length) {
    const two = src.slice(i, i + 2);
    if (two === "/*") {
      const end = src.indexOf("*/", i + 2);
      const stop = end < 0 ? src.length : end + 2;
      blank(i, stop); i = stop; continue;
    }
    if (two === "//") {
      let end = src.indexOf("\n", i); if (end < 0) end = src.length;
      blank(i, end); i = end; continue;
    }
    const ch = src[i];
    if (ch === "/" && regexHere(src, i)) {
      let j = i + 1, inClass = false, ok = true;
      while (j < src.length) {
        const c = src[j];
        if (c === "\\") { j += 2; continue; }
        if (c === "\n") { ok = false; break; }
        if (c === "[") inClass = true;
        else if (c === "]") inClass = false;
        else if (c === "/" && !inClass) break;
        j += 1;
      }
      if (ok && j < src.length) {
        let k = j + 1;
        while (k < src.length && /[a-z]/.test(src[k])) k += 1;
        blank(i, k); i = k; continue;
      }
    }
    if (ch === '"' || ch === "'" || ch === "`") {
      let j = i + 1;
      while (j < src.length) {
        if (src[j] === "\\") { j += 2; continue; }
        if (src[j] === ch) break;
        j += 1;
      }
      blank(i, Math.min(j + 1, src.length));
      i = j + 1; continue;
    }
    i += 1;
  }
  return out.join("");
}

function declaredIn(code) {
  const names = new Set();
  const add = (chunk) => {
    const re = new RegExp(ID_RE, "g");
    let m;
    while ((m = re.exec(String(chunk)))) if (!KEYWORDS.has(m[0])) names.add(m[0]);
  };

  for (const m of code.matchAll(new RegExp("\\b(?:function\\s*\\*?|class)\\s+(" + ID_RE + ")", "g"))) names.add(m[1]);
  for (const m of code.matchAll(/\bcatch\s*\(([^)]*)\)/g)) add(m[1]);

  /* var/let/const: take the whole statement, split on TOP-LEVEL commas, and
   * keep the binding to the left of each `=`. A comma-naive pass loses B in
   * `var A = 'x', B = 'y'` - which is how this check first cried wolf. */
  for (const m of code.matchAll(/\b(?:var|let|const)\s+/g)) {
    let k = m.index + m[0].length, depth = 0, part = "";
    const parts = [];
    for (; k < code.length; k++) {
      const c = code[k];
      if ("([{".indexOf(c) >= 0) { depth++; part += c; continue; }
      if (")]}".indexOf(c) >= 0) { if (depth === 0) break; depth--; part += c; continue; }
      if (c === ";" && depth === 0) break;
      if (c === "," && depth === 0) { parts.push(part); part = ""; continue; }
      part += c;
    }
    parts.push(part);
    for (const one of parts) add(one.split("=")[0]);
  }

  /* every parameter list: arrows, functions, method shorthand */
  for (const m of code.matchAll(/\)\s*=>/g)) {
    let depth = 0, open = -1;
    for (let k = m.index; k >= 0; k--) {
      if (code[k] === ")") depth++;
      else if (code[k] === "(") { depth--; if (depth === 0) { open = k; break; } }
    }
    if (open >= 0) add(code.slice(open + 1, m.index).replace(/=[^,]*/g, ""));
  }
  for (const m of code.matchAll(new RegExp("\\bfunction\\s*\\*?\\s*(?:" + ID_RE + ")?\\s*\\(([^)]*)\\)", "g"))) add(m[1].replace(/=[^,]*/g, ""));
  for (const m of code.matchAll(new RegExp("(" + ID_RE + ")\\s*=>", "g"))) names.add(m[1]);
  for (const m of code.matchAll(new RegExp("(" + ID_RE + ")\\s*\\(([^)]*)\\)\\s*\\{", "g"))) add(m[2].replace(/=[^,]*/g, ""));
  return names;
}

function readsIn(code) {
  const hits = new Map();
  const re = new RegExp("(\\.\\s*)?\\b(" + ID_RE + ")\\b(\\s*:)?", "g");
  let m;
  while ((m = re.exec(code))) {
    if (m[1]) continue;                             /* a property access */
    if (m[3]) continue;                             /* object key / label / case */
    const after = code.slice(m.index + m[0].length);
    if (/^\s*\([^)]*\)\s*\{/.test(after)) continue;  /* method shorthand definition */
    const name = m[2];
    if (KEYWORDS.has(name)) continue;
    if (!hits.has(name)) hits.set(name, { count: 0, at: m.index });
    hits.get(name).count += 1;
  }
  return hits;
}

/* Every identifier ANY file in the page hangs off window/root/globalThis is
 * a real global for every other file loaded beside it. */
function scan(dir) {
  const files = fs.readdirSync(dir).filter((f) => f.endsWith(".js")).sort();
  const shared = new Set();
  const scrubbed = new Map();
  for (const f of files) {
    const code = scrub(fs.readFileSync(path.join(dir, f), "utf8"));
    scrubbed.set(f, code);
    for (const m of code.matchAll(new RegExp("\\b(?:root|window|globalThis|self)\\s*\\.\\s*(" + ID_RE + ")\\s*=", "g"))) shared.add(m[1]);
  }

  const found = [];
  for (const f of files) {
    const code = scrubbed.get(f);
    const declared = declaredIn(code);
    for (const [name, info] of readsIn(code)) {
      if (declared.has(name) || GLOBALS.has(name) || shared.has(name)) continue;
      found.push({ file: f, name, count: info.count, line: code.slice(0, info.at).split("\n").length });
    }
  }
  found.sort((a, b) => (a.file === b.file ? a.line - b.line : a.file < b.file ? -1 : 1));
  return { files, found };
}

module.exports = { scan, scrub, declaredIn, readsIn };

if (require.main === module) {
  const dir = process.argv[2] || path.join(__dirname, "..", "desktop", "renderer");
  const { files, found } = scan(dir);
  for (const hit of found) {
    console.log(hit.file + ":" + hit.line + "  " + hit.name
      + "  (read " + hit.count + "x, never declared)");
  }
  console.log("\n" + found.length + " undeclared read(s) across " + files.length + " files.");
  process.exitCode = found.length ? 1 : 0;
}
