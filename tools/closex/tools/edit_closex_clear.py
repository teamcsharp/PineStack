#!/usr/bin/env python3
"""[closex:clear] Nothing sits under the corner X.

Operator 2026-09-29, the line sheet: the X was drawn over the thumbs-down in
"What would you like to do with this?". pineCloseX now measures, after it is
placed (and again once icons and fonts settle, and on resize): any control the
X covers gets its row padded clear of the X, so the controls move left and
the X stands alone in its corner. Applies to every popup that uses the helper.

usage: edit_closex_clear.py --check|--apply <pine-closex.js>
exit 0 ready, 2 already applied, 1 anchor missing
"""
import sys
from pathlib import Path

MARK = "[closex:clear]"
A1 = "      if (x.parentNode !== pop) pop.appendChild(x);\n    }\n    return true;\n  }\n"
N1 = ("      if (x.parentNode !== pop) pop.appendChild(x);\n    }\n    soon(entry);   /* [closex:clear] */\n    return true;\n  }\n"
      "\n"
      "  /* [closex:clear] nothing sits under the X: a control whose box the X\n"
      "   * covers gets its row padded clear of it, so the row's controls move\n"
      "   * left (operator 2026-09-29: the thumbs sat under the X). */\n"
      "  function clear(entry) {\n"
      "    var pop = entry.node, x = entry.button;\n"
      "    if (!pop.isConnected || !x.isConnected) return;\n"
      "    var xr = x.getBoundingClientRect();\n"
      "    if (!xr.width || !xr.height) return;\n"
      "    var list = pop.querySelectorAll('button, a[href], input, select, textarea, [role=\"button\"], .pcx-avoid');\n"
      "    for (var i = 0; i < list.length; i += 1) {\n"
      "      var el = list[i];\n"
      "      if (el === x || x.contains(el) || el.contains(x)) continue;\n"
      "      var r = el.getBoundingClientRect();\n"
      "      if (!r.width || r.bottom <= xr.top + 2 || r.top >= xr.bottom - 2 || r.right <= xr.left + 2 || r.left >= xr.right - 2) continue;\n"
      "      var row = el.parentElement && el.parentElement !== pop ? el.parentElement : el;\n"
      "      var had = 0;\n"
      "      try { had = parseFloat(root.getComputedStyle(row).paddingRight) || 0; } catch (e) { had = 0; }\n"
      "      row.style.paddingRight = Math.ceil(had + (r.right - xr.left) + 6) + 'px';\n"
      "      row.setAttribute('data-pcx-clear', '');\n"
      "    }\n"
      "  }\n"
      "  function soon(entry) {\n"
      "    if (entry.clearing) return;\n"
      "    entry.clearing = true;\n"
      "    var go = function () { try { clear(entry); } catch (e) { /* the X stands without it */ } };\n"
      "    (root.requestAnimationFrame || root.setTimeout)(function () { entry.clearing = false; go(); });\n"
      "    root.setTimeout(go, 350);    /* icons and fonts settle */\n"
      "    root.setTimeout(go, 1200);\n"
      "    if (!clearWired) {\n"
      "      clearWired = true;\n"
      "      root.addEventListener('resize', function () {\n"
      "        for (var i = 0; i < entries.length; i += 1) { try { clear(entries[i]); } catch (e) { /* next */ } }\n"
      "      });\n"
      "    }\n"
      "  }\n"
      "  var clearWired = false;\n")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    p = Path(sys.argv[2])
    raw = p.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n")
    if MARK in text:
        print(f"{MARK} already applied: {p}"); return 2
    if text.count(A1) != 1:
        print(f"{MARK} anchor missing ({text.count(A1)}): {p}"); return 1
    if mode != "--apply":
        print(f"{MARK} ready: {p}"); return 0
    text = text.replace(A1, N1, 1)
    if crlf:
        text = text.replace("\n", "\r\n")
    p.write_bytes(text.encode("utf-8"))
    print(f"{MARK} applied: {p}"); return 2


if __name__ == "__main__":
    sys.exit(main())
