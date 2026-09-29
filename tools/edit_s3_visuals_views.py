"""[s3-visuals] The slideshow consumes the station's deal; ad-viewer shows the
hourly door's rolls. Marker-idempotent editor for BOTH surfaces of each view:

  desktop/renderer/slideshow.js  +  app/src/main/assets/pine-views/slideshow.js
  desktop/renderer/ad-viewer.js  +  app/src/main/assets/pine-views/ad-viewer.js

slideshow.js: the client stops seeding the server shuffle with Math.random
(seed: 0 asks the playlist door to roll the deal through System 3 - the dealt
seed comes back with the page and is kept for the mount), each advance's
transition is the one the station dealt onto the row (the tabled pool
slideshow.transition; an older station that dealt nothing gets a plain
rotation, never Math.random), and the shatter shards scatter off a tiny
seeded LCG instead of Math.random. After this edit the file contains NO
Math.random at all - the shuffle path's randomness lives on the station,
recorded and editable. Pacing, paging and every request are unchanged.

ad-viewer.js: usedWords() gains one item, 'Hourly rolls', shown only when the
row's h3_prompts record carries the door's rolls (rec.rolls) - the existing
summary line ("rolled by System 3: d100 ...") is untouched. The two copies
must stay byte-identical (tests/test_h3_prompt_presets.py pins that), so this
script applies the same text to both and refuses to fork them.

python3 tools/edit_s3_visuals_views.py --check | --apply  [repo root]
--check exits 0 ready / 2 applied / 1 anchors missing. Each copy keeps its
own line ending: LF stays LF, and a CRLF checkout (the host's kiosk copy of
slideshow.js was CRLF on disk at dc1763e, LF in the index) stays CRLF.
"""
import sys
from pathlib import Path

SLIDESHOW = ("desktop/renderer/slideshow.js", "app/src/main/assets/pine-views/slideshow.js")
ADVIEWER = ("desktop/renderer/ad-viewer.js", "app/src/main/assets/pine-views/ad-viewer.js")

SLIDESHOW_EDITS = [
    ("the-station-deals-the-seed",
     """      /* One seed for the life of this mount, like the desktop's single
       * random.Random - so page two of the playlist continues the same
       * deal rather than re-shuffling the deck. */
      seed: Math.floor(Math.random() * 1000000) + 1,
""",
     """      /* One seed for the life of this mount, like the desktop's single
       * random.Random - so page two of the playlist continues the same
       * deal rather than re-shuffling the deck. [s3-visuals] The station
       * deals it now: 0 asks the playlist door to roll the deal through
       * System 3 (slideshow.deal, recorded on its desk) and the dealt
       * seed rides the answer; this view keeps it for the mount. */
      seed: 0,
"""),
    ("the-dealt-seed-is-kept",
     """      }).then(function (body) {
        backoff = 0;
        S.items = (body && body.rows) || [];
""",
     """      }).then(function (body) {
        backoff = 0;
        if (body && body.seed) S.seed = body.seed;   /* [s3-visuals] the dealt seed, kept */
        S.items = (body && body.rows) || [];
"""),
    ("the-transition-is-the-dealt-one",
     """    function pick() {
      if (S.transition !== 'all') return S.transition;
      return CONCRETE[Math.floor(Math.random() * CONCRETE.length)];
    }
""",
     """    function pick(row) {
      if (S.transition !== 'all') return S.transition;
      /* [s3-visuals] the station deals each row the transition it enters
       * with (the tabled pool slideshow.transition, rolled with the
       * playlist); an older station that dealt nothing gets a plain
       * rotation - never this page's own dice. */
      if (row && row.transition && CONCRETE.indexOf(row.transition) >= 0) return row.transition;
      return CONCRETE[S.shown % CONCRETE.length];
    }
"""),
    ("a-step-picks-for-its-row",
     """      show(next, pick());
    }
""",
     """      show(next, pick(S.items[next]));
    }
"""),
    ("a-strip-tap-picks-for-its-row",
     """            show(index, pick());
""",
     """            show(index, pick(S.items[index]));
"""),
    ("the-shards-scatter-off-the-deal",
     """    /* SHATTER: eight real shards of the outgoing frame, each clipped and
     * thrown. Eight rather than the desktop's many, because every shard is
     * a composited layer and this is a MediaTek GPU. */
    function shatter(from, to, done) {
      var img = from.querySelector('img');
      if (!img) { to.style.display = 'block'; done(); return; }
      var shards = document.createDocumentFragment();
""",
     """    /* [s3-visuals] the shard scatter without the page's own dice: a
     * tiny 32-bit LCG walked from the dealt seed and the advance count -
     * cosmetic jitter, deterministic for the same deal, so no undealt
     * randomness is left anywhere in this view. */
    var jitterState = 1;
    function jitter() {
      jitterState = (Math.imul(jitterState, 1664525) + 1013904223) | 0;
      return ((jitterState >>> 8) & 0xffffff) / 0x1000000;
    }
    /* SHATTER: eight real shards of the outgoing frame, each clipped and
     * thrown. Eight rather than the desktop's many, because every shard is
     * a composited layer and this is a MediaTek GPU. */
    function shatter(from, to, done) {
      var img = from.querySelector('img');
      if (!img) { to.style.display = 'block'; done(); return; }
      jitterState = (((S.seed || 1) + S.shown * 8191 + 1) | 0);
      var shards = document.createDocumentFragment();
"""),
    ("a-shard-flies-off-the-deal-x",
     """        piece.style.setProperty('--sl-fly-x',
          ((x - 37) * (2 + Math.random() * 3)) + '%');
""",
     """        piece.style.setProperty('--sl-fly-x',
          ((x - 37) * (2 + jitter() * 3)) + '%');
"""),
    ("a-shard-flies-off-the-deal-y",
     """        piece.style.setProperty('--sl-fly-y',
          ((y - 25) * (2 + Math.random() * 3)) + '%');
""",
     """        piece.style.setProperty('--sl-fly-y',
          ((y - 25) * (2 + jitter() * 3)) + '%');
"""),
    ("a-shard-spins-off-the-deal",
     """        piece.style.setProperty('--sl-spin',
          (Math.random() * 120 - 60) + 'deg');
""",
     """        piece.style.setProperty('--sl-spin',
          (jitter() * 120 - 60) + 'deg');
"""),
]

