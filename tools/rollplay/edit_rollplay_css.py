#!/usr/bin/env python3
"""[rollplay] the roll tag styles (script-page.css, appended)

Targets: desktop/renderer/script-page.css and app/src/main/assets/pine-views/script-page.css

  python edit_rollplay_css.py --check <file> [<file> ...]   exit 0 ready / 2 applied / 1 anchor missing
  python edit_rollplay_css.py --apply <file> [<file> ...]   idempotent; resumes a half-applied file

Marker-idempotent: an edit counts as APPLIED when its whole replacement is in
the file, READY when its anchor occurs exactly once. Line endings are kept
(a CRLF file stays CRLF, an LF file LF). The write is atomic, and a .js file
must pass `node --check` (when node is on PATH) before it replaces the old
one; a .json file must parse.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

EDITS = [('C1 the roll tag styles (appended)', None, '\n/* [rollplay] THE ROLL TAG, ANYWHERE: the Message view\'s bubble replayed for\n   one line in any popup (PineRollTag.mount in script-page.js) - the hold\n   menu\'s dice section, the repeat diagnostics\' top section, the Script\n   popup\'s Roll tab. The bubble keeps every .sp-mv-* / .sp-rr-* rule above;\n   these only seat it in a popup and lay out what System 3 made it from.\n   The popups\' own `button` rules are out-ranked here so the tile\'s Result\n   tab and tally rows look as they do in Message view. */\n.rt-tag {\n  display: flex; flex-direction: column; gap: 8px; min-width: 0;\n  color: var(--sp-text, #edf3f5); font: 13px/1.4 Inter, "Segoe UI", system-ui, sans-serif; text-align: left;\n}\n.rt-bar { display: flex; align-items: center; gap: 8px; min-width: 0; }\n.rt-title { flex: 1; min-width: 0; font-size: 14px; font-weight: 650; }\n.rt-style {\n  flex: none; padding: 2px 8px; border: 1px solid #35414c; border-radius: 999px;\n  font: 600 10.5px Inter, "Segoe UI", system-ui, sans-serif; letter-spacing: .06em; text-transform: uppercase; color: var(--sp-muted, #8fa0ad);\n}\n.rt-tag button.rt-play {\n  flex: none; display: inline-flex; align-items: center; gap: 6px; min-height: 34px; padding: 0 14px 0 11px; margin: 0;\n  border: 1px solid var(--sp-on, #65c7da); border-radius: 999px; background: rgba(101, 199, 218, .12);\n  color: var(--sp-on, #65c7da); font: 700 12.5px Inter, "Segoe UI", system-ui, sans-serif; cursor: pointer;\n}\n.rt-tag button.rt-play:hover { background: rgba(101, 199, 218, .22); }\n.rt-play-ico, .rt-play-ico svg { width: 15px; height: 15px; fill: currentColor; display: inline-flex; }\n.rt-tag .rt-stage {\n  position: relative; flex: none; min-height: 132px; overflow: visible;\n  justify-content: flex-start; gap: 0; padding: 18px 2px 4px;\n  border: 1px solid #26313a; border-radius: 12px; background: #0b1117;\n}\n.rt-tag .rt-stage > .sp-mv-item { max-width: 100%; }\n.rt-tag .rt-stage > .sp-mv-item.sp-mv-digital { width: min(460px, 100%); }\n.rt-tag .rt-stage > .sp-mv-left { margin-left: 10px; }\n.rt-tag .rt-stage > .sp-mv-right { margin-right: 10px; }\n.rt-tag .rt-stage .sp-mv-all { position: static; max-height: none; margin-top: 4px; box-shadow: none; }\n.rt-tag .rt-wait { align-self: center; margin: 32px 0; }\n.rt-tag button.sp-mv-result {\n  min-height: 24px; margin-top: -2px; padding: 1px 12px 2px; border: 2px solid #3a4a57; border-top: 0; border-radius: 0 0 10px 10px;\n  background: #121a21; color: #cfe3ea; font: 700 12px Inter, "Segoe UI", system-ui, sans-serif;\n}\n.rt-tag button.sp-mv-resrow {\n  min-height: 30px; padding: 5px 9px; border: 1px solid rgba(53, 65, 76, .8); border-left: 3px solid var(--fam, #68ced9); border-radius: 6px;\n  background: #0e151b; color: #d6e3e9; font: 12px Inter, "Segoe UI", system-ui, sans-serif;\n}\n.rt-tag .sp-mv-results .sp-mv-rolls { cursor: pointer; }\n.rt-facts { display: flex; flex-direction: column; gap: 8px; min-width: 0; }\n.rt-verdict { margin: 0; padding: 6px 10px; border-left: 3px solid #54d18b; border-radius: 6px; background: rgba(84, 209, 139, .08); font-size: 12.5px; overflow-wrap: anywhere; }\n.rt-verdict.rt-v-forced { border-left-color: #d9b24c; background: rgba(217, 178, 76, .1); }\n.rt-verdict.rt-v-rogue, .rt-verdict.rt-v-none { border-left-color: #ef7b72; background: rgba(239, 123, 114, .1); }\n.rt-sec { min-width: 0; }\n.rt-tag .rt-h {\n  display: flex; align-items: baseline; gap: 6px; margin: 2px 0 4px;\n  font: 700 10.5px Inter, "Segoe UI", system-ui, sans-serif; letter-spacing: .08em; text-transform: uppercase; color: var(--sp-muted, #8fa0ad);\n}\n.rt-h i { font-style: normal; color: #cfe3ea; }\n.rt-table { width: 100%; border-collapse: separate; border-spacing: 0 3px; font-size: 12px; table-layout: auto; }\n.rt-table th { padding: 0 6px; text-align: left; font: 600 10px Inter, "Segoe UI", system-ui, sans-serif; letter-spacing: .05em; text-transform: uppercase; color: #6f808c; }\n.rt-table td { padding: 3px 6px; background: #0e151b; vertical-align: top; overflow-wrap: anywhere; color: #d6e3e9; }\n.rt-table td:first-child { border-left: 3px solid var(--fam, #68ced9); border-radius: 6px 0 0 6px; }\n.rt-table td:last-child { border-radius: 0 6px 6px 0; }\n.rt-table .rt-tb { color: var(--fam, #68ced9); font-weight: 700; white-space: nowrap; }\n.rt-table .rt-tb i { display: block; font-style: normal; font-weight: 400; font-size: 10.5px; color: #8fa0ad; white-space: normal; }\n.rt-table .rt-d { width: 1%; font: 700 11px ui-monospace, Consolas, monospace; color: #fff; text-align: center; white-space: nowrap; }\n.rt-table .rt-extra td:first-child { border-left-style: dashed; }\n.rt-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 3px; }\n.rt-list li { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px; padding: 3px 8px; border-radius: 6px; background: #0e151b; font-size: 12px; overflow-wrap: anywhere; }\n.rt-list li b { color: #cfe3ea; font-weight: 700; }\n.rt-list li span { color: #9fb0bb; min-width: 0; }\n.rt-list li em { font-style: normal; font-size: 10px; padding: 0 5px; border-radius: 999px; background: rgba(101, 199, 218, .16); color: var(--sp-on, #65c7da); text-transform: uppercase; letter-spacing: .06em; }\n.rt-list .rt-ico, .rt-list .rt-ico svg { width: 14px; height: 14px; fill: currentColor; color: var(--sp-on, #65c7da); align-self: center; display: inline-flex; }\n.rt-none { margin: 0; font-size: 12px; color: var(--sp-muted, #8fa0ad); }\n/* the tile folded to its facts (the hold menu) */\n.rt-fold > summary { cursor: pointer; font: 700 10.5px Inter, "Segoe UI", system-ui, sans-serif; letter-spacing: .08em; text-transform: uppercase; color: var(--sp-muted, #8fa0ad); padding: 2px 0; }\n.rt-fold[open] > summary { margin-bottom: 6px; }\n/* the clip in a popup: drag to scrub, tap to play it with sound on a loop */\n.rt-pip {\n  position: relative; width: 100%; aspect-ratio: 16 / 9; min-height: 96px; overflow: hidden;\n  border: 1px solid #35414c; border-radius: 12px; background: #000; touch-action: none; cursor: ew-resize;\n  -webkit-user-select: none; user-select: none;\n}\n.rt-pip-face, .rt-pip-face > * { position: absolute; inset: 0; width: 100%; height: 100%; }\n.rt-pip-face img, .rt-pip-face video { object-fit: contain; pointer-events: none; }\n.rt-pip-face audio { display: none; }\n.rt-pip-led { background: transparent; pointer-events: none; }\n.rt-pip-state {\n  position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); width: 42px; height: 42px;\n  display: flex; align-items: center; justify-content: center; border-radius: 50%;\n  background: rgba(0, 0, 0, .55); color: #fff; pointer-events: none; transition: opacity .2s;\n}\n.rt-pip-state .sp-mv-ico, .rt-pip-state svg { width: 20px; height: 20px; fill: currentColor; }\n.rt-pip-pause { display: none; }\n.rt-pip.rt-pip-on .rt-pip-state { opacity: 0; }\n.rt-pip.rt-pip-scrub .rt-pip-state { opacity: 0; }\n.rt-pip-time {\n  position: absolute; left: 8px; bottom: 9px; padding: 1px 6px; border-radius: 6px; background: rgba(0, 0, 0, .6);\n  color: #fff; font: 600 11px ui-monospace, Consolas, monospace; pointer-events: none;\n}\n.rt-pip.rt-pip-scrub .rt-pip-time { font-size: 13px; color: var(--sp-on, #65c7da); }\n.rt-pip-bar { position: absolute; left: 0; right: 0; bottom: 0; height: 4px; background: rgba(255, 255, 255, .12); pointer-events: none; }\n.rt-pip-bar i { position: absolute; left: 0; top: 0; bottom: 0; width: 0; background: var(--sp-on, #65c7da); }\n/* the three homes */\n.la-head.la-tiled .la-said { display: none; }\n.la-roll-band { display: flex; gap: 10px; align-items: flex-start; margin: 6px 0 10px; min-width: 0; }\n.la-roll-box { flex: 1 1 auto; min-width: 0; max-height: min(44vh, 400px); overflow-y: auto; overscroll-behavior: contain; padding-right: 2px; }\n.la-clip-band .la-roll-box { flex: 1 1 56%; }\n.la-pip-box { flex: 1 1 44%; min-width: 0; }\n.la-roll-box .rt-tag .rt-stage { min-height: 112px; padding-top: 16px; }\n.la-roll-box .rt-bar { display: none; }\n.lr-section.lr-roll { border-top: 0; }\n.sp-detail-roll[hidden] { display: none; }\n.sp-detail-roll { min-width: 0; max-height: min(56vh, 520px); overflow-y: auto; overscroll-behavior: contain; }\n/* [rollplay] rejected and failed: they pop in, then go grey and inert (reason on hover / long-press) */\n.sp-rr-step.sp-rr-has-rej { flex-wrap: wrap; row-gap: 4px; }\n.sp-rr-rej { flex-basis: 100%; display: flex; flex-wrap: wrap; gap: 4px; padding-left: 34px; min-width: 0; }\n.sp-rr-sub .sp-rr-rej { padding-left: 34px; }\n.sp-rr-rejc {\n  max-width: 100%; padding: 0 7px; border: 1px solid var(--fam, #68ced9); border-radius: 6px;\n  font: 11px/18px Inter, "Segoe UI", system-ui, sans-serif; color: #e8f1f5; background: rgba(255, 255, 255, .05);\n  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; cursor: help;\n  opacity: 0; transform: scale(.6); transition: transform .12s ease-out, opacity .12s linear, filter .25s, color .25s;\n}\n.sp-rr-rejc.pop { opacity: 1; transform: scale(1.08); }\n.sp-rr-rejc.gone { opacity: .5; transform: none; filter: grayscale(1); color: #7d8a93; border-color: #4a5560; text-decoration: line-through; }\n.sp-rr-t.sp-rr-failed { filter: grayscale(1); opacity: .5; cursor: help; }\n.sp-rr-rejn { margin-left: auto; flex: none; font-size: 10px; color: #7d8a93; cursor: help; }\n/* the finished table: the category on its row, the sub-result indented under it */\n.sp-rr-t.folded .sp-rr-line.sp-rr-two { display: flex; flex-direction: column; align-items: stretch; gap: 1px; white-space: normal; }\n.sp-rr-two .sp-rr-lc, .sp-rr-two .sp-rr-ls { display: flex; align-items: baseline; gap: 6px; min-width: 0; white-space: nowrap; overflow: hidden; }\n.sp-rr-two .sp-rr-ls { padding-left: 22px; }\n.sp-rr-two .sp-rr-ll { min-width: 0; overflow: hidden; text-overflow: ellipsis; }\n.sp-rr-two .sp-rr-lof { margin-left: auto; flex: none; font-size: 10px; }\n/* the clip\'s file type, off the file: video teal, audio amber */\n.sp-mv-ftype {\n  flex: none; margin-left: 6px; padding: 0 7px; border: 1px solid currentColor; border-radius: 999px;\n  font: 700 10px/16px ui-monospace, Consolas, monospace; letter-spacing: .04em;\n}\n.sp-mv-ftype.is-video { color: #65c7da; background: rgba(101, 199, 218, .12); }\n.sp-mv-ftype.is-audio { color: #f0b35a; background: rgba(240, 179, 90, .12); }\n.sp-mv-stored .sp-mv-who .sp-mv-ftype { margin-right: 24px; }\n/* no roll: said in words, with the road */\n.rt-noroll { margin: 4px 0 2px; padding: 3px 8px; border-left: 3px solid #ef7b72; border-radius: 6px; background: rgba(239, 123, 114, .1); font-size: 12px; color: #f3c7c2; }\n.rt-table tr.rt-failed td { opacity: .5; filter: grayscale(1); }\n.rt-table tr.rt-rejrow td { background: transparent; padding-top: 0; border-left: 0 !important; }\n.rt-table tr.rt-rejrow b { margin-right: 6px; font-size: 10px; letter-spacing: .06em; text-transform: uppercase; color: #7d8a93; }\n.rt-rej { display: inline-block; margin: 0 4px 3px 0; padding: 0 6px; border: 1px solid #4a5560; border-radius: 6px; color: #7d8a93; text-decoration: line-through; filter: grayscale(1); cursor: help; font-size: 11px; }\n.rt-unrec { font-size: 11px; opacity: .8; margin-top: 4px; }\n/* a way into the reconstruction */\n.sp-rollway { cursor: pointer; }\n.sfxseen-strip.sp-rollway:hover, .sp-detail-text.sp-rollway:hover { outline: 1px solid rgba(101, 199, 218, .5); outline-offset: 2px; border-radius: 6px; }\n/* [rollplay] the Message view scrolls back freely; new arrivals are counted, never forced into view */\n.sp-mv { position: relative; }\n.sp-mv-stage.sp-mv-scroll {\n  overflow-x: hidden; overflow-y: auto; justify-content: flex-start; overscroll-behavior: contain;\n  touch-action: pan-y; -webkit-overflow-scrolling: touch; overflow-anchor: auto;\n}\n.sp-mv-stage.sp-mv-scroll > .sp-mv-item { flex: none; }\n.sp-mv-stage.sp-mv-scroll > .sp-mv-item:first-child { margin-top: auto; }\n.sp-mv-hist .sp-mv-rolls { display: none; }\n.sp-mv-newchip {\n  position: absolute; left: 50%; bottom: 12px; z-index: 6; transform: translateX(-50%);\n  display: inline-flex; align-items: center; gap: 6px; min-height: 30px; padding: 0 12px 0 14px;\n  border: 1px solid var(--sp-on, #65c7da); border-radius: 999px; background: #0b1117; color: var(--sp-on, #65c7da);\n  font: 700 12px Inter, "Segoe UI", system-ui, sans-serif; cursor: pointer; box-shadow: 0 6px 18px rgba(0, 0, 0, .5);\n}\n.sp-mv-newchip[hidden] { display: none; }\n.sp-mv-newchip .sp-mv-ico, .sp-mv-newchip svg { width: 14px; height: 14px; fill: currentColor; }\n/* the pin: viewfinder ticks at the corners, a slow glow - never a scale */\n.sp-mv-pinned .sp-mv-bubble { animation: spMvPulse 2s ease-in-out infinite; }\n@keyframes spMvPulse {\n  0%, 100% { box-shadow: 0 0 0 0 rgba(101, 199, 218, 0); }\n  50% { box-shadow: 0 0 8px 0 rgba(101, 199, 218, .25); }\n}\n.sp-mv-ticks { position: absolute; inset: -7px; pointer-events: none; animation: spMvTicks .15s ease-out both; }\n@keyframes spMvTicks { from { opacity: 0; transform: scale(1.08); } to { opacity: 1; transform: scale(1); } }\n.sp-mv-tick { position: absolute; width: 10px; height: 10px; border: 0 solid var(--sp-on, #65c7da); }\n.sp-mv-tick.tl { left: 0; top: 0; border-left-width: 2px; border-top-width: 2px; border-top-left-radius: 5px; }\n.sp-mv-tick.tr { right: 0; top: 0; border-right-width: 2px; border-top-width: 2px; border-top-right-radius: 5px; }\n.sp-mv-tick.bl { left: 0; bottom: 0; border-left-width: 2px; border-bottom-width: 2px; border-bottom-left-radius: 5px; }\n.sp-mv-tick.br { right: 0; bottom: 0; border-right-width: 2px; border-bottom-width: 2px; border-bottom-right-radius: 5px; }\n.sp-mv-result.sp-mv-pinning { border-color: var(--sp-on, #65c7da); color: var(--sp-on, #65c7da); background: rgba(101, 199, 218, .14); }\n@media (prefers-reduced-motion: reduce) {\n  .sp-mv-pinned .sp-mv-bubble { animation: none; box-shadow: 0 0 6px 0 rgba(101, 199, 218, .22); }\n  .sp-mv-ticks { animation: none; }\n}\n.sp-mv-stage.sp-mv-pinlist { overflow-anchor: none; }\n.sp-mv-frozen, .sp-mv-frozen * { animation-play-state: paused !important; }\n.rt-tag .sp-mv-all[hidden], .sp-mv-hist .sp-mv-all[hidden] { display: none; }\n')]


def status(text):
    out = []
    for name, anchor, new in EDITS:
        if new.rstrip('\n') in text:
            out.append((name, 'applied'))
        elif anchor is None:
            out.append((name, 'ready'))
        else:
            n = text.count(anchor)
            out.append((name, 'ready' if n == 1 else 'missing (anchor x%d)' % n))
    return out


def verify(path, text):
    if path.endswith('.json'):
        json.loads(text)
        return ''
    if path.endswith('.py'):
        try:
            compile(text, path, 'exec')
        except SyntaxError as err:
            return 'SyntaxError: %s (line %s)' % (err.msg, err.lineno)
        return ''
    if path.endswith('.js') and shutil.which('node'):
        fd, tmp = tempfile.mkstemp(suffix='.js')
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as fh:
            fh.write(text)
        try:
            got = subprocess.run(['node', '--check', tmp], capture_output=True, text=True)
            return '' if got.returncode == 0 else (got.stderr or got.stdout)[-800:]
        finally:
            os.unlink(tmp)
    return ''


def one(path, apply):
    raw = open(path, 'rb').read().decode('utf-8')
    crlf = raw.count('\r\n') > raw.count('\n') // 2
    text = raw.replace('\r\n', '\n')
    st = status(text)
    for name, s in st:
        print('  %-60s %s' % (name, s))
    if any(s.startswith('missing') for _, s in st):
        print('%s: ANCHOR MISSING' % path)
        return 1
    if all(s == 'applied' for _, s in st):
        print('%s: already applied' % path)
        return 2
    if not apply:
        print('%s: ready' % path)
        return 0
    for name, anchor, new in EDITS:
        if new.rstrip('\n') in text:
            continue
        if anchor is None:
            text = text.rstrip('\n') + '\n' + new if text else new
            if not text.endswith('\n'):
                text += '\n'
        else:
            assert text.count(anchor) == 1, name
            text = text.replace(anchor, new, 1)
    assert all(s == 'applied' for _, s in status(text)), 'an edit did not land'
    bad = verify(path, text)
    if bad:
        print('%s: REFUSED - the result does not parse:\n%s' % (path, bad))
        return 1
    if crlf:
        text = text.replace('\n', '\r\n')
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, suffix='.part')
    with os.fdopen(fd, 'wb') as fh:
        fh.write(text.encode('utf-8'))
    try:
        shutil.copymode(path, tmp)
    except OSError:
        pass
    os.replace(tmp, path)
    print('%s: APPLIED (%s)' % (path, 'CRLF' if crlf else 'LF'))
    return 0


def main(argv):
    apply = '--apply' in argv
    paths = [a for a in argv if not a.startswith('--')]
    if not paths:
        print(__doc__)
        return 1
    rcs = [one(p, apply) for p in paths]
    return 1 if 1 in rcs else (0 if 0 in rcs else 2)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
