/* MARKING UP THE TABLET'S SCREEN.
 *
 * "A window that allows me to do a draw over where I'm able to click and drag
 *  and draw things on it and make arrows and indicators and do overlays of
 *  text overlays that I'm able to scale and adjust in real time to basically
 *  set up and explain things on it, and allow me to then copy that modified
 *  image to clipboard after modifying it. Offer the same tools that I have in
 *  ShareX."
 *
 * EVERY MARK IS AN OBJECT, NOT PAINT. That is the whole design, and it is
 * what "adjust in real time" requires: an arrow put down ten marks ago can
 * still be picked up, moved, recoloured, made thicker or thrown away. Paint
 * can only be undone, and only if it was the last thing you did - which is
 * exactly the point at which an annotation tool starts making you redo work.
 *
 * The canvas is therefore never drawn on incrementally. Anything that changes
 * redraws the whole picture from the original plus the list of marks, which
 * costs nothing at screenshot sizes and means there is only ever one truth.
 */
'use strict';

const api = window.pineDesktop || {};
const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
const holder = document.getElementById('holder');
const stage = document.getElementById('stage');
const typing = document.getElementById('typing');

/* The picture underneath, the marks on top, and the two stacks that let any
 * of it be taken back. */
let base = null;
let marks = [];
let past = [];
let future = [];

let tool = 'select';
let selected = null;
/* THE LABEL CURRENTLY IN THE TEXT BOX. Declared up here with the rest of the
 * state rather than beside the typing code, because redraw() skips it - and a
 * `let` read before its declaration runs is a dead-zone throw, not an
 * undefined. */
let typingMark = null;
/* SPACE HELD = the hand tool, for as long as it is held. See the listeners
 * near the keyboard shortcuts. */
let spaceHeld = false;
let drag = null;
let steps = 0;             /* the running number for the step counter */
let scale = 1;             /* picture pixels per screen pixel */
let fitScale = 1;          /* what `scale` is when the whole picture shows */
let zoomedByHand = false;  /* has the operator taken the wheel to it */

const style = { colour: '#ff3b30', weight: 4, fill: false, fontSize: 28 };

/* A scratch canvas for the pixelate tool. One, reused - allocating a canvas
 * per frame while dragging a blur box is how you make a 1340x800 editor
 * stutter. */
const scratch = document.createElement('canvas');
const sctx = scratch.getContext('2d');

/* ------------------------------------------------------------------ tools */

const TOOLS = [
  { id: 'select', glyph: '↖', title: 'Select, move and resize anything already drawn (V)' },
  { id: 'arrow', glyph: '→', title: 'Arrow (A)' },
  { id: 'line', glyph: '╱', title: 'Straight line (L)' },
  { id: 'rect', glyph: '▭', title: 'Rectangle (R)' },
  { id: 'ellipse', glyph: '◯', title: 'Ellipse (E)' },
  { id: 'pen', glyph: '✎', title: 'Freehand (P)' },
  { id: 'text', glyph: 'A', title: 'Text - click for a label, or DRAG A BOX and the type fills it (T)' },
  { id: 'highlight', glyph: '▬', title: 'Highlighter (H)' },
  { id: 'blur', glyph: '▒', title: 'Pixelate - for hiding something (B)' },
  { id: 'step', glyph: '①', title: 'Numbered step, for pointing things out in order (S)' },
  { id: 'crop', glyph: '⛶', title: 'Crop to a region (C)' }
];

const KEYS = { v: 'select', a: 'arrow', l: 'line', r: 'rect', e: 'ellipse',
  p: 'pen', t: 'text', h: 'highlight', b: 'blur', s: 'step', c: 'crop' };

(function buildTools() {
  const host = document.getElementById('tools');
  for (const entry of TOOLS) {
    const button = document.createElement('button');
    button.className = 'tool' + (entry.id === tool ? ' on' : '');
    button.textContent = entry.glyph;
    button.title = entry.title;
    button.dataset.tool = entry.id;
    button.addEventListener('click', () => pickTool(entry.id));
    host.appendChild(button);
  }
})();

function pickTool(id) {
  commitTyping();
  tool = id;
  for (const button of document.querySelectorAll('.tool')) {
    button.classList.toggle('on', button.dataset.tool === id);
  }
  canvas.classList.toggle('picking', id === 'select');
  if (id !== 'select') select(null);
  say(TOOLS.find((t) => t.id === id).title);
}

/* ------------------------------------------------------------- the record */

/* Taken BEFORE a change, so undo lands on the state the operator last saw.
 * Marks are plain data, so a structured clone is the whole snapshot. */
function remember() {
  past.push(JSON.stringify(marks));
  if (past.length > 200) past.shift();
  future.length = 0;
  paintButtons();
}

function undo() {
  if (!past.length) return;
  future.push(JSON.stringify(marks));
  marks = JSON.parse(past.pop());
  selected = null;
  paintButtons();
  redraw();
}

function redo() {
  if (!future.length) return;
  past.push(JSON.stringify(marks));
  marks = JSON.parse(future.pop());
  selected = null;
  paintButtons();
  redraw();
}

function paintButtons() {
  document.getElementById('undoBtn').disabled = !past.length;
  document.getElementById('redoBtn').disabled = !future.length;
  document.getElementById('deleteBtn').disabled = !selected;
}

/* ----------------------------------------------------------------- drawing */

function norm(mark) {
  /* Dragged right-to-left or bottom-to-top, a box has negative width. Every
   * hit test and every fill would then need to know that; normalising once
   * here means none of them do. */
  const box = { x: mark.x, y: mark.y, w: mark.w, h: mark.h };
  if (box.w < 0) { box.x += box.w; box.w = -box.w; }
  if (box.h < 0) { box.y += box.h; box.h = -box.h; }
  return box;
}

