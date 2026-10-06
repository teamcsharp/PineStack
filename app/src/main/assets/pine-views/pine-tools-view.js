/* [tools-view] THE TOOLS VIEW - the portable popups, on the tablet's rail.
 *
 * The desk opens its tools as popups and the PiP lists every global with an
 * open() in its catalog; the tablet has a rail of views and no catalog. This is
 * the tablet's door: one TOOLS tab whose view lists every portable tool that is
 * loaded on this screen (The Works, the LLM command table, the hour flow), and
 * opens the chosen one inside the view with a Back bar - the tool's own
 * mount(host) road, nothing of the desk's. Anywhere else it is also a popup
 * (open()), so the PiP's catalog lists it too.
 */
(function (root) {
  'use strict';
  if (root.PineToolsView) return;
  var doc = root.document;
  var TOOLS = [
    {key: 'PineTheWorks', label: 'The Works', blurb: 'the rooms and the blocked book - how the dialogue gets made'},
    {key: 'PineLlmCommands', label: 'LLM command', blurb: 'every spoken command, what it does, how often it is used; add your own'},
    {key: 'PineHourFlow', label: 'The hour as a flowchart', blurb: 'the running order entry, node by node: add, remove, insert, extend, and the micro-exchanges inside a node'},
    {key: 'PineBlockedBook', label: 'The blocked book', blurb: 'every blocked case the ledgers hold'},
    {key: 'PineGazetteView', label: 'The Gazette', blurb: 'the paper as it stands'},
    {key: 'PineSupercutReview', label: 'Supercut studio', blurb: 'tell the SFX guy what to say; the saved supercuts'}
  ];
  function el(tag, cls, text) {
    var n = doc.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function available() {
    return TOOLS.filter(function (t) { var api = root[t.key]; return api && (typeof api.mount === 'function' || typeof api.open === 'function'); });
  }
  function mount(host, opts) {
    opts = opts || {};
    host.innerHTML = '';
    var wrap = el('div', 'ptv-wrap'); host.appendChild(wrap);
    var current = null;
    function list() {
      if (current && current.close) { try { current.close(); } catch (e) { /* gone */ } }
      current = null; wrap.innerHTML = '';
      var head = el('div', 'ptv-head'); head.append(el('b', '', 'Tools'), el('span', 'ptv-sub', 'the station\'s desks, on this screen'));
      wrap.appendChild(head);
      var grid = el('div', 'ptv-grid'); wrap.appendChild(grid);
      var tools = available();
      if (!tools.length) grid.appendChild(el('p', 'ptv-empty', 'No portable tool is loaded on this screen yet.'));
      tools.forEach(function (t) {
        var card = el('button', 'ptv-card'); card.type = 'button';
        card.append(el('b', '', t.label), el('span', '', t.blurb));
        card.addEventListener('click', function () { show(t); });
        grid.appendChild(card);
      });
    }
    function show(t) {
      wrap.innerHTML = '';
      var bar = el('div', 'ptv-bar');
      var back = el('button', 'ptv-back', 'Back'); back.type = 'button'; back.title = 'Back to the tools';
      back.addEventListener('click', list);
      bar.append(back, el('b', '', t.label)); wrap.appendChild(bar);
      var body = el('div', 'ptv-body'); wrap.appendChild(body);
      var api = root[t.key];
      try {
        if (typeof api.mount === 'function') current = api.mount(body, {onBack: list}) || null;
        else if (typeof api.open === 'function') { api.open({onBack: list}); list(); }
      } catch (e) { body.appendChild(el('p', 'ptv-empty', t.label + ' could not start: ' + (e.message || e))); }
    }
    list();
    return {close: function () { if (current && current.close) { try { current.close(); } catch (e) { /* gone */ } } wrap.remove(); }, list: list, show: function (key) { var t = TOOLS.filter(function (x) { return x.key === key; })[0]; if (t) show(t); }};
  }
  var popup = null;
  function open() {
    if (popup) { close(); return; }
    var shade = el('div', 'ptv-pop'); shade.id = 'pineToolsViewPop'; shade.setAttribute('role', 'dialog'); shade.setAttribute('aria-label', 'Tools');
    var box = el('div', 'ptv-box');
    var x = el('button', 'ptv-x', 'X'); x.type = 'button'; x.title = 'Close'; x.setAttribute('aria-label', 'Close the tools');
    x.addEventListener('click', close); box.appendChild(x);
    var host = el('div', ''); box.appendChild(host); shade.appendChild(box); doc.body.appendChild(shade);
    popup = {shade: shade, mounted: mount(host)};
    return popup.mounted;
  }
  function close() { if (!popup) return; try { popup.mounted.close(); } catch (e) { /* gone */ } popup.shade.remove(); popup = null; }
  root.PineToolsView = {mount: mount, open: open, close: close, tools: available, catalog: TOOLS};
})(typeof window !== 'undefined' ? window : this);
