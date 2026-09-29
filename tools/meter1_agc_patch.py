#!/usr/bin/env python3
"""[meter1-agc] Script-page music card, row 1 (the green bar): grow whenever
something plays; the operator's Music level is its ceiling.  Visual only -
no gain, no mix, no level is touched.

  --check   exit 0 = ready (anchors found, not applied)
            exit 2 = already applied (marker present)
            exit 1 = an anchor is missing / ambiguous
  --apply   applies to every copy that is ready, then exit 2 (idempotent;
            re-running on applied copies changes nothing), 1 on a missing anchor.
  --root    repo root (default: the share checkout)

Edits script-page.js in desktop/renderer AND the kiosk mirror
app/src/main/assets/pine-views.  CRLF-aware: inserted text takes the file's
own newline.  Each write re-reads the file and refuses if it changed since
the read (parallel sessions edit this file).
"""
import argparse
import hashlib
import sys
from pathlib import Path

MARK = '[meter1-agc]'
COPIES = ['desktop/renderer/script-page.js',
          'app/src/main/assets/pine-views/script-page.js']

# ---- edit 1: the helper, inserted before wirePlayer's doc comment ----------
A1 = "  /* THE PLAYHEAD IS A REAL SCRUB, and it moves THIS terminal's player.\n"
HELPER = r"""  /* [meter1-agc] begin - ROW 1 GROWS WHENEVER SOMETHING PLAYS; THE LEVEL IS
   * ITS CEILING.
   *
   * "Even though the audio level of the music is low, I still need it to
   *  increase vertically like number two below ... adjusting the volume
   *  level should continuously adjust the limits of how far it comes out on
   *  the Y axis ... The only time the bar should be thin and gone is if I
   *  lower the volume all the way to zero."
   *
   * The green bar drew PineMeters.read('musicPlayer', 'music'): the spectrum
   * multiplied by the gain applied AFTER the analyser (Music level x the duck
   * x the element volume). A record mixed under talking hosts is ducked, so
   * the bars were multiplied down to a 1.5 px dashed line while the music was
   * plainly audible. Visual only - nothing here touches a gain:
   *   - the signal is the RAW reading (the one [msgthumb] uses), shaped by an
   *     adaptive peak normaliser: a peak envelope (fast attack, ~3 s release)
   *     with a floor, so ordinary activity fills ~90% of the height and quiet
   *     but present audio still grows; under the gate it is silence and the
   *     row stays the thin line;
   *   - the CEILING is the operator's own control for this row: the Music
   *     level on the bus (this bar is its slider; the mixer dot moves the same
   *     number), clamped at 100%, times this terminal's HERE volume on the
   *     element. 100% may reach full height, 50% half, 0 is the thin line.
   *     The duck is deliberately NOT in it - that is the mix, not a hand;
   *   - each bar breathes: attack ~35 ms, release ~220 ms, time-based so the
   *     SCOPE_EVERY frame skip does not change the feel. Nothing here reads
   *     layout; it rides the card's existing rAF tick, which already stands
   *     still while the card is hidden.
   * Row 2 (the amber DJ voices) is untouched. */
  var M1_TARGET = 0.9;      /* ordinary activity fills this much of the height */
  var M1_FLOOR = 0.18;      /* the envelope never sinks below this (max gain 5x) */
  var M1_GATE = 0.035;      /* a raw peak under this is silence */
  var M1_ENV_UP = 0.06;     /* s - envelope attack */
  var M1_ENV_DOWN = 3.0;    /* s - envelope release */
  var M1_ATTACK = 0.035;    /* s - bar attack */
  var M1_RELEASE = 0.22;    /* s - bar release */
  var m1 = {env: M1_FLOOR, bars: null, at: 0};

  function meterOneCap() {
    var lv = levelNow('music');
    var cap = lv === null ? 1 : Math.max(0, Math.min(1, lv));
    try {
      var p = el('musicPlayer');
      var vol = p ? Number(p.volume) : 1;
      if (p) cap *= p.muted ? 0 : (isFinite(vol) ? Math.max(0, Math.min(1, vol)) : 1);
    } catch (err) { /* no player here: the level alone */ }
    return cap;
  }

  function meterOneShape(state, reading, cap, nowMs) {
    var raw = reading && reading.bars ? reading.bars : null;
    var n = raw ? raw.length : (state.bars ? state.bars.length : 64);
    var i;
    if (!state.bars || state.bars.length !== n) {
      state.bars = new Array(n);
      for (i = 0; i < n; i += 1) state.bars[i] = 0;
    }
    var dt = state.at ? Math.min(0.25, Math.max(0.001, (nowMs - state.at) / 1000)) : 0.033;
    state.at = nowMs;
    var peak = raw ? (Number(reading.peak) || 0) : 0;
    cap = Math.max(0, Math.min(1, Number(cap) || 0));
    var live = !!raw && peak >= M1_GATE && cap > 0;
    if (live) {
      state.env += (peak - state.env)
        * (1 - Math.exp(-dt / (peak > state.env ? M1_ENV_UP : M1_ENV_DOWN)));
    }
    if (!(state.env >= M1_FLOOR)) state.env = M1_FLOOR;
    var gain = M1_TARGET / state.env;
    var kA = 1 - Math.exp(-dt / M1_ATTACK);
    var kR = 1 - Math.exp(-dt / M1_RELEASE);
    var out = new Array(n);
    var top = 0;
    for (i = 0; i < n; i += 1) {
      var t = live ? Math.min(1, (Number(raw[i]) || 0) * gain) * cap : 0;
      var d = state.bars[i];
      d += (t - d) * (t > d ? kA : kR);
      if (d < 0.004) d = 0;
      state.bars[i] = d;
      out[i] = d;
      if (d > top) top = d;
    }
    return {bars: out, peak: top};
  }
  /* [meter1-agc] end */

"""