function boundsOf(mark) {
  if (mark.kind === 'line' || mark.kind === 'arrow') {
    return { x: Math.min(mark.x1, mark.x2), y: Math.min(mark.y1, mark.y2),
      w: Math.abs(mark.x2 - mark.x1), h: Math.abs(mark.y2 - mark.y1) };
  }
  if (mark.kind === 'pen') {
    const xs = mark.pts.map((p) => p[0]), ys = mark.pts.map((p) => p[1]);
    return { x: Math.min(...xs), y: Math.min(...ys),
      w: Math.max(...xs) - Math.min(...xs), h: Math.max(...ys) - Math.min(...ys) };
  }
  if (mark.kind === 'text') {
    /* A FITTED LABEL IS ITS BOX. The handles and the selection outline then
     * describe the thing that was drawn, so dragging a corner resizes what
     * the operator thinks they are resizing rather than the glyphs. */
    if (mark.fit) {
      return { x: mark.x, y: mark.y,
        w: Math.max(8, mark.fit.w), h: Math.max(8, mark.fit.h) };
    }
    const size = textSize(mark);
    return { x: mark.x, y: mark.y, w: size.w, h: size.h };
  }
  if (mark.kind === 'step') {
    const r = mark.radius;
    return { x: mark.x - r, y: mark.y - r, w: r * 2, h: r * 2 };
  }
  return norm(mark);
}

/**
 * THE LARGEST TYPE THAT FILLS `mark.fit`.
 *
 * Arithmetic rather than a search, because both limits are linear:
 *
 *   width   text width is proportional to font size, so measuring the widest
 *           line once at 100px gives the width per pixel of font size. The
 *           +0.4 is the side padding textSize() already adds.
 *   height  line height is a fixed 1.25 of the font size, so N rows fit
 *           exactly when the size is box.h / (N * 1.25).
 *
 * The answer is the smaller, and it is exact at every size rather than
 * converging to nearly right.
 */
function fitFont(mark) {
  const box = mark.fit;
  if (!box || !(box.w > 0) || !(box.h > 0)) return mark.fontSize;
  const lines = String(mark.text || '').split('\n');
  const rows = Math.max(1, lines.length);

  ctx.save();
  ctx.font = '100px "Segoe UI", system-ui, sans-serif';
  let widest = 0;
  for (const line of lines) widest = Math.max(widest, ctx.measureText(line).width);
  ctx.restore();

  /* Drawn width per 1px of font size. Never zero, so an empty line cannot
   * divide by it - an empty box is then governed by its height, which is
   * what an operator who has drawn a box and not yet typed expects to see. */
  const perPixel = (widest / 100) + 0.4;
  const byWidth = box.w / perPixel;
  const byHeight = box.h / (rows * 1.25);
  return Math.max(6, Math.min(400, Math.min(byWidth, byHeight)));
}

function textSize(mark) {
  ctx.save();
  ctx.font = mark.fontSize + 'px "Segoe UI", system-ui, sans-serif';
  const lines = String(mark.text || '').split('\n');
  let width = 0;
  for (const line of lines) width = Math.max(width, ctx.measureText(line).width);
  ctx.restore();
  const lineHeight = mark.fontSize * 1.25;
  return { w: Math.max(8, width + mark.fontSize * 0.4),
    h: Math.max(lineHeight, lines.length * lineHeight), lineHeight };
}

function drawMark(mark) {
  ctx.save();
  ctx.strokeStyle = mark.colour;
  ctx.fillStyle = mark.colour;
  ctx.lineWidth = mark.weight || style.weight;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';

  if (mark.kind === 'rect') {
    const b = norm(mark);
    if (mark.fill) ctx.fillRect(b.x, b.y, b.w, b.h);
    else ctx.strokeRect(b.x, b.y, b.w, b.h);

  } else if (mark.kind === 'ellipse') {
    const b = norm(mark);
    ctx.beginPath();
    ctx.ellipse(b.x + b.w / 2, b.y + b.h / 2, Math.max(1, b.w / 2),
      Math.max(1, b.h / 2), 0, 0, Math.PI * 2);
    if (mark.fill) ctx.fill(); else ctx.stroke();

  } else if (mark.kind === 'line') {
    ctx.beginPath();
    ctx.moveTo(mark.x1, mark.y1);
    ctx.lineTo(mark.x2, mark.y2);
    ctx.stroke();

  } else if (mark.kind === 'arrow') {
    /* The head is scaled off the line weight, so a thick arrow does not end
     * in a pinhead and a thin one does not end in a spade. */
    const head = Math.max(10, (mark.weight || 4) * 3.2);
    const angle = Math.atan2(mark.y2 - mark.y1, mark.x2 - mark.x1);
    const backX = mark.x2 - Math.cos(angle) * head * 0.72;
    const backY = mark.y2 - Math.sin(angle) * head * 0.72;
    ctx.beginPath();
    ctx.moveTo(mark.x1, mark.y1);
    ctx.lineTo(backX, backY);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(mark.x2, mark.y2);
    ctx.lineTo(mark.x2 - Math.cos(angle - 0.42) * head,
      mark.y2 - Math.sin(angle - 0.42) * head);
    ctx.lineTo(mark.x2 - Math.cos(angle + 0.42) * head,
      mark.y2 - Math.sin(angle + 0.42) * head);
    ctx.closePath();
    ctx.fill();

  } else if (mark.kind === 'pen') {
    ctx.beginPath();
    mark.pts.forEach((p, i) => (i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])));
    ctx.stroke();

  } else if (mark.kind === 'highlight') {
    /* Multiply is what a real highlighter does: it darkens towards its own
     * colour and leaves the text underneath readable. Painting it with alpha
     * instead washes the words out. */
    const b = norm(mark);
    ctx.globalCompositeOperation = 'multiply';
    ctx.globalAlpha = 0.45;
    ctx.fillRect(b.x, b.y, b.w, b.h);

  } else if (mark.kind === 'blur') {
    const b = norm(mark);
    if (b.w >= 2 && b.h >= 2) {
      const step = Math.max(2, mark.amount || 12);
      const sw = Math.max(1, Math.round(b.w / step));
      const sh = Math.max(1, Math.round(b.h / step));
      scratch.width = sw;
      scratch.height = sh;
      /* Read back off the canvas rather than the original, so a blur laid
       * over an arrow hides the arrow too - which is what you expect from
       * something whose whole job is "cover this up". */
      sctx.clearRect(0, 0, sw, sh);
      sctx.drawImage(canvas, b.x, b.y, b.w, b.h, 0, 0, sw, sh);
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(scratch, 0, 0, sw, sh, b.x, b.y, b.w, b.h);
      ctx.imageSmoothingEnabled = true;
    }

  } else if (mark.kind === 'text') {
    const size = textSize(mark);
    if (mark.box) {
      ctx.globalAlpha = 0.82;
      ctx.fillStyle = '#000';
      ctx.fillRect(mark.x, mark.y, size.w, size.h);
      ctx.globalAlpha = 1;
      ctx.fillStyle = mark.colour;
    }
    ctx.font = mark.fontSize + 'px "Segoe UI", system-ui, sans-serif';
    ctx.textBaseline = 'top';
    String(mark.text || '').split('\n').forEach((line, i) => {
      ctx.fillText(line, mark.x + mark.fontSize * 0.2, mark.y + i * size.lineHeight
        + (size.lineHeight - mark.fontSize) / 2);
    });

  } else if (mark.kind === 'step') {
    ctx.beginPath();
    ctx.arc(mark.x, mark.y, mark.radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = Math.max(2, mark.radius * 0.12);
    ctx.stroke();
    ctx.fillStyle = '#fff';
    ctx.font = '600 ' + Math.round(mark.radius * 1.15) + 'px "Segoe UI", system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(String(mark.n), mark.x, mark.y + mark.radius * 0.04);
  }
  ctx.restore();
}

