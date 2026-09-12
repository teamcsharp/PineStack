#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the Pine Box icon set from data/icons/pine-icons.json.

The station used to draw its icons with colour emoji. It now draws them with
one single-colour vector set: IBM Carbon Icons, with Material Symbols
Outlined filling the handful of gaps Carbon has no glyph for. Both are
Apache-2.0, so both are vendored - nothing here reaches the network, which
matters because the tablet lives on a LAN with no internet.

Two artefacts come out of the one mapping, because the application draws
icons in two different ways:

  frontend/pineicons.css      A web font whose cmap maps the ACTUAL emoji
                              codepoints onto the vector outlines, wrapped
                              in a self-contained @font-face (the woff2 is
                              a base64 data: URI, so there is no second
                              request and no MIME type to configure).

                              This is the workhorse. Most of the station's
                              icons are not markup: they are characters in
                              plain strings handed to el(), to <option>, to
                              textContent, and to records already written to
                              disk. A font reaches all of those without
                              rewriting a single one of them.

  frontend/pine-icons.js      An SVG sprite plus a pineIcon() helper, for
                              markup that wants a real <svg> it can size,
                              label and style - icon-only buttons above all,
                              which need an aria-label to stay describable.

Both inherit currentColor. Neither hardcodes a fill.

Run:  python tools/icons_build.py
"""

from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.svgLib.path import parse_path
import pathops

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "icons" / "pine-icons.json"
# frontend/ is tracked and is what the station serves (see /icons/{name} in
# app.py); data/ is runtime state, gitignored, and would not survive a deploy.
FRONTEND = ROOT / "frontend"
# The Electron shell loads its own files off disk, so it gets copies.
RENDERER = ROOT / "desktop" / "renderer"

UPM = 1000          # units per em
BASELINE = -125     # icons hang 12.5% below the baseline, as emoji do
ASCENT, DESCENT = 875, -125


# --- turning one SVG into one set of contours -----------------------------

def _shapes(svg: str):
    """Every drawable in the file as (path-data, is_inner, even_odd).

    Carbon marks the knockout in a two-tone icon with data-icon-path=
    "inner-path"; that part is subtracted, not added. A bare fill="none"
    with no such marker is an invisible bounding box and is dropped.
    """
    out = []
    for tag in re.finditer(r"<(path|circle|rect)\b([^>]*)/?>", svg):
        kind, attrs = tag.group(1), tag.group(2)

        def attr(name, default=None):
            m = re.search(rf'{name}\s*=\s*"([^"]*)"', attrs)
            return m.group(1) if m else default

        inner = attr("data-icon-path") == "inner-path"
        if attr("fill") == "none" and not inner:
            continue
        even_odd = attr("fill-rule") == "evenodd"

        if kind == "path":
            d = attr("d")
        elif kind == "circle":
            cx, cy = float(attr("cx", 0)), float(attr("cy", 0))
            r = float(attr("r", 0))
            k = r * 0.5522847498
            d = (f"M{cx - r},{cy}"
                 f"C{cx - r},{cy - k} {cx - k},{cy - r} {cx},{cy - r}"
                 f"C{cx + k},{cy - r} {cx + r},{cy - k} {cx + r},{cy}"
                 f"C{cx + r},{cy + k} {cx + k},{cy + r} {cx},{cy + r}"
                 f"C{cx - k},{cy + r} {cx - r},{cy + k} {cx - r},{cy}Z")
        else:  # rect
            x, y = float(attr("x", 0)), float(attr("y", 0))
            w, h = float(attr("width", 0)), float(attr("height", 0))
            d = f"M{x},{y}H{x + w}V{y + h}H{x}Z"
        if d:
            out.append((d, inner, even_odd))
    return out


def _viewbox(svg: str):
    m = re.search(r'viewBox\s*=\s*"([^"]+)"', svg)
    return [float(v) for v in re.split(r"[,\s]+", m.group(1).strip())]


def contours(svg: str) -> pathops.Path:
    """Union the additive shapes, subtract the knockouts, resolve winding.

    skia-pathops does the real work: it turns even-odd fills and overlapping
    subpaths into the non-zero, non-self-intersecting outlines TrueType
    needs. Doing this by hand is where icon fonts usually go wrong.
    """
    add, cut = pathops.Path(), pathops.Path()
    for d, inner, even_odd in _shapes(svg):
        piece = pathops.Path(
            fillType=pathops.FillType.EVEN_ODD if even_odd
            else pathops.FillType.WINDING)
        parse_path(d, piece.getPen())
        piece.simplify(fix_winding=True)
        target = cut if inner else add
        merged = pathops.op(target, piece, pathops.PathOp.UNION,
                            fix_winding=True)
        if inner:
            cut = merged
        else:
            add = merged
    if cut.segments:
        add = pathops.op(add, cut, pathops.PathOp.DIFFERENCE, fix_winding=True)
    return add


def glyph_for(svg: str):
    """One SVG -> one TrueType glyph, scaled into the em square."""
    vb_x, vb_y, vb_w, vb_h = _viewbox(svg)
    scale = UPM / vb_w
    # SVG y grows downward, font y grows upward, hence the -scale on d.
    matrix = (scale, 0, 0, -scale,
              -vb_x * scale, scale * (vb_y + vb_h) + BASELINE)
    pen = TTGlyphPen(None)
    contours(svg).draw(TransformPen(Cu2QuPen(pen, 0.6), matrix))
    return pen.glyph()


# --- the font -------------------------------------------------------------

def safe(ref: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", ref).strip("_")


def build_font(doc) -> bytes:
    art, mapping = doc["art"], doc["map"]

    order = [".notdef", "vs"] + [safe(r) for r in art]
    glyphs = {".notdef": TTGlyphPen(None).glyph(),
              "vs": TTGlyphPen(None).glyph()}
    metrics = {".notdef": (UPM, 0), "vs": (0, 0)}
    for ref, svg in art.items():
        name = safe(ref)
        glyphs[name] = glyph_for(svg)
        metrics[name] = (UPM, 0)

    cmap = {}
    for glyph, row in mapping.items():
        target = safe(row["icon"])
        for ch in glyph:
            if ch in ("️", "︎"):
                continue
            cmap[ord(ch)] = target
    # A variation selector must not fall through to a colour emoji font.
    cmap[0xFE0F] = "vs"
    cmap[0xFE0E] = "vs"

    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=ASCENT, descent=DESCENT)
    fb.setupNameTable({
        "familyName": "PineIcons",
        "styleName": "Regular",
        "uniqueFontIdentifier": "PineIcons;PineBox",
        "fullName": "PineIcons",
        "psName": "PineIcons-Regular",
        "version": "Version 1.000",
        "copyright": "IBM Carbon Icons and Material Symbols, both Apache-2.0",
    })
    fb.setupOS2(sTypoAscender=ASCENT, sTypoDescender=DESCENT, sTypoLineGap=0,
                usWinAscent=ASCENT, usWinDescent=-DESCENT,
                sxHeight=500, sCapHeight=700, achVendID="PINE")
    fb.setupPost(isFixedPitch=1)
    fb.font.flavor = "woff2"

    import io
    buf = io.BytesIO()
    fb.font.save(buf)
    return buf.getvalue(), sorted(cmap)


def ranges(codepoints):
    """Codepoints as a compact CSS unicode-range list."""
    out, start, prev = [], None, None
    for cp in codepoints:
        if start is None:
            start = prev = cp
        elif cp == prev + 1:
            prev = cp
        else:
            out.append((start, prev))
            start = prev = cp
    if start is not None:
        out.append((start, prev))
    return ",".join(f"U+{a:04X}" if a == b else f"U+{a:04X}-{b:04X}"
                    for a, b in out)


CSS = """/* Pine Box icons - generated by tools/icons_build.py, do not hand-edit.

   The station's icons used to be colour emoji. This font draws every one of
   them as a single-colour vector: IBM Carbon Icons, with Material Symbols
   Outlined where Carbon has no glyph. Both Apache-2.0, both vendored.

   The cmap maps the REAL emoji codepoints, so nothing in the application has
   to be rewritten for an icon to stop being colourful - including records
   already written to disk, <option> labels, and every string handed to
   textContent, none of which could ever have held an <svg>.

   unicode-range is the safety rail: this font is consulted for the %d
   pictograph codepoints below and for nothing else, so adding 'PineIcons'
   to a font stack cannot change how one letter of text looks.

   Icons inherit currentColor and font-size like any other character. */

