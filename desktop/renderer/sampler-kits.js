/* KITS: A BANK, OR ALL FIVE, AS ONE THING YOU CAN KEEP AND SWAP.
 *
 * "Allow me to export a pad worth of clips to a file that basically
 *  encompasses all of the clips that I can reload and save as preferences
 *  that I can export and import into the software."
 *
 * "I want to be able to export either a page worth of samples or an entire
 *  series of samples from all five pages and have that saved as a preset that
 *  I can jump between with an icon at the top of the screen. I want to be able
 *  to save and store presets and load them and jump between them."
 *
 * THE BYTES TRAVEL, NOT REFERENCES. This is the whole point and it is worth
 * being explicit about, because storing ids would be far smaller and would be
 * useless: a line id resolves for only 48 hours (AIRLOG_KEEP_S) and the media
 * is then swept, so a kit full of references would quietly rot into a grid of
 * dead pads. A kit carries the audio. It is therefore large - a full five-bank
 * kit is tens of megabytes - and it works with the station switched off,
 * which is the reason the sampler holds its own bytes at all.
 *
 * WHY BASE64 IN JSON RATHER THAN A ZIP. A zip needs a library; the renderer
 * has none bundled and the CDN allowlist does not reach the tablet's WebView.
 * Base64 costs a third in size on something already measured in megabytes and
 * buys a file that is one `JSON.parse` away from readable, diffable and
 * repairable by hand. For a format the operator is meant to keep, that trade
 * is the right way round.
 *
 * PRESETS LIVE IN THE BROWSER, FILES LIVE WHEREVER HE PUTS THEM. Saving a
 * preset is instant and local (IndexedDB, beside the pads themselves).
 * Exporting writes a file through the bridge on a terminal that has one, and
 * falls back to a download elsewhere. They are the same object either way, so
 * a preset can be exported and an import can become a preset.
 */