const HANDLE = 8;

function handlesOf(mark) {
  if (mark.kind === 'line' || mark.kind === 'arrow') {
    return [{ id: 'p1', x: mark.x1, y: mark.y1 }, { id: 'p2', x: mark.x2, y: mark.y2 }];
  }
  const b = boundsOf(mark);
  return [
    { id: 'nw', x: b.x, y: b.y }, { id: 'n', x: b.x + b.w / 2, y: b.y },
    { id: 'ne', x: b.x + b.w, y: b.y }, { id: 'e', x: b.x + b.w, y: b.y + b.h / 2 },
    { id: 'se', x: b.x + b.w, y: b.y + b.h }, { id: 's', x: b.x + b.w / 2, y: b.y + b.h },
    { id: 'sw', x: b.x, y: b.y + b.h }, { id: 'w', x: b.x, y: b.y + b.h / 2 }
  ];
}

function drawHandles(mark) {
  const b = boundsOf(mark);
  const size = HANDLE / scale;          /* constant on screen at any zoom */
  ctx.save();
  ctx.setLineDash([4 / scale, 3 / scale]);
  ctx.strokeStyle = '#65c7da';
  ctx.lineWidth = 1 / scale;
  ctx.strokeRect(b.x - 1, b.y - 1, b.w + 2, b.h + 2);
  ctx.setLineDash([]);
  ctx.fillStyle = '#fff';
  ctx.strokeStyle = '#0d1217';
  for (const h of handlesOf(mark)) {
    ctx.fillRect(h.x - size / 2, h.y - size / 2, size, size);
    ctx.strokeRect(h.x - size / 2, h.y - size / 2, size, size);
  }
  ctx.restore();
}

function redraw() {
  if (!base) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(base, 0, 0);
  for (const mark of marks) {
    /* NOT THE ONE BEING TYPED. It is already on screen in the text box
     * sitting over this exact spot, and drawing it here as well showed the
     * OLD wording ghosted behind the new - same colour, offset by the box
     * padding, and read as a rendering fault rather than as two copies. */
    if (mark === typingMark) continue;
    drawMark(mark);
  }
  if (selected) drawHandles(selected);
}

/* ------------------------------------------------------------- hit testing */

function near(mark, x, y) {
  const pad = Math.max(6, (mark.weight || 4)) / 1;
  if (mark.kind === 'line' || mark.kind === 'arrow') {
    return distanceToSegment(x, y, mark.x1, mark.y1, mark.x2, mark.y2) <= pad + 4;
  }
  if (mark.kind === 'pen') {
    for (let i = 1; i < mark.pts.length; i++) {
      const a = mark.pts[i - 1], b = mark.pts[i];
      if (distanceToSegment(x, y, a[0], a[1], b[0], b[1]) <= pad + 4) return true;
    }
    return false;
  }
  const b = boundsOf(mark);
  return x >= b.x - 2 && x <= b.x + b.w + 2 && y >= b.y - 2 && y <= b.y + b.h + 2;
}

function distanceToSegment(px, py, x1, y1, x2, y2) {
  const dx = x2 - x1, dy = y2 - y1;
  const len = dx * dx + dy * dy;
  let t = len ? ((px - x1) * dx + (py - y1) * dy) / len : 0;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
}

function markAt(x, y) {
  /* Topmost first: what is drawn last is what the eye sees, so it is what
   * the click should get. */
  for (let i = marks.length - 1; i >= 0; i--) if (near(marks[i], x, y)) return marks[i];
  return null;
}

function handleAt(mark, x, y) {
  if (!mark) return null;
  const size = (HANDLE + 4) / scale;
  for (const h of handlesOf(mark)) {
    if (Math.abs(x - h.x) <= size && Math.abs(y - h.y) <= size) return h.id;
  }
  return null;
}

function select(mark) {
  selected = mark || null;
  if (selected) {
    /* The bar follows the selection, so the controls describe what is in
     * front of you rather than what you last drew. */
    if (selected.colour) setColour(selected.colour, true);
    if (selected.weight) setWeight(selected.weight, true);
    if (selected.fontSize) setFont(selected.fontSize, true);
    document.getElementById('fillBtn').classList.toggle('on',
      !!(selected.fill || selected.box));
  }
  paintButtons();
  redraw();
}

/* ---------------------------------------------------------------- pointer */

function at(event) {
  const rect = canvas.getBoundingClientRect();
  return { x: (event.clientX - rect.left) / scale, y: (event.clientY - rect.top) / scale };
}