ADVIEWER_EDITS = [
    ("the-door-rolls-have-words",
     """  function usedWords(row) {
""",
     """  function usedRolls(rolls) {
    /* [s3-visuals] the hourly door's own dice (h3.hourly_source / _fresh /
       _marker / _host), recorded with the hour and carried on the row's
       h3_prompts record - worded only when a roll was actually made
       (never fake dice; an empty record stays silent). */
    if (!rolls || typeof rolls !== 'object') return '';
    var bits = [];
    function one(name, rec) {
      if (!rec || typeof rec !== 'object' || rec.dice == null) return;
      if (rec.kind === 'chance') {
        bits.push(name + ': ' + (rec.hit ? 'yes' : 'no') + ' (d100 ' + rec.dice
          + ' against ' + Math.round((rec.odds || 0) * 100) + '%)');
      } else if (rec.index != null && rec.of != null) {
        bits.push(name + ': ' + String(rec.picked || rec.label || '') + ' (d100 ' + rec.dice
          + ', ' + rec.index + ' of ' + rec.of + ')');
      } else {
        bits.push(name + ': d100 ' + rec.dice);
      }
    }
    one('host', rolls.host); one('source', rolls.source);
    one('fresh pick', rolls.fresh); one('window marker', rolls.marker);
    return bits.join('  -  ');
  }
  function usedWords(row) {
"""),
    ("the-card-lists-the-door-rolls",
     """      add('Constraints', rec.constraints, 'constraints');
""",
     """      add('Constraints', rec.constraints, 'constraints');
      add('Hourly rolls', usedRolls(rec.rolls), 'rolls');   /* [s3-visuals] the door's dice, when they rolled */
"""),
]


def state_of(text, old, new):
    n_new, n_old = text.count(new), text.count(old)
    if n_new >= 1 and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and n_old == 1:
        return "ready"
    return "anchor found %d times, wanted 1; replacement found %d times" % (n_old, n_new)


def run(root, apply):
    root = Path(root)
    bad = []
    changed = 0
    for paths, edits in ((SLIDESHOW, SLIDESHOW_EDITS), (ADVIEWER, ADVIEWER_EDITS)):
        texts, crlf = {}, {}
        for rel in paths:
            path = root / rel
            if not path.exists():
                bad.append("%s is missing" % rel)
                continue
            raw = path.read_bytes()
            # A host checkout can hold one copy CRLF (text=auto normalises the
            # index, so git reads it clean): match on LF, write each copy back
            # in its OWN line ending. A mixed file is refused, never guessed.
            n_crlf = raw.count(b"\r\n")
            if n_crlf and n_crlf != raw.count(b"\n"):
                bad.append("%s mixes CRLF and LF lines - refusing" % rel)
                continue
            crlf[rel] = bool(n_crlf)
            texts[rel] = raw.decode("utf-8").replace("\r\n", "\n")
        if len(texts) != len(paths):
            continue
        first = texts[paths[0]]
        if any(texts[rel] != first for rel in paths[1:]):
            bad.append("%s and %s differ before the edit - refusing to fork them further" % paths)
            continue
        states = {name: state_of(first, old, new) for name, old, new in edits}
        missing = ["%s (%s)" % (n, s) for n, s in states.items() if s not in ("ready", "applied")]
        if missing:
            bad.extend("%s: %s" % (paths[0], m) for m in missing)
            continue
        if all(s == "applied" for s in states.values()):
            continue
        if not apply:
            changed += sum(1 for s in states.values() if s == "ready")
            continue
        text = first
        for name, old, new in edits:
            if state_of(text, old, new) == "ready":
                text = text.replace(old, new, 1)
                changed += 1
        for rel in paths:
            data = (text.replace("\n", "\r\n") if crlf[rel] else text).encode("utf-8")
            tmp = root / (rel + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(root / rel)
    if bad:
        for b in bad:
            print("missing:", b)
        return 1
    if not changed:
        print("already applied")
        return 2
    print("APPLIED %d edit(s) to both surfaces" % changed if apply else "ready (%d edit(s))" % changed)
    return 0


def main(argv):
    apply = "--apply" in argv
    root = next((a for a in argv if not a.startswith("--")), ".")
    return run(root, apply)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
