/* THE CAUSE GRAPH - one word, or one line, followed back to what made the
 * station say it.  [#1386]
 *
 * "I want to be able to follow them through a 3js interactive flowchart
 *  down to the initial system prompts and speakerbox seedings that caused
 *  the station to focus on and emphasize these words."
 *
 * THE DRAWING IS THE SHAPE, THE TEXT IS THE RECORD. The rule is
 * line-deep.js:66 and it is not decoration: the picture shows the ROAD,
 * every number under it is text, and the rail beside it lists EVERY node
 * including any the drawing declined to letter. If the canvas is missing
 * the rail alone is the whole feature and nothing is lost but the shape.
 *
 * IT IS A FLOWCHART AND IT HOLDS STILL. See [#1387] below the palette for
 * why the spheres went. There is no OrbitControls anywhere in this repo
 * and this is still not the file that adds one.
 *
 * THREE HONESTY GRADES, carried on every edge by the server:
 *   measured  the round's own paperwork says so.
 *   written   the word is in that store, but nothing proves this round
 *             read it. Drawn dimmer.
 *   absent    the road is KNOWN not to record - a re-fired gold bar has no
 *             speakbox seed at all. Drawn as a stub with a grey cap, and
 *             the reason is printed. A panel that invents a contribution
 *             is worse than one that admits a gap (line-deep.js:58).
 *
 * EVERY FRAME READS A FRESH Date.now(). The tablet's WebView tops out at
 * 12fps and suspends timers while rAF keeps firing, so anything that
 * counted frames or leaned on setInterval would drift or freeze there.
 */
const SEATS = {
  dj: '#65c7da', cohost: '#54d18b', host: '#4fb0a6', third: '#b98cf0',
  caller: '#e3be63', caller2: '#ef8f5e', board: '#8fa0ad', drop: '#e06c9f',
  manager: '#e05c5c',
};
/* [#1387] The kind stripe. Restrained on purpose: on a near-black sheet a
   saturated fill reads as an alarm, so these are the muted end of the same
   hues and they appear only as a 3px key down the left face of a box. */
const KIND = {
  word: '#ff5f1f', utterance: '#6fb3c4', block: '#7fb98a', doc: '#d2a44f',
  gold: '#c4757f', prompts: '#9b86c4', crystal: '#6fa8c4',
  topics: '#b89bc4', scripts: '#8a857d', modifier: '#6fb5a8',
  swath: '#d2a44f', scenario: '#9b86c4', clip: '#d2a44f',
  code: '#8a857d', kin: '#8a857d',
};
/* [#1387] MORE THAN ONE WAY TO READ IT.
 *
 * "i want to have multiple ways of seeing this flowchart display where
 *  everything is connected and shown in a flowing path with interjections
 *  and tinting and all the elements shown in variable linear fashions."
 *
 * The same nodes and the same wires, ranked three ways, because the three
 * questions people actually ask of this drawing are different shapes:
 *
 *   flow    columns by DISTANCE FROM THE SUBJECT, walking the wires. The
 *           default, because it is the followable one: column 0 is the
 *           line, column 1 is what made it, column 2 is what made THAT.
 *   bands   columns by KIND, so every document stands with the documents.
 *           Best for "what sorts of thing are behind this".
 *   stack   one column, top to bottom. The linear reading, and the one
 *           that fits a narrow pane on the tablet without any panning.
 *
 * Nothing here decides what a node MEANS; it only decides where it sits.
 */
const LAYOUTS = ['flow', 'bands', 'stack'];

function colourOf(node) {
  if (node.who && SEATS[node.who]) return SEATS[node.who];
  return KIND[node.type] || '#9fb0bd';
}

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = String(text);
  return n;
}