canvas.addEventListener('pointerdown', (event) => {
  if (event.button !== 0) return;
  /* SPACE HELD MEANS PAN, NOT DRAW. Yielded before the pointer is captured,
   * so the stage's own handler below gets a clean drag - and before
   * commitTyping(), because panning is not a reason to finish a label. */
  if (spaceHeld) return;
  commitTyping();
  /* Capture so a stroke survives the pointer leaving the canvas - drawing an
   * arrow that ends past the edge of the picture is normal, and without this
   * the line stops dead at the border.
   *
   * GUARDED, because it throws on a pointer id the browser does not consider
   * active, and an exception here happens BEFORE the mark is made: the whole
   * tool silently does nothing. Found exactly that way - eight shapes drawn
   * in a test and an undo stack still empty. */
  try { canvas.setPointerCapture(event.pointerId); } catch (error) { /* no capture, still draws */ }
  const p = at(event);

  if (tool === 'select') {
    const grabbed = handleAt(selected, p.x, p.y);
    if (grabbed) {
      remember();
      drag = { how: 'resize', handle: grabbed, from: p, was: JSON.parse(JSON.stringify(selected)) };
      return;
    }
    const hit = markAt(p.x, p.y);
    select(hit);
    if (hit) {
      remember();
      drag = { how: 'move', from: p, was: JSON.parse(JSON.stringify(hit)) };
    }
    return;
  }

  if (tool === 'text') {
    /* A LABEL ALREADY HERE IS EDITED, NOT BURIED. Starting a new one on top
     * of an existing label is never what was meant, and having to switch to
     * the select tool and double-click to change a word is the kind of thing
     * that makes a tool feel like it is arguing with you.
     *
     * It is selected as well as opened, so Delete works on it the moment the
     * editing is finished, without changing tools. */
    const already = markAt(p.x, p.y);
    if (already && already.kind === 'text') {
      select(already);
      startTyping(already.x, already.y, already);
      return;
    }
    /* Not startTyping yet: a DRAG here means "this big", and that cannot be
     * known until the button comes up. A click still lands a caret - see
     * endDrag. */
    drag = { how: 'textbox', from: p, box: { x: p.x, y: p.y, w: 0, h: 0 } };
    return;
  }

  if (tool === 'step') {
    remember();
    steps += 1;
    marks.push({ kind: 'step', x: p.x, y: p.y, n: steps, colour: style.colour,
      radius: Math.max(12, style.fontSize * 0.62) });
    redraw();
    return;
  }

  if (tool === 'crop') {
    drag = { how: 'crop', from: p, box: { x: p.x, y: p.y, w: 0, h: 0 } };
    return;
  }

  remember();
  const fresh = freshMark(tool, p);
  marks.push(fresh);
  drag = { how: 'draw', mark: fresh, from: p };
  redraw();
});

function freshMark(kind, p) {
  const common = { kind, colour: style.colour, weight: style.weight };
  if (kind === 'pen') return Object.assign(common, { pts: [[p.x, p.y]] });
  if (kind === 'line' || kind === 'arrow') {
    return Object.assign(common, { x1: p.x, y1: p.y, x2: p.x, y2: p.y });
  }
  if (kind === 'blur') return { kind, x: p.x, y: p.y, w: 0, h: 0, amount: 12, colour: '#000' };
  if (kind === 'highlight') return { kind, x: p.x, y: p.y, w: 0, h: 0, colour: style.colour };
  return Object.assign(common, { x: p.x, y: p.y, w: 0, h: 0, fill: style.fill });
}

canvas.addEventListener('pointermove', (event) => {
  const p = at(event);
  if (!drag) {
    if (tool === 'select') {
      canvas.classList.toggle('moving',
        !!(handleAt(selected, p.x, p.y) || markAt(p.x, p.y)));
    }
    return;
  }

  if (drag.how === 'draw') {
    const mark = drag.mark;
    if (mark.kind === 'pen') mark.pts.push([p.x, p.y]);
    else if (mark.kind === 'line' || mark.kind === 'arrow') {
      /* Shift straightens it - the one shortcut nobody wants to be without
       * when drawing a line across a screenshot. */
      if (event.shiftKey) {
        if (Math.abs(p.x - mark.x1) > Math.abs(p.y - mark.y1)) { mark.x2 = p.x; mark.y2 = mark.y1; }
        else { mark.x2 = mark.x1; mark.y2 = p.y; }
      } else { mark.x2 = p.x; mark.y2 = p.y; }
    } else {
      mark.w = p.x - mark.x;
      mark.h = p.y - mark.y;
      if (event.shiftKey) {
        const side = Math.max(Math.abs(mark.w), Math.abs(mark.h));
        mark.w = Math.sign(mark.w || 1) * side;
        mark.h = Math.sign(mark.h || 1) * side;
      }
    }
    redraw();
    return;
  }

  if (drag.how === 'move') {
    shift(selected, drag.was, p.x - drag.from.x, p.y - drag.from.y);
    redraw();
    return;
  }

  if (drag.how === 'resize') {
    resize(selected, drag.was, drag.handle, p);
    redraw();
    return;
  }

  if (drag.how === 'textbox') {
    drag.box = { x: Math.min(drag.from.x, p.x), y: Math.min(drag.from.y, p.y),
      w: Math.abs(p.x - drag.from.x), h: Math.abs(p.y - drag.from.y) };
    redraw();
    ctx.save();
    ctx.strokeStyle = style.colour;
    ctx.setLineDash([6 / scale, 4 / scale]);
    ctx.lineWidth = 1 / scale;
    ctx.strokeRect(drag.box.x, drag.box.y, drag.box.w, drag.box.h);
    ctx.restore();
    return;
  }

  if (drag.how === 'crop') {
    drag.box = { x: Math.min(drag.from.x, p.x), y: Math.min(drag.from.y, p.y),
      w: Math.abs(p.x - drag.from.x), h: Math.abs(p.y - drag.from.y) };
    redraw();
    ctx.save();
    ctx.fillStyle = 'rgba(0,0,0,.45)';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.clearRect(drag.box.x, drag.box.y, drag.box.w, drag.box.h);
    ctx.drawImage(base, drag.box.x, drag.box.y, drag.box.w, drag.box.h,
      drag.box.x, drag.box.y, drag.box.w, drag.box.h);
    for (const mark of marks) drawMark(mark);
    ctx.strokeStyle = '#65c7da';
    ctx.lineWidth = 1 / scale;
    ctx.strokeRect(drag.box.x, drag.box.y, drag.box.w, drag.box.h);
    ctx.restore();
  }
});