@font-face {
  font-family: 'PineIcons';
  font-style: normal;
  font-weight: 400;
  font-display: block;           /* never flash the colour emoji first */
  src: url(data:font/woff2;base64,%s) format('woff2');
  unicode-range: %s;
}

/* Sitting the icon on the text's optical centre. Harmless on a bare glyph;
   used by the sprite helper and by any element that is only an icon. */
.pi-icon {
  display: inline-block;
  width: 1em;
  height: 1em;
  vertical-align: -0.145em;
  fill: currentColor;
  flex: none;
}

/* An icon-only control: the glyph carries no text, so the accessible name
   must come from aria-label. */
.pi-only { line-height: 1; }
"""


SPRITE = """/* Pine Box icons - generated by tools/icons_build.py, do not hand-edit.

   The SVG sprite, for markup that wants a real <svg> element it can size and
   label rather than a character in a string. One <use> reference per icon,
   every one inheriting currentColor.

   The sprite is injected into the document rather than referenced across
   files, because <use href="other.svg#id"> is unreliable in the Android
   WebView the tablet runs.

     pineIcon("c:microphone")               -> markup, for innerHTML
     pineIcon("c:microphone", "the booth")  -> with an accessible name
     pineIconFor("\\ud83c\\udf99")            -> by the emoji it replaces

   Static markup asks for an icon by attribute instead, because the sprite
   is injected at load and a <use> written into the HTML would be resolved
   before its target exists:

     <button data-pine-icon="c:gem" aria-label="Crystals"></button>

   pineIconUpgrade() fills those in once the sprite is there; call it with a
   root element after inserting markup of your own.

   Icons with no label are aria-hidden: the neighbouring text names them. */

