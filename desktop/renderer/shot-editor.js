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
let drag = null;
let steps = 0;             /* the running number for the step counter */
let scale = 1;             /* picture pixels per screen pixel */

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
  { id: 'text', glyph: 'A', title: 'Text - drag a corner afterwards to scale it (T)' },
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
    const size = textSize(mark);
    return { x: mark.x, y: mark.y, w: size.w, h: size.h };
  }
  if (mark.kind === 'step') {
    const r = mark.radius;
    return { x: mark.x - r, y: mark.y - r, w: r * 2, h: r * 2 };
  }
  return norm(mark);
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
  for (const mark of marks) drawMark(mark);
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
    startTyping(p.x, p.y);
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
    /* TEXT SCALES, it does not stretch - a screenshot label set in squashed
     * type reads as a mistake. The font follows the height being dragged. */
    const grew = b.h ? h / b.h : 1;
    mark.fontSize = Math.max(8, Math.min(400, Math.round(was.fontSize * grew)));
    mark.x = left; mark.y = top;
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

let typingMark = null;

function startTyping(x, y, existing) {
  commitTyping();
  typingMark = existing || { kind: 'text', x, y, text: '', colour: style.colour,
    fontSize: style.fontSize, box: style.fill };
  const rect = canvas.getBoundingClientRect();
  const holderRect = holder.getBoundingClientRect();
  typing.hidden = false;
  typing.value = typingMark.text;
  typing.style.left = ((rect.left - holderRect.left) + typingMark.x * scale) + 'px';
  typing.style.top = ((rect.top - holderRect.top) + typingMark.y * scale) + 'px';
  typing.style.fontSize = (typingMark.fontSize * scale) + 'px';
  typing.style.lineHeight = (typingMark.fontSize * 1.25 * scale) + 'px';
  typing.style.color = typingMark.colour;
  sizeTyping();
  typing.focus();
  say('Type the label. Enter commits it, Shift+Enter makes a new line, Escape throws it away.');
}

function sizeTyping() {
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
  if (already < 0) marks.push(mark);
  select(mark);
}

function cancelTyping() {
  typingMark = null;
  typing.hidden = true;
  redraw();
}

/* Double-click a label to edit its words rather than redrawing it. */
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

window.addEventListener('keydown', (event) => {
  if (typingMark) return;
  const meta = event.ctrlKey || event.metaKey;
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

/* --------------------------------------------------------------------- fit */

/* Shown whole, always. A screenshot opened at 100% in a window smaller than
 * the tablet means the operator's first action is scrolling, and anything
 * they wanted to point at is probably the part off screen. */
function fit() {
  canvas.width = base.naturalWidth || base.width;
  canvas.height = base.naturalHeight || base.height;
  const room = stage.getBoundingClientRect();
  scale = Math.min(1, (room.width - 28) / canvas.width, (room.height - 28) / canvas.height);
  if (!isFinite(scale) || scale <= 0) scale = 1;
  canvas.style.width = Math.round(canvas.width * scale) + 'px';
  canvas.style.height = Math.round(canvas.height * scale) + 'px';
  redraw();
}

window.addEventListener('resize', () => { if (base) fit(); });

(async function open() {
  try {
    const got = await api.shotImage();
    if (!got || !got.ok) {
      say((got && got.why) || 'There was no picture to mark up.', true);
      return;
    }
    const image = new Image();
    image.onload = () => {
      base = image;
      fit();
      paintButtons();
      say(image.width + '×' + image.height
        + ' · already on your clipboard · draw on it, then Copy again.');
    };
    image.onerror = () => say('The picture would not decode.', true);
    image.src = got.dataUrl;
  } catch (error) {
    say(error.message, true);
  }
})();