function shift(mark, was, dx, dy) {
  if (mark.kind === 'line' || mark.kind === 'arrow') {
    mark.x1 = was.x1 + dx; mark.y1 = was.y1 + dy;
    mark.x2 = was.x2 + dx; mark.y2 = was.y2 + dy;
  } else if (mark.kind === 'pen') {
    mark.pts = was.pts.map((p) => [p[0] + dx, p[1] + dy]);
  } else {
    mark.x = was.x + dx; mark.y = was.y + dy;
  }
}

function resize(mark, was, handle, p) {
  if (mark.kind === 'line' || mark.kind === 'arrow') {
    if (handle === 'p1') { mark.x1 = p.x; mark.y1 = p.y; }
    else { mark.x2 = p.x; mark.y2 = p.y; }
    return;
  }
  const b = boundsOf(was);
  let left = b.x, top = b.y, right = b.x + b.w, bottom = b.y + b.h;
  if (handle.includes('w')) left = p.x;
  if (handle.includes('e')) right = p.x;
  if (handle.includes('n')) top = p.y;
  if (handle.includes('s')) bottom = p.y;
  const w = Math.max(4, right - left), h = Math.max(4, bottom - top);

  if (mark.kind === 'pen') {
    /* Scale the whole stroke about the box being dragged. */
    const sx = b.w ? w / b.w : 1, sy = b.h ? h / b.h : 1;
    mark.pts = was.pts.map((q) => [left + (q[0] - b.x) * sx, top + (q[1] - b.y) * sy]);
    return;
  }
  if (mark.kind === 'text') {
    mark.x = left; mark.y = top;
    if (was.fit) {
      /* A BOX-FITTED LABEL KEEPS FITTING ITS BOX. Scaling the font by the
       * height ratio instead would leave it no longer filling the box the
       * operator drew, the first time they touched it. */
      mark.fit = { w: w, h: h };
      mark.fontSize = fitFont(mark);
      setFont(Math.round(mark.fontSize), true);
      return;
    }
    /* TEXT SCALES, it does not stretch - a screenshot label set in squashed
     * type reads as a mistake. The font follows the height being dragged. */
    const grew = b.h ? h / b.h : 1;
    mark.fontSize = Math.max(8, Math.min(400, Math.round(was.fontSize * grew)));
    setFont(mark.fontSize, true);
    return;
  }
  if (mark.kind === 'step') {
    mark.radius = Math.max(8, Math.min(w, h) / 2);
    mark.x = left + w / 2; mark.y = top + h / 2;
    return;
  }
  mark.x = left; mark.y = top; mark.w = w; mark.h = h;
}

function endDrag(event) {
  if (!drag) return;
  const held = drag;
  drag = null;

  if (held.how === 'textbox') {
    /* A BOX, OR A CARET. Small enough and it was a click, not a drag -
     * and a click is the right gesture for a quick label at the slider's
     * size, so it is kept exactly as it was. */
    if (held.box.w > 12 && held.box.h > 12) {
      startTyping(held.box.x, held.box.y, null, held.box);
    } else {
      startTyping(held.from.x, held.from.y);
    }
    return;
  }

  if (held.how === 'crop') {
    if (held.box.w > 8 && held.box.h > 8) applyCrop(held.box);
    else redraw();
    return;
  }
  if (held.how === 'draw') {
    const mark = held.mark;
    /* A click that drew nothing leaves nothing behind - and must not leave
     * an undo step behind either. */
    const b = boundsOf(mark);
    const nothing = mark.kind === 'pen' ? mark.pts.length < 2 : (b.w < 3 && b.h < 3);
    if (nothing) {
      marks.pop();
      past.pop();
      paintButtons();
    } else if (tool !== 'pen') {
      /* Hand the new mark straight to the select tool: the next thing anyone
       * does to a fresh arrow is nudge it. */
      select(mark);
    }
  }
  redraw();
}

canvas.addEventListener('pointerup', endDrag);
canvas.addEventListener('pointercancel', endDrag);

/* -------------------------------------------------------------------- text */

function startTyping(x, y, existing, fitBox) {
  commitTyping();
  typingMark = existing || { kind: 'text', x, y, text: '', colour: style.colour,
    fontSize: style.fontSize, box: style.fill };
  /* A BOX WAS DRAWN: it, and not the slider, is the size from here on. */
  if (fitBox) {
    typingMark.fit = { w: fitBox.w, h: fitBox.h };
    typingMark.fontSize = fitFont(typingMark);
  }
  const rect = canvas.getBoundingClientRect();
  const holderRect = holder.getBoundingClientRect();
  typing.hidden = false;
  typing.value = typingMark.text;
  typing.style.left = ((rect.left - holderRect.left) + typingMark.x * scale) + 'px';
  typing.style.top = ((rect.top - holderRect.top) + typingMark.y * scale) + 'px';
  typing.style.color = typingMark.colour;
  sizeTyping();
  typing.focus();
  say(typingMark.fit
    ? 'Type the label \u2014 it grows to fill the box you drew. Enter commits it, '
      + 'Shift+Enter makes a new line, Escape throws it away.'
    : 'Type the label. Enter commits it, Shift+Enter makes a new line, Escape throws it away.');
}

function sizeTyping() {
  /* REFIT AS IT IS TYPED, so what is on screen while typing is what will be
   * drawn - the whole point of drawing a box was to stop guessing. */
  if (typingMark.fit) {
    typingMark.text = typing.value;
    typingMark.fontSize = fitFont(typingMark);
  }
  typing.style.fontSize = (typingMark.fontSize * scale) + 'px';
  typing.style.lineHeight = (typingMark.fontSize * 1.25 * scale) + 'px';

  if (typingMark.fit) {
    /* The box itself, so the operator is typing inside the thing they drew
     * rather than inside a field that happens to be near it. */
    typing.style.width = (typingMark.fit.w * scale) + 'px';
    typing.style.height = (typingMark.fit.h * scale) + 'px';
    return;
  }
  const lines = typing.value.split('\n');
  const longest = lines.reduce((n, l) => Math.max(n, l.length), 1);
  typing.style.width = Math.max(40, longest * typingMark.fontSize * scale * 0.62 + 14) + 'px';
  typing.style.height = (lines.length * typingMark.fontSize * 1.25 * scale + 6) + 'px';
}

