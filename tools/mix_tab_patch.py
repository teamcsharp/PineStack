"""[mix-tab] One lane per TAB, not per (link, address).

2026-09-30: two tune pages on one address with one share link (#1421-#1424,
47.155.59.173: two tabs, or two people behind one router) were one "listener"
to [mix-lane], so each one's new mix RELEASED the other's lane while it was
playing: Safari answered MEDIA_ERR_SRC_NOT_SUPPORTED seven times in a row and
the other page kept re-asking. The tune page now sends a per-tab id with the
master (`who`, sessionStorage); the station keys the lane move on it, and
falls back to the link and address for a page that predates it.
Anchor-asserted; run on the host."""
import ast
import sys
from pathlib import Path

p = Path(sys.argv[1] if len(sys.argv) > 1 else "app.py")
a = p.read_text()
if "[mix-tab]" in a:
    raise SystemExit("already patched")


def sub(text, old, new, name):
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"anchor {name}: found {n} times")
    return text.replace(old, new)


a = sub(a, '''    abr: str = "",                                          # [#1475]
''', '''    abr: str = "",                                          # [#1475]
    who: str = "",                                          # [mix-tab]
''', "route-param")
a = sub(a, '''    _hls_mix_move(t, request, personal_mix)                 # [mix-lane]
''', '''    _hls_mix_move(t, request, personal_mix, who)            # [mix-lane] [mix-tab]
''', "route-call")
a = sub(a, '''def _hls_mix_move(token: str, request: Request, mix: Any) -> None:''',
        '''def _hls_mix_move(token: str, request: Request, mix: Any, tab: str = "") -> None:''',
        "helper-sig")
a = sub(a, '''        who = "%s|%s" % (str(token or "")[-12:], addr)
''', '''        who = "%s|%s" % (str(token or "")[-12:], addr)
        # [mix-tab] a page names its own tab: two tabs, or two people behind
        # one router on one link, are two listeners - never one
        tab = re.sub(r"[^A-Za-z0-9_-]", "", str(tab or ""))[:40]
        if tab:
            who = "%s|tab:%s" % (str(token or "")[-12:], tab)
''', "helper-key")
a = sub(a, '''  if (GUEST) url += "&t=" + encodeURIComponent(KEY);
''', '''  if (GUEST) url += "&t=" + encodeURIComponent(KEY);
  if (wantsHls()) url += "&who=" + encodeURIComponent(tuneTab());   /* [mix-tab] */
''', "page-url")
a = sub(a, '''function mixNotApplied(why) {''', '''/* [mix-tab] this tab's own name for the station: its personal-mix lane is
 * released when THIS tab moves on, never when another tab on the same link
 * and address does. */
function tuneTab() {
  try {
    let id = sessionStorage.getItem("pbfmTuneTab");
    if (!id) {
      id = Math.random().toString(36).slice(2, 12);
      sessionStorage.setItem("pbfmTuneTab", id);
    }
    return id;
  } catch (e) {
    if (!window.__pbfmTuneTab) window.__pbfmTuneTab = Math.random().toString(36).slice(2, 12);
    return window.__pbfmTuneTab;
  }
}
function mixNotApplied(why) {''', "page-tab")
ast.parse(a)
p.write_text(a)
print("patched", p)
