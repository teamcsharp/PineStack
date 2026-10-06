#!/usr/bin/env python3
"""[pip-video-folder] The Video menu has its folders when it opens. 2026-10-06.

The folders were fetched only when the menu first opened, and the station took over a minute to
answer, so the list was empty. Now they are fetched the moment PiP is entered (and every five
minutes after), the first menu waits up to two and a half seconds for them, and a menu that opens
before they arrive says so instead of showing nothing. Both copies of pine-pip.js; pip-window.cjs.

Usage:  pip_folders_ready_patch.py --check [ROOT]   0 ready, 2 applied, 1 anchors missing
        pip_folders_ready_patch.py --apply [ROOT]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

JS_FETCH_OLD = r'''  let foldersCache = { folders: [], pin: null }, foldersAt = 0, foldersPending = false;
  function refreshFolders() {
    if (foldersPending || Date.now() - foldersAt < 60000) return; foldersPending = true;
    Promise.resolve().then(() => api().get('/api/sfx/folders')).then(got => {
      const rows = Array.isArray(got?.folders) ? got.folders : [];
      foldersCache = { folders: rows.map(f => ({ path: String(f.path || ''), name: String(f.name || f.path || ''), video: Number(f.video) || 0, audio: Number(f.audio) || 0 })).sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base', numeric: true })), pin: got?.pin || null };
      foldersAt = Date.now();
    }).catch(() => {}).finally(() => { foldersPending = false; });
  }
'''
JS_FETCH_NEW = r'''  let foldersCache = { folders: [], pin: null }, foldersAt = 0, foldersPending = null;
  function refreshFolders(force) {
    if (foldersPending) return foldersPending;
    if (!force && Date.now() - foldersAt < (foldersCache.folders.length ? 300000 : 20000)) return Promise.resolve();
    foldersPending = Promise.resolve().then(() => api().get('/api/sfx/folders')).then(got => {
      const rows = Array.isArray(got?.folders) ? got.folders : [];
      foldersCache = { folders: rows.map(f => ({ path: String(f.path || ''), name: String(f.name || f.path || ''), video: Number(f.video) || 0, audio: Number(f.audio) || 0 })).sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base', numeric: true })), pin: got?.pin || null };
      foldersAt = Date.now();
    }).catch(() => { foldersAt = Date.now() - 280000; }).finally(() => { foldersPending = null; });
    return foldersPending;
  }
'''
JS_MENU_OLD = r'''      const opening = api().pipMenu({...playbackCache,favorites,folders:foldersCache.folders,pin:foldersCache.pin});   /* [pip-video-folder] */
      refreshFolders();
'''
JS_MENU_NEW = r'''      /* [pip-video-folder] the first menu waits a moment for the folders; later ones have them already */
      if (!foldersCache.folders.length) await Promise.race([refreshFolders(), new Promise(resolve => setTimeout(resolve, 2500))]);
      const opening = api().pipMenu({...playbackCache,favorites,folders:foldersCache.folders,pin:foldersCache.pin,foldersLoading:!foldersCache.folders.length&&!!foldersPending});
      refreshFolders();
'''
JS_ENTER_OLD = r'''    if (next.active && !was) confirmPanel();   /* [pip-panel-ready] and make sure the page really switched */
'''
JS_ENTER_NEW = r'''    if (next.active && !was) confirmPanel();   /* [pip-panel-ready] and make sure the page really switched */
    if (next.active && !was) refreshFolders(true);   /* [pip-video-folder] the folders are asked for on entry, not at the menu */
'''
JS_ACTION_OLD = r'''      return api().post('/api/sfx/folder-pin', body).then(got => { foldersAt = 0; refreshFolders(); say(got?.say || (body.clear ? 'Every folder again' : 'Clips come from ' + action.path + ' for the next hour'), 7000); }).catch(err => say(err.message));
'''
JS_ACTION_NEW = r'''      return api().post('/api/sfx/folder-pin', body).then(got => { refreshFolders(true); say(got?.say || (body.clear ? 'Every folder again' : 'Clips come from ' + action.path + ' for the next hour'), 7000); }).catch(err => say(err.message));
'''
WIN_OLD = r'''        { type: 'separator' },
        ...(Array.isArray(playback?.folders) ? playback.folders : []).filter(f => f && typeof f.path === 'string').slice(0, 300)
'''
WIN_NEW = r'''        { type: 'separator' },
        ...(!(Array.isArray(playback?.folders) && playback.folders.length) ? [{ label: playback?.foldersLoading ? 'Reading the SFX catalog\u2019s folders - open the menu again in a moment' : 'The station has not listed its folders yet - open the menu again', enabled: false }] : []),
        ...(Array.isArray(playback?.folders) ? playback.folders : []).filter(f => f && typeof f.path === 'string').slice(0, 300)
'''
PIPJS = [
    ("the fetch is a promise with a short memory", JS_FETCH_OLD, JS_FETCH_NEW, "function refreshFolders(force) {", 1),
    ("the first menu waits for the folders", JS_MENU_OLD, JS_MENU_NEW, "foldersLoading:!foldersCache.folders.length&&!!foldersPending", 1),
    ("entry asks for them", JS_ENTER_OLD, JS_ENTER_NEW, "if (next.active && !was) refreshFolders(true);", 1),
    ("a pin refreshes them", JS_ACTION_OLD, JS_ACTION_NEW, "then(got => { refreshFolders(true); say(", 1),
]
EDITS = {
    "desktop/renderer/pine-pip.js": PIPJS,
    "app/src/main/assets/pine-views/pine-pip.js": PIPJS,
    "desktop/pip-window.cjs": [("an empty list says why", WIN_OLD, WIN_NEW, "Reading the SFX catalog", 1)],
}


def endings(text: str) -> str:
    crlf, lf = text.count("\r\n"), text.count("\n")
    return "lf" if not crlf else "crlf" if crlf == lf else "mixed"


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("--check", "--apply"):
        print(__doc__)
        return 1
    root = Path(argv[2]) if len(argv) > 2 else Path(__file__).resolve().parent.parent
    ready = missing = False
    plans = []
    for name, edits in EDITS.items():
        path = root / name
        if not path.exists():
            print("%-46s (not in this tree - skipped)" % name[-46:])
            continue
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = (raw[3:] if bom else raw).decode("utf-8")
        mode = endings(text)
        if mode == "crlf":
            text = text.replace("\r\n", "\n")
        changed = False
        for label, old, new, probe, count in edits:
            forms = [(old, new, probe)]
            if mode == "mixed":
                forms.append((old.replace("\n", "\r\n"), new.replace("\n", "\r\n"), probe.replace("\n", "\r\n")))
            state = ""
            for old_, new_, probe_ in forms:
                have = text.count(probe_)
                if have == count:
                    state = "applied"
                    break
                if not have and text.count(old_) == count:
                    text = text.replace(old_, new_)
                    assert text.count(probe_) == count, (name, label, "probe after the edit")
                    state, changed = "ready", True
                    break
            if not state:
                state = "missing (anchor found %d, probe %d)" % (text.count(old), text.count(probe))
            print("%-46s %-44s %s" % (name[-46:], label, state))
            if state == "ready":
                ready = True
            elif state != "applied":
                missing = True
        plans.append((path, text, bom, mode, changed))
    if missing:
        print("ANCHORS MISSING - nothing written")
        return 1
    if not ready:
        print("already applied")
        return 2
    if argv[1] == "--check":
        print("ready")
        return 0
    for path, text, bom, mode, changed in plans:
        if not changed:
            continue
        body = (text.replace("\n", "\r\n") if mode == "crlf" else text).encode("utf-8")
        tmp = path.with_name(path.name + ".pipfolders.tmp")
        tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + body)
        os.replace(tmp, path)
        print("wrote %s (%s%s)" % (path, mode.upper(), ", BOM" if bom else ""))
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
