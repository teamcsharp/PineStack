#!/usr/bin/env python3
"""closex_frontend - System 3 (frontend/system3.js): the corner X on every
card and menu (through movableModal, the one road they are all built on)
and on the two full windows.

    python closex_frontend.py --check <repo-root>
    python closex_frontend.py --apply <repo-root>

system3.js is also edited by the staged wave; every anchor here is one line.
On the tune page (no pine-closex.js) each guard is a no-op and the cards keep
the Close they had.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from closex_patchlib import Insert, main  # noqa: E402

F = "frontend/system3.js"

PATCHES = [
    Insert(F, "closex:s3-modal", "  return panel;", """\
  /* [closex:s3-modal] Every System 3 card and menu gets the corner X. It
     presses the card's own Close, or taps its own backdrop - the road
     PineDismiss's BACK already takes. A header Close steps aside for it;
     a menu's Close at the foot stays where the list ends. */
  if (window.pineCloseX) {
    const own = panel.querySelector('.s3-modal-close');
    window.pineCloseX(panel, () => {
      if (own) { own.click(); return; }
      const back = panel.closest('.s3-modal-back');
      if (back) back.click();
    });
    if (own && own.parentNode === panel) own.style.display = 'none';
  }""", where="before", scope="function movableModal(panel) {", within=8),
    Insert(F, "closex:s3-window", "  view = await mount(root, {request, onClose: close, tab, table, conversationId});",
           "  if (!closed && window.pineCloseX) window.pineCloseX(root, close, {label: 'Close System 3'});   // [closex:s3-window]"),
    Insert(F, "closex:s3-focus", "  view = await mount(root, {request, onClose: close, tab: tab || 'focus'});",
           "  if (!closed && window.pineCloseX) window.pineCloseX(root, close, {label: 'Close System 3'});   // [closex:s3-focus]"),
    Insert(F, "closex:s3-audit-menu", "    document.body.append(menuNode);",
           "    if (window.pineCloseX) window.pineCloseX(menuNode, close, {label: 'Close the menu', reserve: 'top'});   // [closex:s3-audit-menu]",
           scope="  function auditMenu(x, y, e, prev) {", within=20),
    # the other windows the panel imports: their Close sat mid-header (or
    # answered no Escape); the corner X is their own close road
    Insert("frontend/system2.js", "closex:s2-window", "  view = await mount(root, {request, onClose: close});",
           "  if (!closed && window.pineCloseX) window.pineCloseX(root, close, {label: 'Close System2'});   // [closex:s2-window]"),
    Insert("frontend/word-cause.js", "closex:word-cause", "  host.appendChild(root);",
           "  if (!embed && window.pineCloseX) { window.pineCloseX(root, () => close(), {label: 'Close'}); shut.style.display = 'none'; }   // [closex:word-cause]",
           scope="export function openWordCause(opts) {", within=200),
    Insert("frontend/comfy-workshop.js", "closex:comfy-workshop",
           "  dialog.append(header, body); shade.append(dialog); document.body.append(shade);",
           "  if (window.pineCloseX) { window.pineCloseX(dialog, () => closeButton.click(), {label: 'Close Workshop'}); closeButton.style.display = 'none'; }   // [closex:comfy-workshop]"),
    Insert("frontend/station-flow.js", "closex:station-flow",
           "  closeBtn.setAttribute(\"aria-label\",\"Close station flow\");closeBtn.onclick=close;",
           "  if(window.pineCloseX){window.pineCloseX(dialog,()=>closeBtn.click(),{label:\"Close station flow\"});closeBtn.style.display=\"none\";}   // [closex:station-flow]"),
]

if __name__ == "__main__":
    sys.exit(main(PATCHES))
