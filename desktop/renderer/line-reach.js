/* RIGHT-CLICK ANY LINE, ANYWHERE, AND INSPECT IT.
 *
 * "I want to be able to right click and inspect any element of dialogue from
 *  the script or the text view or in the booth or anywhere where there's text
 *  or dialogue, and I just want to be able to right click and have an inspect
 *  option that allows me to bring up a pop-up."
 *
 * ONE DELEGATED LISTENER, NOT ONE PER VIEW. This window already had three
 * separate right-click handlers - the marquee, the feed's tag rows, the
 * sampler's pads - each with its own menu and its own idea of what a line is.
 * Adding a fourth for every new list is how "anywhere" quietly becomes
 * "wherever somebody remembered". So the listener sits on the document and
 * walks UP from whatever was clicked looking for a line.
 *
 * THE MARKER IS data-line-id, WHICH ALREADY EXISTED. The marquee has been
 * stamping dataset.lineId / .say / .name / .who / .kind / .at on its items all
 * along; this adopts that convention rather than inventing a second one, so
 * the marquee works the moment this loads and anything else only has to set
 * the same attribute.
 *
 * A LIST THAT KNOWS ITS ROWS CAN SAY SO WITHOUT BEING REWRITTEN: call
 * pineReach.mark(element, row) and the row is carried on the element itself,
 * which is cheaper and more honest than re-deriving it from the DOM text.
 *
 * IT YIELDS. A view with a genuinely better menu for its own rows - the shot
 * editor over a screenshot region, the sampler over a pad - keeps it: those
 * call stopPropagation, and anything marked data-no-inspect is left alone
 * entirely. This is the floor, not a takeover.
 */
'use strict';

(function () {
  const api = window.pineDesktop || {};
  if (!api.inspectFlow) return;      /* nothing to open; stay out of the way */

  /* Rows handed over by mark(), keyed by the element so nothing is parsed
   * back out of the DOM. A WeakMap so a list redrawing does not leak. */
  const known = new WeakMap();

  let menu = null;

  function shut() {
    if (menu) { menu.remove(); menu = null; }
  }

  document.addEventListener('click', (event) => {
    if (menu && !menu.contains(event.target)) shut();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') shut();
  });

  /**
   * What line, if any, was right-clicked.
   *
   * Walks up because the click almost always lands on an inner <i> or <b>
   * rather than on the row that carries the identity.
   */
  function lineAt(node) {
    let el = node;
    while (el && el !== document.body) {
      if (el.dataset) {
        if (el.dataset.noInspect !== undefined) return null;
        const held = known.get(el);
        if (held) return { el, row: held };
        if (el.dataset.lineId) {
          return { el, row: {
            id: el.dataset.lineId,
            text: el.dataset.say || el.dataset.text || '',
            name: el.dataset.name || '',
            who: el.dataset.who || '',
            kind: el.dataset.kind || '',
            sid: el.dataset.sid || '',
            ts: Number(el.dataset.at || el.dataset.ts || 0)
          } };
        }
      }
      el = el.parentElement;
    }
    return null;
  }

  function item(label, can, go, why) {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = label;
    b.disabled = !can;
    if (why) b.title = why;
    if (can) b.addEventListener('click', () => { shut(); go(); });
    return b;
  }

  function open(atX, atY, row) {
    shut();
    menu = document.createElement('div');
    menu.className = 'popmenu reachmenu';

    const said = String(row.text || '');
    const head = document.createElement('div');
    head.className = 'reachWho';
    head.textContent = (row.name || row.who || 'this line')
      + (said ? ' — ' + said.slice(0, 48)
        + (said.length > 48 ? '…' : '') : '');
    menu.appendChild(head);

    menu.appendChild(item('Inspect this line', !!row.id,
      () => api.inspectFlow(row),
      'Everything the station knows about how it came to be'));
    menu.appendChild(item('Play it', !!row.id,
      () => api.inspectPlay && api.inspectPlay({ id: row.id })));
    menu.appendChild(item('Export it to mp3', !!row.id,
      () => api.inspectExport && api.inspectExport({ id: row.id, how: 'line' })));
    menu.appendChild(item('Export the conversation', !!(row.id && row.sid),
      () => api.inspectExport
        && api.inspectExport({ id: row.id, sid: row.sid, how: 'round' }),
      row.sid ? '' : 'The station kept no written round for this line'));

    const hr = document.createElement('hr');
    menu.appendChild(hr);
    menu.appendChild(item('Copy the text', !!said, () => {
      if (api.copyText) api.copyText(said);
    }));
    menu.appendChild(item('Copy its id', !!row.id, () => {
      if (api.copyText) api.copyText(String(row.id));
    }));

    document.body.appendChild(menu);
    /* Kept on screen - a menu opened near an edge would otherwise open off
     * it, and the feed lists run right to the window edge. */
    const room = document.body.getBoundingClientRect();
    const box = menu.getBoundingClientRect();
    menu.style.left = Math.min(atX, room.width - box.width - 6) + 'px';
    menu.style.top = Math.min(atY, room.height - box.height - 6) + 'px';
  }

  document.addEventListener('contextmenu', (event) => {
    const found = lineAt(event.target);
    if (!found) return;                /* not a line: the OS menu, as usual */
    event.preventDefault();
    open(event.clientX, event.clientY, found.row);
  });

  window.pineReach = {
    /** Carry a row on an element so right-click finds it without parsing. */
    mark(element, row) {
      if (!element || !row) return element;
      known.set(element, row);
      if (row.id) element.dataset.lineId = String(row.id);
      return element;
    },
    /** Mark a whole list at once, by index. */
    markAll(elements, rows) {
      const list = Array.from(elements || []);
      list.forEach((el, i) => { if (rows[i]) this.mark(el, rows[i]); });
      return list;
    },
    close: shut
  };
})();