export function openWordCause(opts) {
  const request = opts.request;
  const onClose = opts.onClose || function () {};
  const host = opts.host || document.body;
  const threeUrl = opts.threeUrl || '/vendor/three.min.js';

  let raf = null;
  let dead = false;
  /* [#1386] PHOTOSHOP CONTROLS, the house rule for every editor here:
     wheel-zoom at the pointer, drag to pan, pinch on glass, 0 to fit.
     The camera still DRIFTS rather than orbits - there is no OrbitControls
     in this repo and this is not the file that adds one - so `view` is a
     dolly and a pan, never a tumble. */
  /* A flat pan and a dolly, in world units. `s` is pixels per world unit;
     there is no tumble and no third axis, because a flowchart has none. */
  const view = {s: 1, x: 0, y: 0, want: null, at: 0};
  let layout = String(opts.layout || 'flow');
  let data = null;
  let picked = null;
  /* id -> the number printed on its box, so the rail can carry the same
     one and the drawing and the record read as one document. */
  let numbers = new Map();
  /* [#1387] NARROWING. "offer filter options for narrowing down the amount
     of items being shown and of what type."
     Two knobs, because there are two ways an answer is too big: too many
     KINDS of thing, and too many of one kind. `off` holds the kinds turned
     down; `needle` narrows what is left by its words. Both are drawing
     controls and neither re-asks the station - the answer has not changed,
     only how much of it is on the glass. The subject itself is never
     filtered away, because a drawing with no subject answers nothing. */
  const off = new Set();
  let needle = '';

  /* [#1386] EMBEDDED OR FLOATING.
   *
   * "I want to be able to toggle feed view between being feed view and
   *  technical view which is what it jumps into when i select any element
   *  in the script view."
   *
   * The same renderer, the same gestures and the same editing either way -
   * only the frame changes. Embedded it fills whatever pane it is handed
   * and grows no chrome of its own, because the pane already has a heading
   * and a toggle above it. */
  const embed = !!opts.embed;
  const root = el('div', embed ? 'wc-dialog wc-embed' : 'wc-dialog');
  root.innerHTML = '';
  const bar = el('div', 'wc-bar');
  const field = document.createElement('input');
  field.className = 'wc-field';
  field.placeholder = 'a word said on air, or tap a line in the script';
  field.value = String(opts.word || '');
  const go = el('button', 'wc-go', 'follow it back');
  const shut = el('button', 'wc-shut', '✕');
  shut.title = 'close';
  /* The reading, chosen on the bar. It re-places the same nodes rather
     than re-asking the station: the answer has not changed, only the
     question being put to it. */
  const lay = document.createElement('select');
  lay.className = 'wc-lay';
  LAYOUTS.forEach((name) => {
    const o = document.createElement('option');
    o.value = name;
    o.textContent = name;
    lay.appendChild(o);
  });
  lay.value = layout;
  lay.title = 'flow: columns by how far each cause stands from the subject. '
    + 'bands: columns by kind. stack: one column, top to bottom.';
  lay.onchange = () => { layout = lay.value; build(); fit(); };

  /* [#1387] THE WHOLE GLASS. "allow me to open a full screen version of
     the technical tab through the 3js window."
     The station already has a full-screen host for this - the PINE_3JS
     entry `wordcause`, which brings the pop-up frame, the tablet chooser
     and the gallery with it. So this does not build a second full-screen
     mode; it hands the SUBJECT to the one that exists. The host says how
     (onFull), because only the host knows whether it is the panel itself,
     a webview inside a shell, or a tab that has to be opened. */
  const fullBtn = el('button', 'wc-go', 'full');
  fullBtn.title = 'Open this trace full screen in the 3JS window';
  fullBtn.onclick = () => {
    const want = {line: lastLine, word: field.value, said: lastSaid};
    if (typeof opts.onFull === 'function') {
      try { opts.onFull(want); return; } catch (err) { /* fall through */ }
    }
    /* No host answer: the panel's own road, which reads ?view= on load. */
    const q = '/?view=wordcause'
      + (want.line ? '&wc=' + encodeURIComponent(want.line) : '')
      + (!want.line && want.word ? '&wcq=' + encodeURIComponent(want.word) : '');
    try { window.open(base + q, '_blank'); } catch (err) { /* blocked */ }
  };

  const fitBtn = el('button', 'wc-go', 'fit');
  fitBtn.title = 'Frame the whole graph again (or press 0)';
  fitBtn.onclick = () => fit();
  bar.appendChild(field);
  bar.appendChild(go);
  bar.appendChild(lay);
  bar.appendChild(fitBtn);
  if (embed) bar.appendChild(fullBtn);
  bar.appendChild(shut);
  root.appendChild(bar);

  /* The strip of kinds, rebuilt from whatever came back - the station
     decides what kinds exist, not a list in this file that would go stale
     the day a new sort of cause is recorded. */
  const strip = el('div', 'wc-strip');
  root.appendChild(strip);

  function paintStrip() {
    strip.textContent = '';
    if (!data || !(data.nodes || []).length) { strip.style.display = 'none'; return; }
    strip.style.display = '';
    const tally = new Map();
    (data.nodes || []).forEach((n) => {
      tally.set(n.type, (tally.get(n.type) || 0) + 1);
    });
    const kinds = [...tally.keys()].sort();
    const shown = kept().length;
    strip.appendChild(el('span', 'wc-strip-head',
      shown + ' of ' + (data.nodes || []).length));
    kinds.forEach((kind) => {
      const chip = el('button', 'wc-chip' + (off.has(kind) ? ' wc-chip-off' : ''),
        '');
      const dot = el('i', 'wc-chip-dot');
      dot.style.background = KIND[kind] || '#8a857d';
      chip.appendChild(dot);
      chip.appendChild(el('span', '', String(kind)));
      chip.appendChild(el('b', '', String(tally.get(kind))));
      chip.title = off.has(kind) ? 'show ' + kind + ' again' : 'hide ' + kind;
      chip.onclick = () => {
        if (off.has(kind)) off.delete(kind); else off.add(kind);
        fitted = false;
        build();
        paintRail();
      };
      strip.appendChild(chip);
    });
    if (off.size) {
      const all = el('button', 'wc-chip wc-chip-all', 'show all');
      all.onclick = () => { off.clear(); fitted = false; build(); paintRail(); };
      strip.appendChild(all);
    }
    const nar = document.createElement('input');
    nar.className = 'wc-narrow';
    nar.placeholder = 'narrow by word\u2026';
    nar.value = needle;
    nar.oninput = () => {
      needle = nar.value.trim().toLowerCase();
      fitted = false;
      build();
      paintRail();
      /* Repainting the rail rebuilds this strip, and a rebuilt input has
         lost the caret. Put it back where the typing was. */
      const live = strip.querySelector('.wc-narrow');
      if (live && live !== document.activeElement) {
        live.focus();
        try { live.setSelectionRange(needle.length, needle.length); }
        catch (err) { /* not a text input on this build */ }
      }
    };
    strip.appendChild(nar);
  }

  /* The nodes actually on the glass. The subject survives every filter. */
  function kept() {
    const all = (data && data.nodes) || [];
    if (!off.size && !needle) return all;
    const rootId = (all.find((n) => n.id === 'line')
      || all.find((n) => n.type === 'word') || all[0] || {}).id;
    return all.filter((n) => {
      if (n.id === rootId) return true;
      if (off.has(n.type)) return false;
      if (!needle) return true;
      return (String(n.label || '') + ' ' + String(n.type || '') + ' '
        + String(n.snippet || '') + ' ' + String(n.store || ''))
        .toLowerCase().indexOf(needle) >= 0;
    });
  }

  const split = el('div', 'wc-split');
  const stage = el('div', 'wc-stage');
  const grip = el('div', 'wc-grip');
  const rail = el('div', 'wc-rail');
  grip.title = 'Drag to give the record more room, or less';
  split.appendChild(stage);
  split.appendChild(grip);
  split.appendChild(rail);
  root.appendChild(split);
  host.appendChild(root);

  /* [#1387] THE DIVIDER IS HIS. "make sure that the sidebar has elements
     formatted properly ... there's ample room and they're able to fit
     properly in nice and adequate tables."
     A stylesheet can pick a good width; it cannot know that THIS trace is
     six system prompts and needs half the glass while the next one is
     four documents and does not. So the split is draggable, it remembers
     where it was left, and the drawing re-fits itself into whatever is
     left rather than being cropped. */
  (function dragGrip() {
    let from = 0;
    let was = 0;
    let wide = 0;
    try {
      wide = parseInt(localStorage.getItem('wc.rail') || '0', 10) || 0;
    } catch (err) { wide = 0; }
    if (wide >= 260) rail.style.flexBasis = wide + 'px';

    const move = (ev) => {
      /* The rail grows as the pointer goes LEFT, which is the direction
         the edge itself is moving. */
      const want = Math.max(260, Math.min(
        Math.max(320, split.clientWidth - 280), was + (from - ev.clientX)));
      rail.style.flexBasis = want + 'px';
      resize();
    };
    const stop = (ev) => {
      try { grip.releasePointerCapture(ev.pointerId); } catch (err) { /* gone */ }
      grip.removeEventListener('pointermove', move);
      grip.removeEventListener('pointerup', stop);
      grip.removeEventListener('pointercancel', stop);
      try { localStorage.setItem('wc.rail', String(rail.clientWidth)); }
      catch (err) { /* a private window, and nothing is lost but the memory */ }
      resize();
    };
    grip.addEventListener('pointerdown', (ev) => {
      ev.preventDefault();
      from = ev.clientX;
      was = rail.clientWidth;
      try { grip.setPointerCapture(ev.pointerId); } catch (err) { /* older */ }
      grip.addEventListener('pointermove', move);
      grip.addEventListener('pointerup', stop);
      grip.addEventListener('pointercancel', stop);
    });
    /* Double tap the divider to put it back where it started. */
    grip.addEventListener('dblclick', () => {
      rail.style.flexBasis = '';
      try { localStorage.removeItem('wc.rail'); } catch (err) { /* fine */ }
      resize();
    });
  }());

  shut.onclick = () => close();
  go.onclick = () => load(field.value);
  field.onkeydown = (e) => { if (e.key === 'Enter') load(field.value); };

  /* ------------------------------------------------- [#1387] THE DRAWING
   *
   * "the technical view is chaotic with alot of overlap and the nodes are
   *  hard to read. I want something made in a followable fashion that shows
   *  the rationale layed out in a detailed fashion like the references."
   *  "a streamlined, teenage engineering inspired technical look showing
   *  the paths and datastreams in a concise and understandable way."
   *
   * The references he sent are all the same thing, and it is not a point
   * cloud: BOXES WITH WORDS IN THEM, joined by RIGHT-ANGLED LINES that are
   * themselves labelled. That is a flowchart, and a flowchart is flat. The
   * old renderer put spheres in perspective space, which meant a label was
   * legible only when the drift happened to swing it forward, two causes at
   * different depths sat on top of each other, and nothing carried the WHY
   * along the wire. Three faults, one cause: the wrong medium.
   *
   * So the picture is a 2D canvas, and the rules are:
   *
   *   NO OVERLAP BY CONSTRUCTION. Nodes are ranked into columns by how far
   *   they stand from the subject and stacked inside their column at a
   *   fixed pitch. Two boxes cannot collide, because nothing ever chooses a
   *   free position - the layout is a table, not a simulation.
   *
   *   EVERY WIRE IS A PATH YOU CAN FOLLOW. Out of the right face, along its
   *   own vertical lane, into the left face, with an arrow. Lanes are
   *   handed out per column, so two runs never sit on one another.
   *
   *   THE WIRE CARRIES THE REASON. The relation rides the horizontal run,
   *   and the paperwork sentence - "49% - rolled 0.31 -> yes" - appears on
   *   the wires of the selected node. The rationale is ON the drawing,
   *   which is the thing the references do that the spheres did not.
   *
   *   EVERY BOX IS NUMBERED, and the same number stands against the same
   *   row in the rail. The picture and the record are one document read two
   *   ways, so "which of these is that one" is never a question.
   *
   * IT DOES NOT MOVE. The old file's own comment said "a diagram that spins
   * is a diagram you cannot read" and then drifted the camera anyway. A
   * flowchart holds still: it is redrawn when something changes and while
   * an ease is running, and at no other time. That also retires the
   * tablet's 12fps ceiling - there is no steady frame left to miss.
   */

  /* Teenage Engineering: near-black, one hot accent, everything else in
     greyscale, and colour used as a small coded stripe rather than as a
     surface. Nothing here is a gradient and nothing here glows. */
  const INK = {
    back: '#0e0e0d', grid: '#1a1a18',
    boxFill: '#161614', boxLine: '#34332f',
    text: '#ece8e0', dim: '#8a857c', faint: '#57534c',
    hot: '#ff5f1f',
    measured: '#d6d1c7', written: '#6a655d', absent: '#464239',
  };
  const MONO = 'ui-monospace, SFMono-Regular, Menlo, monospace';
  const BOX_W = 186;
  const COL_GAP = 104;   /* the routing channel lives in here */
  const ROW_GAP = 15;
  const PAD = 60;

  /* [#1387] MEDIA IN THE DRAWING.
   *
   * "Whenever videos and images are involved, I want to see their
   *  thumbnails and infographics in this flowchart view being referenced.
   *  And I want to be able to tap on them in order to have them play or be
   *  able to tap and hold on them in order to bring up a pop up where I can
   *  choose to save them or delete them or export them to the sampler."
   *
   * A clip node carries `media` - the sid, the kind, a SIGNED play road and
   * a SIGNED picture road. The picture is a frame for a video and a
   * spectrogram for audio, which is the infographic for a thing that has no
   * picture of its own; the station decides which, because only it knows
   * whether the clip is a video, and it hands over the one that will
   * answer. Neither route is ever asked a question it cannot answer.
   *
   * The pictures load LAZILY and off the draw path: a box with no picture
   * yet draws its frame and its words and simply has nothing in the window,
   * and the one image load that arrives repaints. Nothing blocks, nothing
   * is fetched twice, and a picture that 404s is remembered as missing so
   * it is not asked for again on every pan.
   */
  const base = String(opts.base || '');
  const pics = new Map();          /* url -> {img, ok, bad} */

  function picFor(url) {
    if (!url) return null;
    const full = /^https?:/.test(url) ? url : base + url;
    const held = pics.get(full);
    if (held) return held.ok ? held.img : null;
    const img = new Image();
    const row = {img: img, ok: false, bad: false};
    pics.set(full, row);
    img.onload = () => { row.ok = true; draw(); };
    img.onerror = () => { row.bad = true; };
    img.src = full;
    return null;
  }

  const canvas = document.createElement('canvas');
  canvas.className = 'wc-canvas';
  let ctx = null;
  let laid = null;      /* the table, in world units */
  let hot = null;       /* the id under the pointer */
  let fitted = false;

  /* ------------------------------------------------------------ measuring */
  function wrap(text, maxW, maxLines, font) {
    ctx.font = font;
    const whole = String(text || '');
    const words = whole.split(/\s+/).filter(Boolean);
    const lines = [];
    let at = '';
    for (const w of words) {
      const next = at ? at + ' ' + w : w;
      if (ctx.measureText(next).width <= maxW) { at = next; continue; }
      if (at) lines.push(at);
      at = w;
      if (lines.length >= maxLines) break;
    }
    if (at && lines.length < maxLines) lines.push(at);
    if (!lines.length) return [''];
    if (lines.length >= maxLines) {
      /* The last line says there is more rather than pretending there is
         not - the rail carries the whole of it either way. */
      let tail = lines[maxLines - 1];
      const shown = lines.slice(0, maxLines).join(' ').length;
      if (shown < whole.length) {
        while (tail.length > 3
               && ctx.measureText(tail + '…').width > maxW) {
          tail = tail.slice(0, -1);
        }
        tail += '…';
      }
      lines[maxLines - 1] = tail;
    }
    return lines.slice(0, maxLines);
  }

  /* ------------------------------------------------------------- the table */
  /* How far each node stands from the subject, walking the wires forward.
     A node nothing reaches is not hidden and not guessed at - it is put in
     a column of its own past the end, which is the truth about it. */
  function ranksOf(nodes, edges) {
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const out = new Map();
    edges.forEach((e) => {
      if (!out.has(e.from)) out.set(e.from, []);
      out.get(e.from).push(e.to);
    });
    let root = nodes.find((n) => n.id === 'line')
      || nodes.find((n) => n.type === 'word');
    if (!root) {
      root = nodes.slice()
        .sort((a, b) => (Number(b.n) || 0) - (Number(a.n) || 0))[0];
    }
    const rank = new Map();
    if (root) {
      rank.set(root.id, 0);
      let edge = [root.id];
      let guard = 0;
      while (edge.length && guard < 40) {
        guard += 1;
        const next = [];
        edge.forEach((id) => {
          (out.get(id) || []).forEach((to) => {
            if (!byId.has(to)) return;
            const want = (rank.get(id) || 0) + 1;
            if (rank.has(to) && rank.get(to) >= want) return;
            rank.set(to, want);
            next.push(to);
          });
        });
        edge = next;
      }
    }
    let deepest = 0;
    rank.forEach((v) => { if (v > deepest) deepest = v; });
    nodes.forEach((n) => { if (!rank.has(n.id)) rank.set(n.id, deepest + 1); });
    return {rank, rootId: root ? root.id : null};
  }

  const BAND_ORDER = ['word', 'utterance', 'block', 'scenario', 'prompts',
    'doc', 'swath', 'modifier', 'crystal', 'topics', 'gold', 'scripts',
    'code', 'kin'];

  function build() {
    if (!ctx || !data) { laid = null; draw(); return; }
    const nodes = kept().slice();
    const live = new Set(nodes.map((n) => n.id));
    /* An edge to a node that is not on the glass is a wire to nowhere. */
    const edges = (data.edges || []).filter(
      (e) => live.has(e.from) && live.has(e.to));
    const {rank, rootId} = ranksOf(nodes, edges);

    const colOf = (n) => {
      if (layout === 'bands') {
        const at = BAND_ORDER.indexOf(n.type);
        return at < 0 ? BAND_ORDER.length : at;
      }
      if (layout === 'stack') return 0;
      return rank.get(n.id) || 0;
    };

    /* Size every box first: a box is as tall as its own words and no
       taller. The subject gets three lines because it is usually a whole
       spoken line; everything else gets two. */
    const boxes = new Map();
    nodes.forEach((n) => {
      const isRoot = n.id === rootId;
      const body = wrap(n.label || n.type, BOX_W - 26, isRoot ? 3 : 2,
                        '12px ' + MONO);
      /* A clip gets a window at the top of its box for its own picture.
         16:9, because that is what a grabbed frame is, and a spectrogram
         reads fine in any rectangle. */
      const shot = (n.media && n.media.thumb) ? Math.round(BOX_W * 0.48) : 0;
      boxes.set(n.id, {
        node: n, lines: body, w: BOX_W, h: 32 + body.length * 15 + shot,
        shot: shot, col: colOf(n), root: isRoot, x: 0, y: 0, num: 0,
      });
    });

    /* Stack each column. Inside a column the order is the subject, then
       the heaviest, then the rest - so the eye lands on the thing that
       mattered most without hunting for it. */
    const cols = new Map();
    boxes.forEach((b) => {
      if (!cols.has(b.col)) cols.set(b.col, []);
      cols.get(b.col).push(b);
    });
    const colKeys = [...cols.keys()].sort((a, b) => a - b);
    let x = PAD;
    let tallest = 0;
    const colX = new Map();
    colKeys.forEach((k) => {
      const list = cols.get(k);
      list.sort((a, b) => (b.root ? 1 : 0) - (a.root ? 1 : 0)
        || (Number(b.node.n) || 0) - (Number(a.node.n) || 0)
        || String(a.node.label || '').localeCompare(String(b.node.label || '')));
      let h = -ROW_GAP;
      list.forEach((b) => { h += b.h + ROW_GAP; });
      if (h > tallest) tallest = h;
      colX.set(k, x);
      x += BOX_W + COL_GAP;
    });
    colKeys.forEach((k) => {
      const list = cols.get(k);
      let h = -ROW_GAP;
      list.forEach((b) => { h += b.h + ROW_GAP; });
      let y = (tallest - h) / 2 + PAD;
      list.forEach((b) => {
        b.x = colX.get(k);
        b.y = y;
        y += b.h + ROW_GAP;
      });
    });

    /* The numbers. Reading order is left to right, top to bottom - the
       order a person's eye actually takes the picture in, so 07 always
       stands below and to the right of 03. The rail numbers from the
       same walk, which is what joins the drawing to the record. */
    const order = [...boxes.values()].sort((a, b) => a.col - b.col || a.y - b.y);
    order.forEach((b, i) => { b.num = i + 1; });
    numbers = new Map(order.map((b) => [b.node.id, b.num]));

    /* The wires. Each gets its own vertical lane in the channel to the
       right of its source column, so two runs never share a line. */
    const lanes = new Map();
    const links = [];
    edges.forEach((e) => {
      const a = boxes.get(e.from);
      const b = boxes.get(e.to);
      if (!a || !b) return;
      const lane = lanes.get(a.col) || 0;
      lanes.set(a.col, lane + 1);
      links.push({e, a, b, lane});
    });

    laid = {boxes, links, rootId, w: x - COL_GAP + PAD, h: tallest + PAD * 2};
    if (!fitted) { fitted = true; fitNow(); }
    draw();
  }

  /* ------------------------------------------------------------- the paint */
  function dpr() { return Math.min(2, window.devicePixelRatio || 1); }
  function cw() { return canvas.width / dpr(); }
  function ch() { return canvas.height / dpr(); }
  function toScreen(wx, wy) {
    return [(wx - view.x) * view.s + cw() / 2, (wy - view.y) * view.s + ch() / 2];
  }

  /* Everything upstream and downstream of one node - the road it is on.
     Selecting dims everything off it, which is the point of a diagram you
     are using to decide something. */
  function pathOf(id) {
    if (!id || !laid) return null;
    const on = new Set([id]);
    const live = new Set([...laid.boxes.keys()]);
    const edges = ((data && data.edges) || []).filter(
      (e) => live.has(e.from) && live.has(e.to));
    let grew = true;
    let guard = 0;
    while (grew && guard < 40) {
      grew = false; guard += 1;
      edges.forEach((e) => {
        if (on.has(e.from) && !on.has(e.to)) { on.add(e.to); grew = true; }
        if (on.has(e.to) && !on.has(e.from)) { on.add(e.from); grew = true; }
      });
    }
    return on;
  }

  function draw() {
    if (!ctx) return;
    const W = cw();
    const H = ch();
    ctx.setTransform(dpr(), 0, 0, dpr(), 0, 0);
    ctx.fillStyle = INK.back;
    ctx.fillRect(0, 0, W, H);
    if (!laid) {
      ctx.fillStyle = INK.dim;
      ctx.font = '12px ' + MONO;
      ctx.fillText('nothing traced yet — tap a name in the script, or '
        + 'type a word above', 22, 34);
      return;
    }

    /* The grid. A technical drawing sits on paper that shows its own
       scale, and it tells you instantly whether a pan did anything. */
    const step = 26 * view.s;
    if (step > 9) {
      ctx.fillStyle = INK.grid;
      const ox = ((-view.x * view.s + W / 2) % step + step) % step;
      const oy = ((-view.y * view.s + H / 2) % step + step) % step;
      for (let gx = ox; gx < W; gx += step) {
        for (let gy = oy; gy < H; gy += step) ctx.fillRect(gx, gy, 1, 1);
      }
    }

    const lit = picked ? pathOf(picked.id) : null;
    const detail = view.s > 0.52;

    /* ------------------------------------------------------------ wires */
    laid.links.forEach((L) => {
      const on = !lit || (lit.has(L.e.from) && lit.has(L.e.to));
      const grade = L.e.grade || 'measured';
      const [ax, ay] = toScreen(L.a.x + L.a.w, L.a.y + L.a.h / 2);
      const [bx, by] = toScreen(L.b.x, L.b.y + L.b.h / 2);
      const back = L.b.col <= L.a.col;
      let mid = ax + (18 + (L.lane % 9) * 6) * view.s;
      if (!back && mid > bx - 14 * view.s) mid = (ax + bx) / 2;

      ctx.save();
      ctx.globalAlpha = on ? 1 : 0.16;
      ctx.strokeStyle = grade === 'absent' ? INK.absent
        : grade === 'written' ? INK.written : INK.measured;
      ctx.lineWidth = grade === 'measured' ? 1.4 : 1.1;

      if (grade === 'absent') {
        /* A road KNOWN not to record stops short, with a cap. It never
           reaches the box, because it never reached it in life. */
        ctx.setLineDash([3, 3]);
        const stop = ax + (bx - ax) * 0.34;
        ctx.beginPath();
        ctx.moveTo(ax, ay);
        ctx.lineTo(stop, ay);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = INK.absent;
        ctx.fillRect(stop - 3, ay - 3, 6, 6);
        ctx.restore();
        return;
      }

      ctx.beginPath();
      if (back) {
        const low = Math.max(ay, by)
          + (Math.max(L.a.h, L.b.h) / 2 + 12) * view.s;
        ctx.moveTo(ax, ay);
        ctx.lineTo(ax + 14 * view.s, ay);
        ctx.lineTo(ax + 14 * view.s, low);
        ctx.lineTo(bx - 14 * view.s, low);
        ctx.lineTo(bx - 14 * view.s, by);
        ctx.lineTo(bx, by);
      } else {
        ctx.moveTo(ax, ay);
        ctx.lineTo(mid, ay);
        ctx.lineTo(mid, by);
        ctx.lineTo(bx, by);
      }
      ctx.stroke();

      ctx.fillStyle = ctx.strokeStyle;
      ctx.beginPath();
      ctx.moveTo(bx, by);
      ctx.lineTo(bx - 6, by - 3.4);
      ctx.lineTo(bx - 6, by + 3.4);
      ctx.closePath();
      ctx.fill();

      /* The reason, on the wire. The relation always; the paperwork
         sentence when this wire is one of the selected node's, because
         six sentences at once is the chaos being got rid of. */
      if (detail && on) {
        const deep = !!lit && !!L.e.say;
        const text = deep ? (L.e.rel + ' · ' + L.e.say)
          : String(L.e.rel || '');
        if (text) {
          ctx.font = '9.5px ' + MONO;
          const cap = deep ? 54 : 22;
          const t = text.length > cap ? text.slice(0, cap - 1) + '…' : text;
          const tw = ctx.measureText(t).width;
          const lx = back ? (ax + bx) / 2 - tw / 2
            : Math.min(mid + 6, bx - tw - 10);
          const ly = back ? Math.max(ay, by) + 22 * view.s : by - 5;
          ctx.fillStyle = INK.back;
          ctx.fillRect(lx - 3, ly - 9, tw + 6, 12);
          ctx.fillStyle = grade === 'written' ? INK.faint : INK.dim;
          ctx.fillText(t, lx, ly);
        }
      }
      ctx.restore();
    });

    /* ------------------------------------------------------------ boxes */
    laid.boxes.forEach((b) => {
      const on = !lit || lit.has(b.node.id);
      const sel = picked && picked.id === b.node.id;
      const [sx, sy] = toScreen(b.x, b.y);
      const w = b.w * view.s;
      const h = b.h * view.s;
      if (sx > W + 40 || sy > H + 40 || sx + w < -40 || sy + h < -40) return;
      ctx.save();
      ctx.globalAlpha = on ? 1 : 0.2;

      ctx.fillStyle = INK.boxFill;
      ctx.fillRect(sx, sy, w, h);
      ctx.lineWidth = sel ? 2 : 1;
      ctx.strokeStyle = sel ? INK.hot
        : (hot === b.node.id ? INK.dim : INK.boxLine);
      ctx.strokeRect(sx + 0.5, sy + 0.5, w - 1, h - 1);
      /* The coded stripe. Colour is a KEY here, never a surface. */
      ctx.fillStyle = colourOf(b.node);
      ctx.fillRect(sx, sy, Math.max(2, 3 * view.s), h);

      /* The picture, in the window at the top. It is drawn UNDER the
         number and the words, cropped to fill rather than letterboxed,
         because a black bar on a near-black sheet reads as a fault. */
      if (b.shot) {
        const win = {x: sx + 1, y: sy + 1, w: w - 2, h: b.shot * view.s};
        ctx.save();
        ctx.beginPath();
        ctx.rect(win.x, win.y, win.w, win.h);
        ctx.clip();
        ctx.fillStyle = '#0a0a09';
        ctx.fillRect(win.x, win.y, win.w, win.h);
        const pic = picFor(b.node.media.thumb);
        if (pic && pic.naturalWidth) {
          const k = Math.max(win.w / pic.naturalWidth, win.h / pic.naturalHeight);
          const dw = pic.naturalWidth * k;
          const dh = pic.naturalHeight * k;
          ctx.drawImage(pic, win.x + (win.w - dw) / 2,
                        win.y + (win.h - dh) / 2, dw, dh);
        } else {
          ctx.fillStyle = INK.faint;
          ctx.font = '9px ' + MONO;
          const word = b.node.media.thumb_kind === 'spectrogram'
            ? 'SPECTROGRAM' : 'FRAME';
          ctx.fillText(word, win.x + 8, win.y + win.h / 2 + 3);
        }
        ctx.restore();
        /* The play mark, and the kind, so a video is told from a sound
           without opening anything. */
        if (detail) {
          const cx2 = win.x + win.w - 16 * view.s;
          const cy2 = win.y + win.h - 14 * view.s;
          ctx.fillStyle = 'rgba(14,14,13,.72)';
          ctx.fillRect(win.x, win.y + win.h - 15 * view.s, win.w,
                       15 * view.s);
          ctx.fillStyle = INK.hot;
          ctx.beginPath();
          ctx.moveTo(cx2, cy2 - 4);
          ctx.lineTo(cx2 + 7, cy2);
          ctx.lineTo(cx2, cy2 + 4);
          ctx.closePath();
          ctx.fill();
          ctx.font = '8.5px ' + MONO;
          ctx.fillStyle = INK.dim;
          const secs = Number(b.node.media.seconds) || 0;
          ctx.fillText(String(b.node.media.kind || '').toUpperCase()
            + (secs ? '  ' + secs.toFixed(1) + 'S' : ''),
            win.x + 7, cy2 + 3);
        }
        ctx.strokeStyle = INK.boxLine;
        ctx.lineWidth = 1;
        ctx.strokeRect(win.x - .5, win.y + win.h - .5, win.w + 1, 1);
      }

      if (!detail) { ctx.restore(); return; }

      const px = sx + 10 * view.s;
      /* The number and the kind, in the same tiny uppercase mono the
         references put on every element. */
      ctx.font = '9px ' + MONO;
      ctx.fillStyle = sel ? INK.hot : colourOf(b.node);
      const top = sy + b.shot * view.s;
      ctx.fillText(String(b.num).padStart(2, '0'), px, top + 14 * view.s);
      ctx.fillStyle = INK.faint;
      ctx.fillText(String(b.node.type || '').toUpperCase(),
                   px + 20 * view.s, top + 14 * view.s);
      /* A quiet mark on any box with an excerpt behind it, so the drawing
         itself says which elements are worth opening. */
      if (b.node.excerpt) {
        ctx.fillStyle = INK.faint;
        ctx.fillText('\u00b6', sx + w - 9 * view.s, top + h - 7 * view.s);
      }
      if (b.node.n) {
        const cnt = '×' + b.node.n;
        ctx.fillStyle = INK.faint;
        ctx.fillText(cnt, sx + w - ctx.measureText(cnt).width - 8 * view.s,
                     top + 14 * view.s);
      }

      ctx.font = (12 * view.s).toFixed(1) + 'px ' + MONO;
      ctx.fillStyle = on ? INK.text : INK.dim;
      b.lines.forEach((line, i) => {
        ctx.fillText(line, px, top + (26 + i * 15) * view.s + 4);
      });
      ctx.restore();
    });

    drawKey();
  }

  /* The key, pinned to the glass and never zoomed - it is an instrument
     label, not part of the drawing. */
  function drawKey() {
    const rows = [
      [INK.measured, 'MEASURED', 'the round’s own paperwork says so'],
      [INK.written, 'WRITTEN', 'in the store, nothing proves it was read'],
      [INK.absent, 'ABSENT', 'the road is known not to record'],
    ];
    ctx.save();
    ctx.font = '9px ' + MONO;
    let y = ch() - 14 - rows.length * 13;
    ctx.fillStyle = 'rgba(14,14,13,.86)';
    ctx.fillRect(10, y - 14, 262, rows.length * 13 + 20);
    ctx.strokeStyle = INK.boxLine;
    ctx.lineWidth = 1;
    ctx.strokeRect(10.5, y - 13.5, 261, rows.length * 13 + 19);
    ctx.fillStyle = INK.faint;
    ctx.fillText(String(layout).toUpperCase() + '  ·  '
      + (laid ? laid.boxes.size : 0) + ' NODES  ·  '
      + (laid ? laid.links.length : 0) + ' PATHS', 18, y - 2);
    rows.forEach((row) => {
      ctx.strokeStyle = row[0];
      ctx.lineWidth = row[1] === 'MEASURED' ? 1.4 : 1.1;
      ctx.setLineDash(row[1] === 'ABSENT' ? [3, 3] : []);
      ctx.beginPath();
      ctx.moveTo(18, y + 8);
      ctx.lineTo(40, y + 8);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = row[0];
      ctx.fillText(row[1], 46, y + 11);
      ctx.fillStyle = INK.faint;
      ctx.fillText(row[2], 102, y + 11);
      y += 13;
    });
    ctx.restore();
  }

  /* -------------------------------------------------------- [#1387] MEDIA
   *
   * TAP PLAYS IT. HOLD ASKS WHAT TO DO WITH IT.
   *
   * Both gestures land on the same node, which is why they must not both
   * fire: the hold arms at 480ms and MARKS the gesture spent, so letting go
   * afterwards does not also play the clip behind the menu that just
   * opened. The same 10px of slop as every other tap here, because a finger
   * resting on glass never rests still.
   *
   * The player is real HTML over the canvas rather than a frame decoded
   * into it: a <video> can seek, scrub and honour its own codecs, and a
   * canvas cannot do any of that without becoming a media player. And it
   * DUCKS the station while it plays - the standing rule for any surface
   * that makes noise over the broadcast. */
  let player = null;
  let ducked = null;

  function duck(on) {
    const D = window.PineDuck;
    if (!D || typeof D.hold !== 'function') return;
    try {
      if (on && !ducked) {
        ducked = D.hold('word-cause', D.REPORT || 0.1, player || stage);
      } else if (!on && ducked) {
        if (typeof ducked === 'function') ducked();
        else if (ducked && typeof ducked.release === 'function') ducked.release();
        ducked = null;
      }
    } catch (err) { ducked = null; }
  }

  function stopPlaying() {
    if (!player) return;
    try { player.remove(); } catch (err) { /* already gone */ }
    player = null;
    duck(false);
  }

  function playClip(node) {
    const m = node && node.media;
    if (!m || !m.play) return;
    stopPlaying();
    const url = /^https?:/.test(m.play) ? m.play : base + m.play;
    const shell = el('div', 'wc-player');
    const head = el('div', 'wc-player-head');
    head.appendChild(el('b', '', String(m.name || node.label || 'clip')));
    const shut2 = el('button', 'wc-btn wc-small', 'close');
    shut2.onclick = () => stopPlaying();
    head.appendChild(shut2);
    shell.appendChild(head);
    const tag = document.createElement(m.kind === 'video' ? 'video' : 'audio');
    tag.src = url;
    tag.controls = true;
    tag.autoplay = true;
    tag.className = 'wc-player-media';
    /* A clip that will not play says why, here, rather than sitting
       silently at 0:00 - which is indistinguishable from a broken tap. */
    tag.onerror = () => {
      const why = el('div', 'wc-player-bad',
        'the station would not serve that clip - it may have been renamed '
        + 'or carried off the share since it aired');
      shell.appendChild(why);
    };
    tag.onended = () => { if (m.kind !== 'video') stopPlaying(); };
    shell.appendChild(tag);
    stage.appendChild(shell);
    player = shell;
    duck(true);
  }

  /* The hold sheet. Four choices, and the irreversible one is amber and
     asked twice - two differently worded confirmations for one destructive
     act is how an operator gets surprised, so it is the SAME button that
     changes its own words. */
  let sheet = null;
  function closeSheet() {
    if (!sheet) return;
    try { sheet.remove(); } catch (err) { /* gone */ }
    sheet = null;
  }

  function holdSheet(node, atX, atY) {
    closeSheet();
    const m = node && node.media;
    if (!m) return;
    const box = el('div', 'wc-sheet');
    const rect = stage.getBoundingClientRect();
    box.style.left = Math.max(8, Math.min(rect.width - 218, atX - rect.left - 100)) + 'px';
    box.style.top = Math.max(8, Math.min(rect.height - 210, atY - rect.top - 16)) + 'px';
    const title = el('div', 'wc-sheet-head',
      String(m.name || node.label || 'clip'));
    box.appendChild(title);
    const said = el('div', 'wc-sheet-said', '');
    const row = (label, cls, run) => {
      const b = el('button', 'wc-btn ' + (cls || ''), label);
      b.onclick = (ev) => { ev.stopPropagation(); run(b); };
      box.appendChild(b);
      return b;
    };
    row('play it', '', () => { closeSheet(); playClip(node); });
    row('save it', '', (b) => {
      b.textContent = 'saving\u2026';
      request('/api/clip/save', {method: 'POST',
        body: JSON.stringify({id: m.sid})})
        .then((r) => { said.textContent = String(r.say || 'saved'); refresh(); })
        .catch((err) => { said.textContent = String((err && err.message) || err); })
        .then(() => { b.textContent = 'save it'; });
    });
    row('to a sampler pad', '', (b) => {
      /* The sampler is the TERMINAL's, not the station's - the pads live
         in this browser. So the same door the line menu uses, and the same
         honest refusal when this glass has no sampler on it. */
      const S = window.PineSampler;
      if (!S || typeof S.grab !== 'function') {
        said.textContent = 'the sampler is not loaded on this terminal';
        return;
      }
      b.textContent = 'sending\u2026';
      Promise.resolve(S.grab({sfx: m.sid,
                              url: (/^https?:/.test(m.play) ? m.play : base + m.play),
                              text: String(m.name || '')}))
        .then((got) => {
          said.textContent = (got && got.ok === false)
            ? String(got.why || 'the sampler would not take it')
            : ('on pad ' + (((got && got.pad) | 0) + 1)
               + ' of bank ' + (((got && got.bank) | 0) + 1));
        })
        .catch((err) => { said.textContent = String((err && err.message) || err); })
        .then(() => { b.textContent = 'to a sampler pad'; });
    });
    let armed = false;
    row('delete it', 'wc-warn', (b) => {
      if (!armed) {
        armed = true;
        b.textContent = 'delete it \u2014 press again';
        said.textContent = 'this removes the clip from the library. The '
          + 'file lives on a read-only share, so the desk carries the '
          + 'delete out when it is running.';
        return;
      }
      b.textContent = 'deleting\u2026';
      request('/api/sfx/delete', {method: 'POST',
        body: JSON.stringify({id: m.sid})})
        .then((r) => { said.textContent = String(r.say || 'deleted'); refresh(); })
        .catch((err) => { said.textContent = String((err && err.message) || err); })
        .then(() => { b.textContent = 'delete it'; armed = false; });
    });
    box.appendChild(said);
    stage.appendChild(box);
    sheet = box;
  }

  /* ------------------------------------------------------------ the view */
  function clampZoom(z) { return Math.max(0.18, Math.min(3.2, z)); }

  function fitNow() {
    if (!laid || !ctx) return;
    const s = clampZoom(Math.min(cw() / Math.max(1, laid.w),
                                 ch() / Math.max(1, laid.h)) * 0.94);
    view.want = {x: laid.w / 2, y: laid.h / 2, s};
    view.at = Date.now();
    ease();
  }
  function fit() { fitNow(); }

  function focusOn(node) {
    if (!node || !laid) return;
    const b = laid.boxes.get(node.id);
    if (!b) return;
    view.want = {x: b.x + b.w / 2, y: b.y + b.h / 2, s: clampZoom(1.15)};
    view.at = Date.now();
    ease();
  }

  /* A short ease, and then the picture is STILL. Every step reads a fresh
     clock, because the tablet suspends timers while rAF keeps firing. */
  function ease() {
    if (raf !== null || dead) return;
    const run = () => {
      raf = null;
      if (dead || !view.want) { draw(); return; }
      const k = Math.min(1, (Date.now() - view.at) / 380);
      const e = Math.max(0.09, k * k * (3 - 2 * k) * 0.42);
      view.x += (view.want.x - view.x) * e;
      view.y += (view.want.y - view.y) * e;
      view.s += (view.want.s - view.s) * e;
      if (k >= 1) {
        view.x = view.want.x; view.y = view.want.y; view.s = view.want.s;
        view.want = null;
      }
      draw();
      if (view.want) raf = requestAnimationFrame(run);
    };
    raf = requestAnimationFrame(run);
  }

  async function mount() {
    stage.appendChild(canvas);
    ctx = canvas.getContext('2d');
    if (!ctx) {
      stage.appendChild(el('div', 'wc-flat',
        'No canvas here, so the drawing is missing - the record beside it '
        + 'is the whole of it, and nothing is lost but the shape.'));
      return;
    }
    resize();
    bindControls(canvas);
  }

  function atPoint(ev) {
    if (!laid) return null;
    const rect = canvas.getBoundingClientRect();
    const wx = (ev.clientX - rect.left - cw() / 2) / view.s + view.x;
    const wy = (ev.clientY - rect.top - ch() / 2) / view.s + view.y;
    let found = null;
    laid.boxes.forEach((b) => {
      if (wx >= b.x && wx <= b.x + b.w && wy >= b.y && wy <= b.y + b.h) {
        found = b.node;
      }
    });
    return found;
  }

  function bindControls(node) {
    const pts = new Map();
    let pinch = 0;
    let panning = null;
    let downAt = 0;
    let lastTap = 0;
    let held = null;
    const dropHold = () => {
      if (held) { clearTimeout(held); held = null; }
    };

    node.addEventListener('wheel', (ev) => {
      ev.preventDefault();
      /* Zoom AT THE POINTER - the house rule. The world point under the
         cursor is the anchor, and it does not move. */
      const rect = node.getBoundingClientRect();
      const px = ev.clientX - rect.left;
      const py = ev.clientY - rect.top;
      const wx = (px - cw() / 2) / view.s + view.x;
      const wy = (py - ch() / 2) / view.s + view.y;
      view.s = clampZoom(view.s * (ev.deltaY > 0 ? 0.88 : 1.13));
      view.x = wx - (px - cw() / 2) / view.s;
      view.y = wy - (py - ch() / 2) / view.s;
      view.want = null;
      draw();
    }, {passive: false});

    node.addEventListener('pointerdown', (ev) => {
      node.setPointerCapture?.(ev.pointerId);
      pts.set(ev.pointerId, {x: ev.clientX, y: ev.clientY});
      if (pts.size === 2) {
        const two = [...pts.values()];
        pinch = Math.hypot(two[0].x - two[1].x, two[0].y - two[1].y);
        panning = null;
      } else {
        downAt = Date.now();
        panning = {x: ev.clientX, y: ev.clientY, moved: 0, spent: false};
        closeSheet();
        /* TAP AND HOLD. It arms here and cancels on movement, on a second
           finger, and on letting go - and when it does fire it marks the
           gesture spent, so the release does not also play the clip
           underneath the sheet that just opened. */
        const on = atPoint(ev);
        if (on && on.media) {
          const px = ev.clientX;
          const py = ev.clientY;
          const mine = panning;
          held = setTimeout(() => {
            held = null;
            if (!panning || panning !== mine || mine.moved > 10) return;
            mine.spent = true;
            holdSheet(on, px, py);
          }, 480);
        }
      }
    });

    node.addEventListener('pointermove', (ev) => {
      if (!pts.has(ev.pointerId)) {
        const over = atPoint(ev);
        const id = over ? over.id : null;
        if (id !== hot) { hot = id; draw(); }
        return;
      }
      pts.set(ev.pointerId, {x: ev.clientX, y: ev.clientY});
      if (pts.size === 2 && pinch > 0) {
        dropHold();
        const two = [...pts.values()];
        const gap = Math.hypot(two[0].x - two[1].x, two[0].y - two[1].y);
        if (gap > 0) {
          view.s = clampZoom(view.s * (gap / pinch));
          pinch = gap;
          view.want = null;
          draw();
        }
        return;
      }
      if (panning) {
        const dx = ev.clientX - panning.x;
        const dy = ev.clientY - panning.y;
        panning.moved += Math.abs(dx) + Math.abs(dy);
        if (panning.moved > 10) dropHold();
        view.x -= dx / view.s;
        view.y -= dy / view.s;
        panning.x = ev.clientX;
        panning.y = ev.clientY;
        view.want = null;
        draw();
      }
    });

    const up = (ev) => {
      const was = panning;
      dropHold();
      pts.delete(ev.pointerId);
      if (pts.size < 2) pinch = 0;
      panning = null;
      if (!was || was.spent) return;   /* the hold already answered this */
      /* A drag is not a tap. 10px of slop, because a finger on glass
         never lands still. A long press is not a tap either, and 700ms
         is past the 480ms the hold sheet arms at. */
      if (was.moved > 10 || Date.now() - downAt > 700) return;
      const found = atPoint(ev);
      if (!found) return;
      const now = Date.now();
      if (now - lastTap < 320) { focusOn(found); lastTap = 0; return; }
      lastTap = now;
      showNode(found);
      /* "I want to be able to tap on them in order to have them play."
         A clip answers a tap by playing; everything else answers by
         opening its record in the rail, which it has just done. */
      if (found.media && found.media.play) playClip(found);
    };
    node.addEventListener('pointerup', up);
    node.addEventListener('pointercancel', (ev) => {
      dropHold();
      pts.delete(ev.pointerId); panning = null; pinch = 0;
    });
    /* A right-click is the desk's own way of asking the same question. */
    node.addEventListener('contextmenu', (ev) => {
      const on = atPoint(ev);
      if (!on || !on.media) return;
      ev.preventDefault();
      holdSheet(on, ev.clientX, ev.clientY);
    });
    node.addEventListener('pointerleave', () => {
      if (hot) { hot = null; draw(); }
    });

    node.addEventListener('dblclick', (ev) => {
      const found = atPoint(ev);
      if (found) focusOn(found);
    });

    node.setAttribute('tabindex', '0');
    node.addEventListener('keydown', (ev) => {
      if (ev.key === '0') { fit(); ev.preventDefault(); }
    });
  }

  function resize() {
    if (!ctx) return;
    const w = Math.max(200, stage.clientWidth);
    const h = Math.max(200, stage.clientHeight);
    canvas.width = Math.round(w * dpr());
    canvas.height = Math.round(h * dpr());
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
    draw();
  }

  /* -------------------------------------------------------------- rail */
  function showNode(node) {
    picked = node;
    paintRail();
  }

  function paintRail() {
    rail.textContent = '';
    if (!data) { rail.appendChild(el('div', 'wc-muted', 'nothing asked yet')); return; }
    rail.appendChild(el('div', 'wc-say', data.say || ''));

    const air = data.air || {};
    if (air.why) {
      const v = el('div', 'wc-verdict', air.why);
      rail.appendChild(v);
    }
    if (air.total != null) {
      rail.appendChild(el('div', 'wc-muted',
        air.total + ' airing(s), ' + (air.distinct || 0) + ' distinct line(s)'));
    }

    (data.gaps || []).forEach((g) => {
      const row = el('div', 'wc-gap');
      row.appendChild(el('b', '', g.road));
      row.appendChild(el('span', '', ' ' + g.say));
      rail.appendChild(row);
    });

    if (picked) {
      const card = el('div', 'wc-card');
      card.appendChild(el('b', '', picked.label || picked.type));
      card.appendChild(el('div', 'wc-muted', picked.type
        + (picked.n ? '  ·  ' + picked.n : '')));
      if (picked.snippet) card.appendChild(el('div', 'wc-snip', picked.snippet));
      /* The card is what a tap opens, so the words belong here too - not
         only behind the caret in the list below. */
      if (picked.excerpt) {
        const how = el('div', 'wc-exhow', '');
        const grade = String(picked.excerpt_grade || 'written');
        how.appendChild(el('b', 'wc-grade wc-grade-' + grade, grade));
        how.appendChild(el('span', '', ' ' + String(picked.excerpt_how || '')));
        card.appendChild(how);
        card.appendChild(el('div', 'wc-snip wc-excerpt', String(picked.excerpt)));
      }
      if (picked.store) {
        card.appendChild(el('div', 'wc-muted', picked.store + '  ' + (picked.key || '')));
      }
      if (picked.kill && picked.kill.kill_label) {
        card.appendChild(el('div', 'wc-muted', picked.kill.kill_label));
      }
      actionsFor(card, picked);
      rail.appendChild(card);
    }
    paintEdits();

    paintStrip();
    const total = (data.nodes || []).length;
    const shown = kept().length;
    const head = el('div', 'wc-head',
      shown === total ? 'every node'
        : ('showing ' + shown + ' of ' + total + ' \u2014 the rest is '
           + 'filtered, not missing'));
    rail.appendChild(head);
    const list = el('div', 'wc-list');
    kept().slice()
      .sort((a, b) => (numbers.get(a.id) || 1e6) - (numbers.get(b.id) || 1e6)
        || (Number(b.n) || 0) - (Number(a.n) || 0))
      .forEach((n) => {
        const row = el('div', 'wc-row');
        /* [#1387] THE SAME NUMBER AS THE BOX. The drawing letters every
           element 01, 02, 03 in reading order; the rail prints the same
           number against the same thing, so "which one is 07" is looked
           up rather than hunted for. A node the drawing has not laid out
           yet shows a dash rather than a wrong number. */
        const num = el('i', 'wc-num',
          numbers.has(n.id) ? String(numbers.get(n.id)).padStart(2, '0') : '--');
        num.style.color = colourOf(n);
        row.appendChild(num);
        row.appendChild(el('span', 'wc-kind', n.type));
        row.appendChild(el('span', 'wc-label', n.label || ''));
        if (n.n) row.appendChild(el('span', 'wc-n', n.n));
        /* [#1386] EVERY ROW OPENS. "be able to go in and expand each of the
           elements in the sidebar to see the details on each and every
           element". One tap selects and draws the node's card above;
           the caret opens the whole record inline, here, without losing
           your place in the list. */
        const more = el('button', 'wc-more', '\u25be');
        more.title = 'open everything the station holds about this';
        const deep = el('div', 'wc-deep');
        deep.style.display = 'none';
        more.onclick = (ev) => {
          ev.stopPropagation();
          const open = deep.style.display === 'none';
          deep.style.display = open ? 'block' : 'none';
          more.textContent = open ? '\u25b4' : '\u25be';
          if (open && !deep.childNodes.length) fillDeep(deep, n);
        };
        row.appendChild(more);
        row.onclick = () => showNode(n);
        list.appendChild(row);
        list.appendChild(deep);
      });
    rail.appendChild(list);

    const dials = data.dials || {};
    if (Object.keys(dials).length) {
      rail.appendChild(el('div', 'wc-head', 'the dials behind it'));
      Object.keys(dials).forEach((k) => {
        const row = el('div', 'wc-row');
        row.appendChild(el('span', 'wc-kind', k));
        row.appendChild(el('span', 'wc-label', String(dials[k])));
        rail.appendChild(row);
      });
    }
  }

  /* [#1386] WHAT THIS NODE CAN BE TOLD TO DO.
   *
   * Every action here goes through a door the station already owns, and
   * every one of them is written to the undo ledger BEFORE the store is
   * touched. Nothing is offered that cannot be done: a node with nothing
   * to turn says what it is instead of growing a button that would do
   * nothing, because "a control that does nothing at all is worse than
   * one that refuses out loud" (line-deep.js:129).
   *
   * The station is live while this is open, so the strip after every save
   * repeats the station's own contract: most edits land on the NEXT round,
   * not the one being spoken. */
  /* Every field the station holds about this node, and nothing it does
     not: an absent field prints as absent with a reason rather than being
     quietly dropped. */
  function fillDeep(host2, node) {
    const put = (k, v, why) => {
      if (v === undefined || v === null || v === '') {
        if (!why) return;
        const r = el('div', 'wc-deep-row');
        r.appendChild(el('span', 'wc-kind', k));
        r.appendChild(el('span', 'wc-muted', why));
        host2.appendChild(r);
        return;
      }
      const r = el('div', 'wc-deep-row');
      r.appendChild(el('span', 'wc-kind', k));
      r.appendChild(el('span', 'wc-label',
        typeof v === 'object' ? JSON.stringify(v) : String(v)));
      host2.appendChild(r);
    };
    put('type', node.type);
    put('airings', node.n);
    put('label', node.label);
    put('store', node.store, 'not held in a store - this is a live count');
    put('key', node.key);
    put('seat', node.who);
    put('round', node.round);
    put('weight', node.weight,
        node.type === 'doc' ? 'no weight recorded - it draws at the default' : '');
    put('snippet', node.snippet);
    /* [#1387] THE EXCERPT, AS WORDS.
     *
     * "Any element that's being referred to, I need to be able to expand it
     *  and see an excerpt of what is being referred to in that element."
     *
     * A key/value row is for a fact - a weight, a count, a filename. The
     * passage a document was referred to FOR is not a fact, it is prose,
     * and prose in a 148px-key table is unreadable. So it gets its own
     * block, full width, selectable, wrapped, with the sentence saying
     * where it came from and its grade above it - because an excerpt the
     * station is only fairly sure of must not read like one it watched
     * happen. */
    if (node.excerpt) {
      host2.appendChild(el('div', 'wc-head', 'what it says'));
      const how = el('div', 'wc-exhow', '');
      const grade = String(node.excerpt_grade || 'written');
      const tag = el('b', 'wc-grade wc-grade-' + grade, grade);
      how.appendChild(tag);
      how.appendChild(el('span', '', ' ' + String(node.excerpt_how || '')));
      host2.appendChild(how);
      const body = el('div', 'wc-snip wc-excerpt', String(node.excerpt));
      host2.appendChild(body);
    } else if (node.excerpt_how) {
      /* Nothing to show and a reason why. Better than a blank. */
      host2.appendChild(el('div', 'wc-head', 'what it says'));
      host2.appendChild(el('div', 'wc-exhow', String(node.excerpt_how)));
    }
    put('how it can be removed', node.kill && node.kill.kill_label,
        'nothing here can remove this');
    /* The edges that reach it - the actual road from the word to here. */
    const ins = (data.edges || []).filter((e) => e.to === node.id);
    const outs = (data.edges || []).filter((e) => e.from === node.id);
    if (ins.length || outs.length) {
      host2.appendChild(el('div', 'wc-head', 'how it is connected'));
      ins.slice(0, 8).forEach((e) => {
        const r = el('div', 'wc-deep-row');
        r.appendChild(el('span', 'wc-kind', e.grade));
        r.appendChild(el('span', 'wc-label', '\u2190 ' + e.rel + '  ' + (e.say || '')));
        host2.appendChild(r);
      });
      outs.slice(0, 8).forEach((e) => {
        const r = el('div', 'wc-deep-row');
        r.appendChild(el('span', 'wc-kind', e.grade));
        r.appendChild(el('span', 'wc-label', '\u2192 ' + e.rel + '  ' + (e.say || '')));
        host2.appendChild(r);
      });
    }
    const go = el('button', 'wc-btn wc-small', 'bring it to the middle');
    go.onclick = (ev) => { ev.stopPropagation(); focusOn(node); };
    host2.appendChild(go);
  }

  function actionsFor(card, node) {
    const say = el('div', 'wc-muted', '');
    const done = (text) => { say.textContent = String(text || ''); refresh(); };
    const fail = (err) => { say.textContent = String((err && err.message) || err); };

    if (node.type === 'doc') {
      const row = el('div', 'wc-act');
      row.appendChild(el('span', 'wc-kind', 'weight'));
      const slide = document.createElement('input');
      slide.type = 'range'; slide.min = '0'; slide.max = '100';
      slide.value = String(node.weight == null ? 8 : node.weight);
      slide.className = 'wc-slide';
      const val = el('span', 'wc-n', slide.value);
      slide.oninput = () => { val.textContent = slide.value; };
      slide.onchange = () => {
        request('/api/speakbox/weight', {
          method: 'POST',
          body: JSON.stringify({file: node.label, weight: Number(slide.value),
                                word: (data && data.q) || '', node_id: node.id}),
        }).then((r) => done(r.say)).catch(fail);
      };
      row.appendChild(slide);
      row.appendChild(val);
      card.appendChild(row);
      card.appendChild(el('div', 'wc-muted',
        '0 switches the document off - it will not be drawn from again.'));
    } else if (node.type === 'gold') {
      const row = el('div', 'wc-act');
      const burn = el('button', 'wc-btn', 'burn this bar');
      burn.title = 'Out of the bank and into data/gold_burnt.json. It can be '
        + 'put back.';
      burn.onclick = () => {
        request('/api/gold/burn', {
          method: 'POST',
          body: JSON.stringify({keys: [String(node.id).replace(/^gold:/, '')],
                                why: 'burnt from the cause graph',
                                word: (data && data.q) || ''}),
        }).then((r) => done(r.say)).catch(fail);
      };
      row.appendChild(burn);
      card.appendChild(row);
      card.appendChild(el('div', 'wc-muted',
        'A banked bar has no prompt behind it - this is the only lever that '
        + 'reaches it without banning the whole phrase.'));
    } else if (node.edit && node.edit.scope) {
      /* [#1386] "edit their system prompts". Through the one door the
         station already owns - PUT /api/paperwork/field - which decides
         which store a scope names, keeps the (used) flags, and answers
         with the sentence that goes on the strip. `was` is sent so the
         station can refuse an edit written against a box that has since
         moved, rather than clobbering it. */
      const box = document.createElement('textarea');
      box.className = 'wc-box';
      box.value = String(node.snippet || '');
      box.rows = 5;
      const was = String(node.snippet || '');
      const save = el('button', 'wc-btn', 'save it');
      save.onclick = () => {
        request('/api/paperwork/field', {
          method: 'PUT',
          body: JSON.stringify({scope: node.edit.scope,
                                key: node.edit.key || node.label || '',
                                value: box.value, was: was}),
        }).then((r) => done(r.say || 'saved - it lands on the next round'))
          .catch(fail);
      };
      card.appendChild(box);
      const row = el('div', 'wc-act');
      row.appendChild(save);
      card.appendChild(row);
      card.appendChild(el('div', 'wc-muted',
        'Most edits land on the NEXT round, not the one being spoken.'));
    } else if (node.kill && node.kill.source_id && node.kill.kill
               && node.kill.kill !== 'code' && node.kill.kill !== 'file') {
      card.appendChild(el('div', 'wc-muted',
        'Tick this source in the ban sheet on the Script view to remove it - '
        + 'a ban retires prepared rounds and burns bars as it goes, so it '
        + 'asks there, where every cost is named.'));
    } else if (node.type === 'code' || (node.kill && node.kill.kill === 'code')) {
      card.appendChild(el('div', 'wc-muted',
        'This is written into the code - the ban covers it at the mouth, but '
        + 'no tick-box can edit a Python tuple.'));
    }
    card.appendChild(say);
  }

  /* The last twenty changes, and the ones that can be walked back. */
  let edits = [];
  function paintEdits() {
    if (!edits.length) return;
    rail.appendChild(el('div', 'wc-head', 'what you changed'));
    edits.slice(0, 20).forEach((e) => {
      const row = el('div', 'wc-row');
      row.appendChild(el('span', 'wc-kind', e.node_type || '-'));
      row.appendChild(el('span', 'wc-label', e.say || e.endpoint));
      if (e.can_undo) {
        const back = el('button', 'wc-btn wc-small', 'put it back');
        back.onclick = (ev) => {
          ev.stopPropagation();
          request('/api/word/edits/undo', {
            method: 'POST', body: JSON.stringify({at: e.at}),
          }).then(() => refresh()).catch(() => {});
        };
        row.appendChild(back);
      } else if (e.why_not) {
        const no = el('span', 'wc-muted', 'cannot be undone');
        no.title = e.why_not;
        row.appendChild(no);
      }
      rail.appendChild(row);
    });
  }

  async function refresh() {
    try {
      const got = await request('/api/word/edits?most=20');
      edits = got.edits || [];
    } catch (err) { edits = []; }
    if (data) paintRail();
  }

  /* [#1386] ONE LINE, NOT ONE WORD. The script view hands over a line id
     and the same picture is drawn from /api/line/causes - the line in the
     middle, and every thing that made it hanging off it. */
  let lastLine = '';
  let lastSaid = '';

  async function showLine(lineId, said) {
    const id = String(lineId || '').trim();
    if (!id) return;
    lastLine = id;
    lastSaid = String(said || '');
    field.value = said ? String(said).slice(0, 60) : '';
    rail.textContent = '';
    rail.appendChild(el('div', 'wc-muted', 'tracing that line back...'));
    try {
      data = await request('/api/line/causes?id=' + encodeURIComponent(id));
    } catch (err) {
      rail.textContent = '';
      rail.appendChild(el('div', 'wc-gap', String((err && err.message) || err)));
      return;
    }
    if (data && data.ok === false) {
      rail.textContent = '';
      rail.appendChild(el('div', 'wc-gap', String(data.say || 'that line is not in the ledger')));
      return;
    }
    try {
      const got = await request('/api/word/edits?most=20');
      edits = got.edits || [];
    } catch (err) { edits = []; }
    picked = null;
    stopPlaying();
    closeSheet();
    fitted = false;   /* a new subject gets framed again */
    build();
    paintRail();
  }

  async function load(word) {
    const q = String(word || '').trim();
    if (q.length < 2) return;
    lastLine = '';
    lastSaid = '';
    rail.textContent = '';
    rail.appendChild(el('div', 'wc-muted', 'following ' + q + ' back...'));
    try {
      data = await request('/api/word/causes?q=' + encodeURIComponent(q));
      try {
        const got = await request('/api/word/edits?most=20');
        edits = got.edits || [];
      } catch (err) { edits = []; }
    } catch (err) {
      rail.textContent = '';
      rail.appendChild(el('div', 'wc-gap', String((err && err.message) || err)));
      return;
    }
    picked = null;
    stopPlaying();
    closeSheet();
    fitted = false;   /* a new subject gets framed again */
    build();
    paintRail();
  }

  function close() {
    if (dead) return;
    dead = true;
    if (raf !== null) { try { cancelAnimationFrame(raf); } catch (e) { /* gone */ } }
    raf = null;
    /* [#1387] There is no WebGL context to hand back any more - the whole
       reason that dance existed. A canvas dies with its element. */
    laid = null;
    ctx = null;
    stopPlaying();
    closeSheet();
    try { if (root.parentNode) root.parentNode.removeChild(root); }
    catch (e) { /* already gone */ }
    try { onClose(); } catch (e) { /* the caller is gone */ }
  }

  mount().then(() => { if (opts.word) load(opts.word); });

  return {
    element: root,
    resize,
    close,
    show: (w) => { field.value = w; load(w); },
    showLine,
  };
}
