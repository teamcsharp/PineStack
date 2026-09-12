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
      return {ok: !!(got && got.ok), where: (got && got.where) || '',
              detail: (got && got.detail) || '', kit: kit};
    }
    if (bridge) {
      return {ok: false, where: '',
              detail: 'this terminal cannot write files - the bridge has no saveText',
              kit: kit};
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


  /* ======================================================================
     AN MPC DRUM KIT, FOR AN MPC
     ======================================================================

     "Whenever I export a series of pads from the sampler as a preset, I want
      to save it in a format allowing me to reuse that as a kit on the MPC
      sampler or to import that and use it as a drum kit on the MPC Live 3."

     WHAT AN MPC KIT ACTUALLY IS. A folder holding one `.xpm` program - which
     is XML, not a binary - beside the WAV files it names. Drop the folder
     anywhere the MPC can see (its internal drive, an SD card, a USB stick),
     open the program from Browse, and it is a drum kit. The XPM refers to
     its samples by BARE NAME with no extension and no path, which is why
     everything has to sit in one folder together.

     THE PAD ORDER IS NOT THE SCREEN ORDER. An MPC numbers its pads from the
     BOTTOM-LEFT - pad A01 is the lowest left pad, instrument 0 - while this
     grid is laid out in reading order from the top-left. Exporting in screen
     order would put the kit upside down on the hardware. It is the same
     bottom-left-up walk that 16 LEVEL uses, so the two agree.

     WAV, ALWAYS. A pad may hold an mp3 - the station cuts spoken lines as
     mp3 - and an MPC program will not load one. So anything that is not
     already WAV is decoded and re-encoded here. The air takes are WAV
     already and pass through untouched.

     WHAT IS HONEST ABOUT THIS, AND WHAT IS NOT. The folder of WAVs is
     certain: named per pad, in pad order, loadable by hand on any sampler
     ever made. The `.xpm` is written to Akai's documented MPC 2.x program
     schema, which is what MPC Live/One/X/Key and the MPC Live III firmware
     read - but it has NOT been tested against real hardware from here,
     because there is no MPC on this network to test against. If the MPC
     refuses the program, the WAVs are still a kit you can build in thirty
     seconds, and the XPM is plain XML you can diff against one the MPC
     wrote itself. That is said here rather than discovered on the device. */

  var MPC_PADS = 16;          /* one MPC bank */
  var MPC_INSTRUMENTS = 128;  /* a drum program always declares all of them */

  /* Bottom-left up, the way the hardware counts. Screen index -> MPC pad. */
  function mpcOrder() {
    var out = [];
    for (var step = 0; step < MPC_PADS; step += 1) {
      var row = 3 - Math.floor(step / 4);
      var column = step % 4;
      out.push(row * 4 + column);     /* the screen index for this MPC pad */
    }
    return out;
  }

  function xmlSafe(text) {
    return String(text === undefined || text === null ? '' : text)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&apos;');
  }

  /* A name the MPC and every filesystem it might land on will accept. FAT32
   * on a USB stick is the strictest thing in the chain, so this is cut to
   * what FAT32 allows rather than to what Android does. */
  function mpcName(index, label) {
    var words = String(label || '').replace(/[^A-Za-z0-9 _-]+/g, ' ')
      .replace(/\s+/g, ' ').trim().slice(0, 40).trim();
    var number = (index + 1 < 10 ? '0' : '') + (index + 1);
    return ('Pad' + number + (words ? ' ' + words : '')).slice(0, 46);
  }

  /**
   * ONE INSTRUMENT of the program.
   *
   * Four layers exist whether or not they are used - that is how the format
   * is shaped, and a program with a short Layers list is one an MPC may
   * simply not open. Only layer 1 is ever filled here: these are one-shots
   * off the radio, not velocity-layered drums.
   */
  function instrument(number, sampleName, meta) {
    var has = !!sampleName;
    var gain = meta && isFinite(meta.gain) ? Math.max(0, Math.min(1, meta.gain)) : 1;
    /* The pad's tune is stored as a playback RATIO here and the MPC wants
     * semitones, so it is converted rather than copied - a pad tuned by ear
     * in the sampler should arrive tuned the same way on the hardware. */
    var semis = 0;
    if (meta && isFinite(meta.pitch) && meta.pitch > 0 && meta.pitch !== 1) {
      semis = Math.max(-36, Math.min(36, Math.round(12 * Math.log2(meta.pitch))));
    }
    var layers = '';
    for (var n = 1; n <= 4; n += 1) {
      var live = has && n === 1;
      layers +=
        '        <Layer number="' + n + '">\n' +
        '          <Active>' + (live ? 'True' : 'False') + '</Active>\n' +
        '          <Volume>' + (live ? gain.toFixed(6) : '1.000000') + '</Volume>\n' +
        '          <Pan>0.500000</Pan>\n' +
        '          <Pitch>0.000000</Pitch>\n' +
        '          <TuneSemi>' + (live ? semis : 0) + '</TuneSemi>\n' +
        '          <TuneFine>0</TuneFine>\n' +
        '          <VelStart>0</VelStart>\n' +
        '          <VelEnd>127</VelEnd>\n' +
        '          <SampleStart>0</SampleStart>\n' +
        '          <SampleEnd>0</SampleEnd>\n' +
        '          <Loop>False</Loop>\n' +
        '          <LoopStart>0</LoopStart>\n' +
        '          <LoopEnd>0</LoopEnd>\n' +
        '          <Direction>' +
          (live && meta && meta.reverse ? '1' : '0') + '</Direction>\n' +
        '          <SampleName>' + (live ? xmlSafe(sampleName) : '') + '</SampleName>\n' +
        '          <SampleFile></SampleFile>\n' +
        '          <SliceIndex>0</SliceIndex>\n' +
        '        </Layer>\n';
    }
    /* PLAY MODE. A radio line is a statement, not a hit: ONE SHOT lets it
     * finish when the pad is tapped instead of stopping the moment the
     * finger lifts, which is what NOTE ON would do to an eight-second
     * sentence. It matches this sampler's own default. */
    return '' +
      '      <Instrument number="' + number + '">\n' +
      '        <VolumeA>1.000000</VolumeA>\n' +
      '        <Pan>0.500000</Pan>\n' +
      '        <Mute>False</Mute>\n' +
      '        <Solo>False</Solo>\n' +
      '        <TuneSemi>0</TuneSemi>\n' +
      '        <TuneFine>0</TuneFine>\n' +
      '        <MuteGroup>0</MuteGroup>\n' +
      '        <TriggerMode>0</TriggerMode>\n' +
      '        <OneShot>True</OneShot>\n' +
      '        <Polyphony>0</Polyphony>\n' +
      '        <FilterType>0</FilterType>\n' +
      '        <Cutoff>1.000000</Cutoff>\n' +
      '        <Resonance>0.000000</Resonance>\n' +
      '        <VolumeAttack>0.000000</VolumeAttack>\n' +
      '        <VolumeDecay>0.000000</VolumeDecay>\n' +
      '        <VolumeRelease>0.000000</VolumeRelease>\n' +
      '        <Layers>\n' + layers +
      '        </Layers>\n' +
      '      </Instrument>\n';
  }

  function programXml(name, samples, metas) {
    var body = '';
    for (var i = 0; i < MPC_INSTRUMENTS; i += 1) {
      body += instrument(i, samples[i] || '', metas[i] || null);
    }
    return '<?xml version="1.0" encoding="UTF-8"?>\n' +
      '<MPCVObject>\n' +
      '  <Version>\n' +
      '    <File_Version>2.1</File_Version>\n' +
      '    <Application>MPC-V</Application>\n' +
      '    <Application_Version>2.11.6.6</Application_Version>\n' +
      '    <Platform>Linux</Platform>\n' +
      '  </Version>\n' +
      '  <Program type="Drum">\n' +
      '    <ProgramName>' + xmlSafe(name) + '</ProgramName>\n' +
      '    <Instruments>\n' + body +
      '    </Instruments>\n' +
      '    <PadNoteMap>\n' + padNoteMap() +
      '    </PadNoteMap>\n' +
      '    <ProgramPadsV2>\n' +
      '      <Version>1</Version>\n' +
      '    </ProgramPadsV2>\n' +
      '  </Program>\n' +
      '</MPCVObject>\n';
  }

  /* The MPC's own default note map: pad 0 is MIDI note 37 and it counts up.
   * Written out rather than left off, because a program with no map can load
   * with its pads silent to incoming MIDI. */
  function padNoteMap() {
    var out = '';
    for (var pad = 0; pad < MPC_INSTRUMENTS; pad += 1) {
      out += '      <PadNote number="' + pad + '">\n' +
             '        <Note>' + (37 + pad) + '</Note>\n' +
             '      </PadNote>\n';
    }
    return out;
  }

  /* ---- the audio ------------------------------------------------------- */

  /* AN MPC WILL NOT LOAD AN MP3, and the station cuts spoken lines as mp3
   * (libmp3lame -q:a 3). So anything that is not already a RIFF/WAVE is
   * decoded and re-encoded. Checked by MAGIC BYTES rather than by the stored
   * mime type: the type is whatever a Content-Type header claimed, and the
   * bytes are what is actually there. */
  function isWav(bytes) {
    if (!bytes || bytes.byteLength < 12) return false;
    var head = new Uint8Array(bytes, 0, 12);
    return head[0] === 0x52 && head[1] === 0x49 && head[2] === 0x46 && head[3] === 0x46
      && head[8] === 0x57 && head[9] === 0x41 && head[10] === 0x56 && head[11] === 0x45;
  }

  function toWav(bytes) {
    if (isWav(bytes)) return Promise.resolve(bytes);
    var engine = root.PineSamplerEngine;
    var ctx = engine && engine.context ? engine.context() : null;
    if (!ctx) return Promise.reject(new Error('no audio engine to convert with'));
    return ctx.decodeAudioData(bytes.slice(0)).then(function (buffer) {
      return encodeWav(buffer);
    });
  }

  /* Interleaved 16-bit PCM at the buffer's own rate. Stereo is kept where it
   * exists - an MPC is perfectly happy with it, and folding a music grab to
   * mono to save a third of the size would be throwing away the record. */
  function encodeWav(buffer) {
    var channels = Math.min(2, buffer.numberOfChannels);
    var frames = buffer.length;
    var rate = buffer.sampleRate;
    var data = [];
    for (var c = 0; c < channels; c += 1) data.push(buffer.getChannelData(c));
    var bytes = new ArrayBuffer(44 + frames * channels * 2);
    var view = new DataView(bytes);
    var text = function (at, s) {
      for (var i = 0; i < s.length; i += 1) view.setUint8(at + i, s.charCodeAt(i));
    };
    text(0, 'RIFF');
    view.setUint32(4, 36 + frames * channels * 2, true);
    text(8, 'WAVE');
    text(12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, channels, true);
    view.setUint32(24, rate, true);
    view.setUint32(28, rate * channels * 2, true);
    view.setUint16(32, channels * 2, true);
    view.setUint16(34, 16, true);
    text(36, 'data');
    view.setUint32(40, frames * channels * 2, true);
    var at = 44;
    for (var f = 0; f < frames; f += 1) {
      for (var ch = 0; ch < channels; ch += 1) {
        var v = Math.max(-1, Math.min(1, data[ch][f]));
        view.setInt16(at, v < 0 ? v * 0x8000 : v * 0x7fff, true);
        at += 2;
      }
    }
    return bytes;
  }

  /* ---- writing it out --------------------------------------------------- */

  function writeFile(folder, name, bytes, mime) {
    var bridge = root.pineDesktop;
    if (bridge && typeof bridge.saveBytes === 'function') {
      return Promise.resolve(bridge.saveBytes({
        folder: folder, name: name, mime: mime || 'application/octet-stream',
        base64: toBase64(bytes)
      }));
    }
    /* A DOWNLOAD IS INERT IN THE TABLET WEBVIEW, so falling back to one
     * there is not a fallback - it is a lie. This exporter did exactly that
     * once and reported "ok: true, 16 pads" for a kit that was never
     * written to disk. On a terminal with a bridge but no saveBytes, say so.
     */
    if (root.pineDesktop) {
      return Promise.resolve({
        ok: false, where: '',
        detail: 'this terminal cannot write files - the bridge has no saveBytes'
      });
    }
    /* The desktop, where a download is real. One file at a time, which is
     * what a browser will allow. */
    var blob = new Blob([bytes], {type: mime || 'application/octet-stream'});
    var url = URL.createObjectURL(blob);
    var link = document.createElement('a');
    link.href = url;
    link.download = name;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
    return Promise.resolve({ok: true, where: name});
  }

  /**
   * Export one bank as an MPC drum kit.
   *
   * @param which the bank index
   * @param name  the kit (and program) name
   * @param say   optional progress reporter - this writes seventeen files and
   *              a full bank of long grabs is tens of megabytes, so it is not
   *              instant and must not look stuck
   */
  async function exportMpc(which, name, say) {
    var api = sampler();
    if (!api) throw new Error('the sampler is not loaded');
    var kitName = String(name || 'Pine Box Kit').replace(/[^A-Za-z0-9 _-]+/g, ' ')
      .replace(/\s+/g, ' ').trim().slice(0, 40) || 'Pine Box Kit';
    /* Everything in ONE folder: the XPM names its samples with no path, so
     * they have to be beside it. */
    var folder = 'Pine Box/' + kitName;
    var layout = api.layout();
    var order = mpcOrder();
    var samples = [];
    var metas = [];
    var written = 0;

    for (var pad = 0; pad < MPC_PADS; pad += 1) {
      var screen = order[pad];
      var meta = layout[which][screen];
      if (!meta) { samples.push(''); metas.push(null); continue; }
      if (say) say('pad ' + (pad + 1) + ' of 16…');
      var record = null;
      try { record = await api.bytes(api.padKey(which, screen)); } catch (err) { record = null; }
      if (!record || !record.bytes) { samples.push(''); metas.push(null); continue; }
      var wav;
      try { wav = await toWav(record.bytes); } catch (err) {
        samples.push(''); metas.push(null); continue;
      }
      var stem = mpcName(pad, meta.label);
      var got = await writeFile(folder, stem + '.wav', wav, 'audio/wav');
      if (!got || got.ok === false) { samples.push(''); metas.push(null); continue; }
      samples.push(stem);
      metas.push(meta);
      written += 1;
    }
    for (var rest = MPC_PADS; rest < MPC_INSTRUMENTS; rest += 1) {
      samples.push('');
      metas.push(null);
    }

    if (say) say('writing the program…');
    var xml = programXml(kitName, samples, metas);
    var xmlBytes = new TextEncoder().encode(xml).buffer;
    /* NOT application/xml. MediaStore corrects a filename whose extension
     * does not match the MIME type it was given, so declaring the program as
     * XML had it written to disk as "<name>.xpm.xml" - a file the MPC will
     * never show, because it browses for .xpm. Measured exactly that.
     * octet-stream carries no opinion about the extension. */
    var program = await writeFile(folder, kitName + '.xpm', xmlBytes,
      'application/octet-stream');

    /* A note in the folder saying what this is and what is certain about it.
     * The operator is carrying this to another device; a README costs one
     * file and answers the question he will have there. */
    var readme =
      'PINE BOX FM - sampler kit "' + kitName + '"\n\n' +
      written + ' pads, exported ' + new Date().toISOString() + '\n\n' +
      'FOR AN MPC (Live / Live II / Live III / One / X / Key):\n' +
      '  Copy this whole folder to the MPC - internal drive, SD card or USB.\n' +
      '  Browse to it and open ' + kitName + '.xpm. The samples must stay in\n' +
      '  the same folder as the .xpm; the program names them without a path.\n\n' +
      'PAD ORDER: the MPC counts from the BOTTOM-LEFT (A01), this sampler\n' +
      '  draws from the top-left, and the export already accounts for that.\n' +
      '  Pad01 here is pad A01 there.\n\n' +
      'IF THE PROGRAM WILL NOT OPEN: the WAVs are plain 16-bit PCM and can be\n' +
      '  dropped onto pads by hand on any sampler. The .xpm is plain XML -\n' +
      '  compare it with one your MPC saved itself and the difference will be\n' +
      '  visible.\n';
    await writeFile(folder, 'READ ME.txt',
      new TextEncoder().encode(readme).buffer, 'text/plain');
    /* The program is the thing the MPC opens; if its name was corrected on
     * the way to disk the kit is unusable, so that is reported rather than
     * counted as success. */
    var wrote = (program && program.where) || '';
    if (wrote && wrote.indexOf('.xpm') >= 0 && !/\.xpm$/.test(wrote)) {
      return {ok: false, pads: written, folder: folder, where: wrote,
              program: kitName + '.xpm',
              detail: 'the program was renamed to ' + wrote.split('/').pop()
                + ' on the way to disk, so the MPC will not see it'};
    }

    return {
      ok: !!(program && program.ok !== false),
      pads: written,
      folder: folder,
      where: (program && program.where) || folder,
      program: kitName + '.xpm'
    };
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
    exportMpc: exportMpc,
    defaultName: defaultName
  };
  root.PineSamplerKits = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