typing.addEventListener('input', sizeTyping);
typing.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') { event.preventDefault(); cancelTyping(); }
  else if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); commitTyping(); }
  event.stopPropagation();
});
typing.addEventListener('blur', () => commitTyping());

function commitTyping() {
  if (!typingMark) return;
  const mark = typingMark;
  typingMark = null;
  typing.hidden = true;
  const text = typing.value.replace(/\s+$/, '');
  const already = marks.indexOf(mark);
  if (!text) {
    if (already >= 0) { remember(); marks.splice(already, 1); }
    redraw();
    return;
  }
  remember();
  mark.text = text;
  /* One last fit: the trailing whitespace stripped just above can change
   * which line is the widest, and the committed label must match what was
   * on screen a moment ago. */
  if (mark.fit) mark.fontSize = fitFont(mark);
  if (already < 0) marks.push(mark);
  select(mark);
}

function cancelTyping() {
  typingMark = null;
  typing.hidden = true;
  redraw();
}

/* Double-click a label to edit its words rather than redrawing it. */
/* Double-click edits a label from ANY tool. The text tool reaches the same
 * place with a single click - see pointerdown - so this is the road for when
 * the select tool is in hand. */
canvas.addEventListener('dblclick', (event) => {
  const p = at(event);
  const hit = markAt(p.x, p.y);
  if (hit && hit.kind === 'text') { select(hit); startTyping(hit.x, hit.y, hit); }
});

/* -------------------------------------------------------------------- crop */

function applyCrop(box) {
  remember();
  const cut = document.createElement('canvas');
  cut.width = Math.round(box.w);
  cut.height = Math.round(box.h);
  cut.getContext('2d').drawImage(base, Math.round(box.x), Math.round(box.y),
    cut.width, cut.height, 0, 0, cut.width, cut.height);
  const image = new Image();
  image.onload = () => {
    base = image;
    /* The marks move with the picture, or a crop would scatter every arrow
     * already placed. */
    for (const mark of marks) shift(mark, JSON.parse(JSON.stringify(mark)), -box.x, -box.y);
    fit();
    say('Cropped to ' + cut.width + '×' + cut.height + '.');
  };
  image.src = cut.toDataURL('image/png');
  pickTool('select');
}

/* ------------------------------------------------------------------ styles */

function setColour(value, quiet) {
  style.colour = value;
  document.getElementById('colour').value = value;
  if (!quiet && selected) { remember(); selected.colour = value; redraw(); }
}
function setWeight(value, quiet) {
  style.weight = Number(value);
  document.getElementById('weight').value = String(value);
  document.getElementById('weightSaid').textContent = String(value);
  if (!quiet && selected) { remember(); selected.weight = Number(value); redraw(); }
}
function setFont(value, quiet) {
  style.fontSize = Number(value);
  document.getElementById('fontSize').value = String(value);
  document.getElementById('fontSaid').textContent = String(value);
  if (!quiet && selected && selected.kind === 'text') {
    remember(); selected.fontSize = Number(value); redraw();
  }
  if (!quiet && selected && selected.kind === 'step') {
    remember(); selected.radius = Math.max(12, Number(value) * 0.62); redraw();
  }
}

document.getElementById('colour').addEventListener('input',
  (event) => setColour(event.target.value));
document.getElementById('weight').addEventListener('input',
  (event) => setWeight(event.target.value));
document.getElementById('fontSize').addEventListener('input',
  (event) => setFont(event.target.value));
document.getElementById('fillBtn').addEventListener('click', () => {
  style.fill = !style.fill;
  document.getElementById('fillBtn').classList.toggle('on', style.fill);
  if (selected) {
    remember();
    if (selected.kind === 'text') selected.box = style.fill;
    else selected.fill = style.fill;
    redraw();
  }
});

document.getElementById('undoBtn').addEventListener('click', undo);
document.getElementById('redoBtn').addEventListener('click', redo);
document.getElementById('deleteBtn').addEventListener('click', dropSelected);
document.getElementById('clearBtn').addEventListener('click', () => {
  if (!marks.length) return;
  remember();
  marks = [];
  steps = 0;
  select(null);
  redraw();
  say('Every mark removed. Ctrl+Z brings them back.');
});

function dropSelected() {
  if (!selected) return;
  remember();
  const where = marks.indexOf(selected);
  if (where >= 0) marks.splice(where, 1);
  select(null);
}

/* ------------------------------------------------------------------- going */

function flatten() {
  /* The handles are UI, not part of the picture. */
  const held = selected;
  selected = null;
  redraw();
  const url = canvas.toDataURL('image/png');
  selected = held;
  redraw();
  return url;
}

async function copyOut() {
  const url = flatten();
  let ok = false;
  try { ok = !!(api.copyImage && api.copyImage(url)); } catch (error) { ok = false; }
  say(ok ? 'The marked-up picture is on the clipboard.'
    : 'The clipboard would not take it.', !ok);
}

async function saveOut() {
  const url = flatten();
  try {
    const done = await api.shotSave(url);
    if (done && done.ok) say('Saved to ' + done.path);
    else if (done && done.canceled) say('Not saved.');
    else say((done && done.why) || 'It could not be saved.', true);
  } catch (error) {
    say(error.message, true);
  }
}

document.getElementById('copyBtn').addEventListener('click', copyOut);
document.getElementById('saveBtn').addEventListener('click', saveOut);

/* HOLD SPACE TO PAN, the convention every drawing tool shares - and the one
 * that matters here now that a 2680x1600 screenshot rarely fits the window.
 *
 * Its own pair of listeners rather than a branch in the shortcut handler
 * below, because this is a HELD gesture and not a keypress: it has to be
 * disarmed by a keyup, and by a blur, which a shortcut table has no place
 * for. */