(function (root) {
  'use strict';

  var DB = 'pine-sampler';
  var STORE = 'kits';
  var VERSION = 1;

  function sampler() { return root.PineSampler || null; }

  /* ------------------------------------------------------------- the store */

  /* A SEPARATE OBJECT STORE IN THE SAMPLER'S OWN DATABASE. Opening it with a
   * higher version than sampler.js uses would trigger its upgrade path on
   * every load and fight it; instead this opens whatever exists and creates
   * the store only if the sampler's own upgrade has not already run. */
  function open() {
    return new Promise(function (ok, no) {
      var request = root.indexedDB.open(DB);
      request.onerror = function () { no(request.error); };
      request.onsuccess = function () {
        var db = request.result;
        if (db.objectStoreNames.contains(STORE)) { ok(db); return; }
        /* Not there yet - reopen one version up and add it. */
        var next = db.version + 1;
        db.close();
        var bump = root.indexedDB.open(DB, next);
        bump.onupgradeneeded = function () {
          var inner = bump.result;
          if (!inner.objectStoreNames.contains(STORE)) inner.createObjectStore(STORE);
        };
        bump.onerror = function () { no(bump.error); };
        bump.onsuccess = function () { ok(bump.result); };
      };
    });
  }

  function tx(mode, run) {
    return open().then(function (db) {
      return new Promise(function (ok, no) {
        var t = db.transaction(STORE, mode);
        var store = t.objectStore(STORE);
        var out = run(store);
        t.oncomplete = function () { db.close(); ok(out && out.result !== undefined ? out.result : out); };
        t.onerror = function () { db.close(); no(t.error); };
      });
    });
  }

  function put(name, kit) { return tx('readwrite', function (s) { return s.put(kit, name); }); }
  function get(name) { return tx('readonly', function (s) { return s.get(name); }); }
  function drop(name) { return tx('readwrite', function (s) { return s.delete(name); }); }
  function names() { return tx('readonly', function (s) { return s.getAllKeys(); }); }

  /* --------------------------------------------------------- making a kit */

  /* @param which a bank index, or null for every bank. */
  async function build(which) {
    var api = sampler();
    if (!api) throw new Error('the sampler is not loaded');
    var layout = api.layout();
    var banks = which === null || which === undefined
      ? layout.map(function (_, i) { return i; })
      : [which];
    var kit = {
      pine: 'sampler-kit', version: VERSION,
      made: new Date().toISOString(),
      banks: {}, pads: 0, bytes: 0
    };
    for (var b = 0; b < banks.length; b += 1) {
      var index = banks[b];
      var into = [];
      for (var p = 0; p < layout[index].length; p += 1) {
        var meta = layout[index][p];
        if (!meta) { into.push(null); continue; }
        var record = null;
        try { record = await api.bytes(api.padKey(index, p)); } catch (err) { record = null; }
        if (!record || !record.bytes) {
          /* THE PAD IS NAMED BUT THE AUDIO IS GONE. Said out loud in the kit
           * rather than dropped silently, so an import can explain a hole
           * instead of presenting a shorter bank as if it were complete. */
          into.push({meta: meta, missing: true});
          continue;
        }
        into.push({
          meta: meta,
          type: record.type || 'audio/wav',
          audio: toBase64(record.bytes)
        });
        kit.pads += 1;
        kit.bytes += record.bytes.byteLength || 0;
      }
      kit.banks[String(index)] = into;
    }
    return kit;
  }

  /* ------------------------------------------------------- laying one down */

  /**
   * @param kit    a kit object
   * @param onto   bank index to load a single-bank kit into, or null to put
   *               every bank back where it came from
   * @param merge  true keeps pads the kit has nothing for; false clears them
   */
  async function apply(kit, onto, merge) {
    var api = sampler();
    if (!api) throw new Error('the sampler is not loaded');
    if (!kit || kit.pine !== 'sampler-kit') throw new Error('that is not a sampler kit');
    var layout = api.layout();
    var keys = Object.keys(kit.banks || {});
    if (!keys.length) throw new Error('that kit is empty');
    var single = keys.length === 1;
    var landed = 0, holes = 0;

    for (var k = 0; k < keys.length; k += 1) {
      var from = keys[k];
      var target = (single && onto !== null && onto !== undefined) ? onto : Number(from);
      if (!layout[target]) continue;
      var pads = kit.banks[from] || [];
      for (var p = 0; p < pads.length && p < layout[target].length; p += 1) {
        var slot = pads[p];
        var key = api.padKey(target, p);
        if (!slot) {
          if (!merge) {
            await api.forget(target, p);
          }
          continue;
        }
        if (slot.missing || !slot.audio) { holes += 1; continue; }
        var bytes = fromBase64(slot.audio);
        await putPad(api, key, target, p, bytes, slot);
        landed += 1;
      }
    }
    api.save();
    api.repaint();
    return {pads: landed, missing: holes};
  }

  async function putPad(api, key, bankIndex, pad, bytes, slot) {
    /* There is no public "load these bytes" seam on the sampler, so the kit
     * writes through the same two doors the sampler itself uses - its store
     * and its engine - and then hands it the metadata. Reaching in through
     * layout() is deliberate and narrow: one line, and it is the object the
     * sampler already publishes for exactly this. */
    var engine = root.PineSamplerEngine || root.pineSampler;
    await sampler().put(key, {bytes: bytes, type: slot.type || 'audio/wav'});
    await engine.load(key, bytes);
    var meta = Object.assign({}, slot.meta || {});
    meta.seconds = engine.seconds(key);
    api.layout()[bankIndex][pad] = meta;
    api.applySettings(key, meta);
  }

  /* ------------------------------------------------------------- transport */

  function toBase64(buffer) {
    var view = new Uint8Array(buffer);
    var out = '';
    /* In chunks: String.fromCharCode.apply on a multi-megabyte array blows
     * the argument limit and throws, which is a crash at the exact moment the
     * operator is trying to save his work. */
    for (var i = 0; i < view.length; i += 0x8000) {
      out += String.fromCharCode.apply(null, view.subarray(i, i + 0x8000));
    }
    return root.btoa(out);
  }

  function fromBase64(text) {
    var binary = root.atob(text);
    var out = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i += 1) out[i] = binary.charCodeAt(i);
    return out.buffer;
  }

  /* ------------------------------------------------------------- the files */

  async function exportKit(which, name) {
    var kit = await build(which);
    kit.name = name || defaultName(which);
    var text = JSON.stringify(kit);
    var file = kit.name.replace(/[^\w .()-]+/g, '_') + '.pinekit.json';
    var bridge = root.pineDesktop;
    if (bridge && typeof bridge.saveText === 'function') {
      var got = await bridge.saveText({name: file, text: text, where: 'downloads'});
      return {ok: !!(got && got.ok), where: (got && got.where) || '', kit: kit};
    }
    /* A plain download, for the desktop. This road does NOT work inside the
     * tablet WebView - an <a download> is inert there - which is why the
     * bridge above exists rather than this being the only way out. */
    var blob = new Blob([text], {type: 'application/json'});
    var url = URL.createObjectURL(blob);
    var link = document.createElement('a');
    link.href = url;
    link.download = file;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
    return {ok: true, where: file, kit: kit};
  }

  function importFile() {
    return new Promise(function (ok, no) {
      var input = document.createElement('input');
      input.type = 'file';
      input.accept = '.json,application/json';
      input.addEventListener('change', function () {
        var file = input.files && input.files[0];
        if (!file) { no(new Error('nothing was chosen')); return; }
        var reader = new FileReader();
        reader.onload = function () {
          try { ok(JSON.parse(String(reader.result))); }
          catch (err) { no(new Error('that file is not a kit: ' + err.message)); }
        };
        reader.onerror = function () { no(reader.error); };
        reader.readAsText(file);
      });
      input.click();
    });
  }

  function defaultName(which) {
    var when = new Date();
    var stamp = when.toISOString().slice(0, 16).replace('T', ' ');
    return (which === null || which === undefined)
      ? 'all banks ' + stamp
      : 'bank ' + (which + 1) + ' ' + stamp;
  }

  var api = {
    build: build, apply: apply,
    save: async function (name, which) {
      var kit = await build(which);
      kit.name = name;
      await put(name, kit);
      return kit;
    },
    load: get, forget: drop, list: names,
    exportKit: exportKit, importFile: importFile,
    defaultName: defaultName
  };
  root.PineSamplerKits = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