# ---- edit 2: row 1's draw call ---------------------------------------------
A2 = "        meters.draw(spectrum, liveRead || meters.read('musicPlayer', 'music'), '#54d18b');\n"
R2 = ("        meters.draw(spectrum, meterOneShape(m1,                      /* [meter1-agc] */\n"
      "          liveRead || meters.read('musicPlayer', 'raw'), meterOneCap(), nowMs), '#54d18b');\n")


def state_of(text):
    """'applied' | 'ready' | 'missing:<why>'"""
    if MARK in text:
        return 'applied'
    for name, a in (('helper anchor', A1), ('draw anchor', A2)):
        c = text.count(a)
        if c != 1:
            return 'missing:%s x%d' % (name, c)
    return 'ready'


def patch(text):
    text = text.replace(A1, HELPER + A1, 1)
    return text.replace(A2, R2, 1)


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--check', action='store_true')
    g.add_argument('--apply', action='store_true')
    ap.add_argument('--root', default=r'\\10.89.1.246\ehm_eckx\pinevoice-stack\spark-agent')
    args = ap.parse_args()
    root = Path(args.root)
    states = {}
    for rel in COPIES:
        p = root / rel
        if not p.exists():
            print('%s: MISSING FILE' % rel)
            return 1
        raw = p.read_bytes()
        crlf = b'\r\n' in raw
        text = raw.decode('utf-8').replace('\r\n', '\n')
        states[rel] = (p, raw, crlf, text, state_of(text))
        print('%s: %s%s' % (rel, states[rel][4], ' (CRLF)' if crlf else ''))
    if any(s[4].startswith('missing') for s in states.values()):
        return 1
    if args.check:
        return 2 if all(s[4] == 'applied' for s in states.values()) else 0
    for rel, (p, raw, crlf, text, st) in states.items():
        if st != 'ready':
            continue
        out = patch(text)
        if crlf:
            out = out.replace('\n', '\r\n')
        data = out.encode('utf-8')
        if hashlib.sha256(p.read_bytes()).digest() != hashlib.sha256(raw).digest():
            print('%s: CHANGED UNDER US - re-run' % rel)
            return 1
        p.write_bytes(data)
        print('%s: applied' % rel)
    return 2


if __name__ == '__main__':
    sys.exit(main())