window.addEventListener('keydown', (event) => {
  if (event.code !== 'Space') return;
  /* While a label is being typed, space is a SPACE. Stealing it would make
   * text with spaces in it impossible to write. */
  if (typingMark) return;
  /* Auto-repeat fires this for as long as the key is down. Arm once, but
   * suppress the default every time or the window scrolls under the pan. */
  event.preventDefault();
  if (spaceHeld) return;
  spaceHeld = true;
  stage.classList.add('handy');
});

window.addEventListener('keyup', (event) => {
  if (event.code !== 'Space') return;
  spaceHeld = false;
  stage.classList.remove('handy');
});

/* Alt-tab away with space down and the keyup never arrives, leaving the
 * editor armed in a mode with nothing on screen to explain it. */
window.addEventListener('blur', () => {
  spaceHeld = false;
  stage.classList.remove('handy');
});

/* Fit, from the toolbar and from the keyboard. `0` is what every other
 * viewer in this application uses for "show me the whole thing again". */
document.getElementById('fitBtn')?.addEventListener('click', () => {
  if (base) fit();
});

window.addEventListener('keydown', (event) => {
  if (typingMark) return;
  const meta = event.ctrlKey || event.metaKey;
  if (!meta && event.key === '0') {
    event.preventDefault();
    if (base) fit();
    return;
  }
  if (meta && event.key.toLowerCase() === 'z') {
    event.preventDefault();
    if (event.shiftKey) redo(); else undo();
    return;
  }
  if (meta && event.key.toLowerCase() === 'y') { event.preventDefault(); redo(); return; }
  if (meta && event.key.toLowerCase() === 'c') { event.preventDefault(); copyOut(); return; }
  if (meta && event.key.toLowerCase() === 's') { event.preventDefault(); saveOut(); return; }
  if (meta) return;
  if (event.key === 'Delete' || event.key === 'Backspace') {
    event.preventDefault(); dropSelected(); return;
  }
  if (event.key === 'Escape') { select(null); pickTool('select'); return; }
  const wanted = KEYS[event.key.toLowerCase()];
  if (wanted) { event.preventDefault(); pickTool(wanted); }
});

function say(text, bad) {
  const note = document.getElementById('say');
  note.textContent = text || '';
  note.classList.toggle('err', !!bad);
}

/* ------------------------------------------------------- the resolution */

/* THE SLIDER AND THE DROPDOWN.
 *
 * Every change resamples from the ORIGINAL bytes, never from what is on
 * screen: 2x of a 2x is not 4x of the original, it is a double
 * interpolation, and moving a slider back and forth would soften the picture
 * a little more each time.
 *
 * THE CEILING IS CAPPED FROM THE SOURCE. A canvas past roughly 268
 * megapixels - 2^28, the area limit - is created without complaint and comes
 * back BLANK. Measured in this build: a 1340x800 screenshot survives 14x
 * (210 MP) and fails at 16x (274 MP). Eight is the operator's ceiling and
 * fits comfortably, but the cap is computed anyway so a larger picture one
 * day cannot walk off the same cliff.
 */
const AREA = 240 * 1000 * 1000;      /* a margin under the 268 MP limit */
let source = { width: 0, height: 0 };
let times = 1;
let how = '';
let resampling = false;

function mostTimes() {
  const px = (source.width || 1) * (source.height || 1);
  const fits = Math.floor(Math.sqrt(AREA / px));
  return Math.max(1, Math.min(8, fits));
}

/* EVERY MARK MOVES WITH THE PICTURE.
 *
 * Marks are stored in picture coordinates, so changing the resolution
 * underneath them without touching them would leave every arrow pointing a
 * screen-width from the thing it was drawn against. Stroke weights and font
 * sizes go too, or the drawing would appear to thin out as it sharpened. */
function rescaleMarks(by) {
  if (!(by > 0) || by === 1) return;
  const FLAT = ['x', 'y', 'w', 'h', 'x1', 'y1', 'x2', 'y2',
    'radius', 'fontSize', 'weight'];
  for (const mark of marks) {
    for (const key of FLAT) {
      if (typeof mark[key] === 'number') mark[key] *= by;
    }
    if (Array.isArray(mark.pts)) {
      mark.pts = mark.pts.map((q) => [q[0] * by, q[1] * by]);
    }
    if (mark.fit) mark.fit = { w: mark.fit.w * by, h: mark.fit.h * by };
  }
  /* And the tool defaults, so the NEXT mark looks like the last one rather
   * than a hairline on a picture eight times the size. */
  setWeight(Math.max(1, Math.min(200, Math.round(style.weight * by))), true);
  setFont(Math.max(10, Math.min(600, Math.round(style.fontSize * by))), true);
}

function sayTimes() {
  const said = document.getElementById('timesSaid');
  if (said) said.textContent = times + '\u00d7';
  const slider = document.getElementById('times');
  if (slider) {
    slider.max = String(mostTimes());
    if (Number(slider.value) !== times) slider.value = String(times);
  }
}

async function resample(wantTimes, wantHow) {
  if (resampling) return;
  const asked = Math.max(1, Math.min(mostTimes(), Math.round(wantTimes)));
  const nextHow = wantHow || how;
  if (asked === times && nextHow === how) return;
  resampling = true;
  const wasTimes = times;
  say('Resampling to ' + asked + '\u00d7\u2026');
  try {
    const got = await api.shotResample({ times: asked, how: nextHow });
    if (!got || !got.ok) {
      say((got && got.why) || 'It could not be resampled.', true);
      return;
    }
    await new Promise((resolve, reject) => {
      const next = new Image();
      next.onload = () => { base = next; resolve(); };
      next.onerror = () => reject(new Error('the resampled picture would not load'));
      next.src = got.dataUrl;
    });
    times = got.times;
    how = got.how;
    /* The marks are in the OLD picture's coordinates until this runs. */
    rescaleMarks(times / wasTimes);
    fit();
    sayTimes();
    say(base.naturalWidth + '\u00d7' + base.naturalHeight + ' at ' + times
      + '\u00d7' + (got.why ? ' \u2014 ' + got.why : '')
      + ' \u00b7 Copy again to put it on the clipboard.', !!got.why);
  } catch (error) {
    say(error.message, true);
  } finally {
    resampling = false;
  }
}

document.getElementById('times')?.addEventListener('change', (event) => {
  resample(Number(event.target.value), how);
});