(function (root) {
  "use strict";

  var ART = %s;
  var BY_GLYPH = %s;
  var injected = false;

  function id(ref) { return "pi-" + ref.replace(/[^A-Za-z0-9]+/g, "-"); }

  function inject() {
    if (injected || !root.document || !root.document.body) return;
    var host = root.document.getElementById("pineIconSprite");
    if (!host) {
      host = root.document.createElementNS(
        "http://www.w3.org/2000/svg", "svg");
      host.setAttribute("id", "pineIconSprite");
      host.setAttribute("aria-hidden", "true");
      host.style.cssText =
        "position:absolute;width:0;height:0;overflow:hidden";
      var parts = [];
      for (var ref in ART) {
        if (!Object.prototype.hasOwnProperty.call(ART, ref)) continue;
        parts.push('<symbol id="' + id(ref) + '" viewBox="' +
                   ART[ref][0] + '">' + ART[ref][1] + "</symbol>");
      }
      host.innerHTML = parts.join("");
      root.document.body.insertBefore(host, root.document.body.firstChild);
    }
    injected = true;
  }

  function pineIcon(ref, label) {
    if (!ART[ref]) return "";
    inject();
    var named = label !== undefined && label !== null && label !== "";
    return '<svg class="pi-icon" ' +
      (named ? 'role="img" aria-label="' + String(label)
                 .replace(/&/g, "&amp;").replace(/"/g, "&quot;")
                 .replace(/</g, "&lt;") + '"'
             : 'aria-hidden="true" focusable="false"') +
      '><use href="#' + id(ref) + '"/></svg>';
  }

  function pineIconFor(glyph, label) {
    var ref = BY_GLYPH[glyph];
    return ref ? pineIcon(ref, label) : "";
  }

  /* Fill in every [data-pine-icon] under `where` (the document by default).
     Each element is done once; calling it again after inserting markup is
     cheap and safe. An element that already carries its own aria-label or
     title keeps it - the icon inside is then decorative. */
  function pineIconUpgrade(where) {
    var root_ = where || root.document;
    if (!root_ || !root_.querySelectorAll) return 0;
    var list = root_.querySelectorAll("[data-pine-icon]:not([data-pine-done])");
    for (var i = 0; i < list.length; i++) {
      var el = list[i];
      var ref = el.getAttribute("data-pine-icon");
      if (!ART[ref]) continue;
      var named = !el.getAttribute("aria-label") && !el.getAttribute("title")
        ? el.getAttribute("data-pine-label") : null;
      el.innerHTML = pineIcon(ref, named);
      el.setAttribute("data-pine-done", "1");
    }
    return list.length;
  }

  function start() { inject(); pineIconUpgrade(); }

  if (root.document) {
    if (root.document.readyState === "loading") {
      root.document.addEventListener("DOMContentLoaded", start);
    } else {
      start();
    }
  }

  root.pineIcon = pineIcon;
  root.pineIconFor = pineIconFor;
  root.pineIconUpgrade = pineIconUpgrade;
  root.pineIconRefs = ART;
})(typeof window !== "undefined" ? window : this);
"""


def build_sprite(doc) -> str:
    art = {}
    for ref, svg in doc["art"].items():
        vb = re.search(r'viewBox\s*=\s*"([^"]+)"', svg).group(1)
        body = re.sub(r"^<svg[^>]*>|</svg>\s*$", "", svg).strip()
        # currentColor, never a hardcoded fill.
        body = re.sub(r'\sfill="(?!none)[^"]*"', "", body)
        art[ref] = [vb, body]
    by_glyph = {g: row["icon"] for g, row in doc["map"].items()}
    return SPRITE % (json.dumps(art, ensure_ascii=False, sort_keys=True),
                     json.dumps(by_glyph, ensure_ascii=True, sort_keys=True))


def main() -> int:
    doc = json.loads(SRC.read_text(encoding="utf-8"))
    woff2, codepoints = build_font(doc)
    css = CSS % (len(codepoints),
                 base64.b64encode(woff2).decode("ascii"),
                 ranges(codepoints))
    sprite = build_sprite(doc)

    written = []
    for folder in (FRONTEND, RENDERER):
        if not folder.exists():
            continue
        for name, text in (("pineicons.css", css), ("pine-icons.js", sprite)):
            path = folder / name
            path.write_text(text, encoding="utf-8")
            written.append(path)

    print(f"font      {len(woff2):,} bytes woff2, "
          f"{len(doc['art'])} outlines, {len(codepoints)} codepoints")
    for path in written:
        print(f"wrote     {path.relative_to(ROOT)}  "
              f"({path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