document.getElementById('times')?.addEventListener('input', (event) => {
  /* The readout follows the thumb; the work waits for it to be let go -
   * eight times a screenshot is a real amount of ffmpeg. */
  const said = document.getElementById('timesSaid');
  if (said) said.textContent = Math.round(Number(event.target.value)) + '\u00d7';
});

document.getElementById('how')?.addEventListener('change', (event) => {
  resample(times, event.target.value);
});

/* --------------------------------------------------------------------- fit */

/* Shown whole, always. A screenshot opened at 100% in a window smaller than
 * the tablet means the operator's first action is scrolling, and anything
 * they wanted to point at is probably the part off screen. */
function fit() {
  canvas.width = base.naturalWidth || base.width;
  canvas.height = base.naturalHeight || base.height;
  const room = stage.getBoundingClientRect();
  fitScale = Math.min(1, (room.width - 28) / canvas.width,
    (room.height - 28) / canvas.height);
  if (!isFinite(fitScale) || fitScale <= 0) fitScale = 1;
  zoomedByHand = false;
  apply(fitScale);
}

/* ------------------------------------------------------------------- zoom */

/* THE SAME `scale` THE WHOLE EDITOR ALREADY USES, moved.
 *
 * at() divides by it to turn a pointer into a picture coordinate, handles are
 * sized 1/scale so they stay constant on screen, and the selection dashes the
 * same. A CSS transform laid over the top would leave every one of those
 * describing the old size, and marks would land somewhere plausible and
 * wrong. */
const DEEPEST = 8;

function apply(next) {
  scale = Math.max(0.02, Math.min(DEEPEST, next));
  canvas.style.width = Math.round(canvas.width * scale) + 'px';
  canvas.style.height = Math.round(canvas.height * scale) + 'px';
  redraw();
  const said = document.getElementById('zoomSaid');
  if (said) {
    said.textContent = Math.round(scale * 100) + '%';
  }
}

/* Never smaller than the whole picture: below that there is nothing to see
 * and no way back that is obvious. */
function zoomTo(next, holdX, holdY) {
  const was = scale;
  const want = Math.max(fitScale, Math.min(DEEPEST, next));
  if (Math.abs(want - was) < 0.0001) return;

  /* Which picture pixel is under the cursor right now. */
  const before = canvas.getBoundingClientRect();
  const px = (holdX - before.left) / was;
  const py = (holdY - before.top) / was;

  apply(want);
  zoomedByHand = Math.abs(want - fitScale) > 0.0001;

  /* And scroll by however far that pixel moved. The stage scrolls already,
   * so the browser keeps this inside the picture for us. */
  const after = canvas.getBoundingClientRect();
  stage.scrollLeft += (after.left + px * scale) - holdX;
  stage.scrollTop += (after.top + py * scale) - holdY;
}

stage.addEventListener('wheel', (event) => {
  event.preventDefault();
  const room = stage.getBoundingClientRect();
  /* A fixed ratio per notch, so in and straight back out lands exactly where
   * it started rather than drifting. */
  const step = event.deltaY < 0 ? 1.25 : 1 / 1.25;
  zoomTo(scale * step,
    event.clientX || (room.left + room.width / 2),
    event.clientY || (room.top + room.height / 2));
}, { passive: false });

/* THE MIDDLE BUTTON PANS. The canvas's own pointerdown already ignores
 * anything but button 0, so this cannot start a stroke by accident. */
let scrolling = null;

stage.addEventListener('pointerdown', (event) => {
  /* Two ways in, one pan: the middle button any time, and the left button
   * while space is held. */
  if (event.button !== 1 && !(event.button === 0 && spaceHeld)) return;
  event.preventDefault();
  scrolling = { x: event.clientX, y: event.clientY,
    left: stage.scrollLeft, top: stage.scrollTop };
  stage.classList.add('panning');
  try { stage.setPointerCapture(event.pointerId); } catch (error) { /* fine */ }
});

stage.addEventListener('pointermove', (event) => {
  if (!scrolling) return;
  stage.scrollLeft = scrolling.left - (event.clientX - scrolling.x);
  stage.scrollTop = scrolling.top - (event.clientY - scrolling.y);
});

function stopScroll(event) {
  if (!scrolling) return;
  scrolling = null;
  stage.classList.remove('panning');
  try { stage.releasePointerCapture(event.pointerId); } catch (error) { /* fine */ }
}

stage.addEventListener('pointerup', stopScroll);
stage.addEventListener('pointercancel', stopScroll);
stage.addEventListener('auxclick', (event) => {
  /* Windows starts its own autoscroll on the middle button otherwise. */
  if (event.button === 1) event.preventDefault();
});

/* A HAND-SET ZOOM SURVIVES A RESIZE. Re-fitting on every resize would throw
 * away the view the operator had just framed, and dragging a window edge is
 * not a request to zoom out. */
window.addEventListener('resize', () => {
  if (!base) return;
  if (zoomedByHand) return;
  fit();
});

(async function open() {
  try {
    const got = await api.shotImage();
    if (!got || !got.ok) {
      say((got && got.why) || 'There was no picture to mark up.', true);
      return;
    }
    /* What the slider multiplies, what it is currently at, and the ways
     * it can be done - all three come from the main process so there is one
     * list of algorithms rather than two that drift. */
    source = got.source || { width: 0, height: 0 };
    times = got.times || 1;
    how = got.how || '';
    const picker = document.getElementById('how');
    if (picker && Array.isArray(got.ways)) {
      picker.textContent = '';
      for (const way of got.ways) {
        const choice = document.createElement('option');
        choice.value = way.id;
        choice.textContent = way.name;
        choice.title = way.note || '';
        picker.appendChild(choice);
      }
      picker.value = how;
    }
    sayTimes();

    const image = new Image();
    image.onload = () => {
      base = image;
      fit();
      paintButtons();
      say(image.width + '×' + image.height + ' at ' + times + '×'
        + ' · already on your clipboard · draw on it, then Copy again.');
    };
    image.onerror = () => say('The picture would not decode.', true);
    image.src = got.dataUrl;
  } catch (error) {
    say(error.message, true);
  }
})();
