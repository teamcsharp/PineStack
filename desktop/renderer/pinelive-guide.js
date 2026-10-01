/* PINELIVE - THE TROUBLESHOOTER'S KNOWLEDGE AND ITS DRAWINGS.
 *
 * "I want a detailed flowchart and imaged based troubleshooter and ui
 *  referencing the manual with imagery and infographics guiding me through
 *  getting my audio connected to the pine agent to broadcast."
 *
 * Three things live here, none of which makes a request of its own:
 *
 *   1. THE DEVICE PROFILES - which pages of which manual answer which
 *      check. Nothing below is manual text: every quotation shown on screen
 *      is read from the station at the moment it is shown -
 *        the Library shelf   GET /api/manuals/page/<slug>/<n>
 *                            (the KOII EP133 Notebook, a PDF on the shelf)
 *        the gear corpus     GET /api/te/manual/<slug>
 *                            (Teenage Engineering's own online guide, with
 *                             its illustrations at /api/te/asset/<slug>/<n>)
 *      A profile only says WHERE to look: a page number, an image name and
 *      a phrase to centre the quotation on. If the station cannot answer,
 *      the page reference is shown bare - nothing is filled in.
 *
 *   2. THE FLOWCHART - the station's ordered checks
 *      (GET /api/pinelive/troubleshoot, CONTRACT.md section 3) drawn as a
 *      chain of questions, each lit by its result. The first `fail` is the
 *      one to fix; everything after it waits on it and is drawn dimmed.
 *
 *   3. THE CONNECTION INFOGRAPHIC - the road the sound takes, from the
 *      instrument to the listeners and to the QuickSwap folder, each leg
 *      coloured by the check that grades it.
 *
 * Both drawings are inline SVG made here, in the panel's own colours.
 */
(function (root) {
  'use strict';

  var NS = 'http://www.w3.org/2000/svg';

  /* ------------------------------------------------------------ profiles */

  /* `lib` rows point into the Library's KOII EP133 Notebook (PDF page n,
   * which prints a different number in its own corner - the heading of
   * each page starts with the printed number, and that is what is shown).
   * `guide` rows point into the gear corpus copy of TE's online guide and
   * usually carry the guide's own illustration. */
  var PROFILES = {
    'ep-133': {
      id: 'ep-133',
      name: 'EP-133 K.O. II',
      short: 'K.O. II',
      match: /ep[\s‐-―-]?133|k\.?\s?o\.?\s?(ii|2)\b|koii|ko2/i,
      guide: 'ep-133',
      library: /koii|ep[\s-]?133/i,
      hero: {guide: 3, image: '003-hero.svg'},
      port: 'USB-C port, top side',
      steps: {
        usb: [
          {guide: 93, image: '173-output-example.svg', find: 'connect ko2 directly'},
          {guide: 86, image: '166-1-hardware-overview.svg', find: 'top side'},
          {guide: 182, image: '357-usb.svg', find: 'usb-c cable'},
          {lib: 23, find: 'USB-C Connection can interface'},
          {lib: 17, find: 'USB communication is connected'},
          {lib: 197, find: 'data compatible cable'}
        ],
        alsa: [
          {guide: 209, image: '367-os-2-5.svg', find: 'class compliant USB audio host'},
          {lib: 10, find: 'USB Audio routed in/out'},
          {lib: 187, find: '2-In/2-Out'}
        ],
        'class': [
          {lib: 187, find: 'class compliant'},
          {guide: 209, image: '367-os-2-5.svg', find: 'any class compliant'}
        ],
        capture: [
          {lib: 188, find: "'EP-133 2In/2Out'"},
          {lib: 187, find: '2-In/2-Out'}
        ],
        signal: [
          {lib: 186, find: 'The output is the master out'},
          {guide: 93, image: '173-output-example.svg', find: 'record sound straight'},
          {lib: 19, find: 'communicating to / from a computer'}
        ],
        level: [
          {lib: 14, find: 'Main output audio level'},
          {lib: 15, find: 'Main Volume Knob'},
          {lib: 186, find: 'Audio out level set by main'}
        ]
      }
    },
    'ep-136': {
      id: 'ep-136',
      name: 'EP-136 K.O.-sidekick',
      short: 'sidekick',
      match: /ep[\s‐-―-]?136|sidekick/i,
      guide: 'ep-136',
      library: null,
      hero: {guide: 2, image: '002-hero.svg'},
      port: 'USB-C port, top side',
      steps: {
        usb: [
          {guide: 42, image: '076-inputs.svg', find: 'top side'},
          {guide: 64, image: '097-usb.svg', find: 'usb-c cable'},
          {guide: 62, image: '095-switch-on.svg', find: 'power-switch'},
          {guide: 63, image: '096-on.svg', find: 'led screen'}
        ],
        alsa: [
          {guide: 50, find: 'audio interface'},
          {guide: 78, find: 'usb audio 2.0'},
          {guide: 65, find: 'firmware'}
        ],
        'class': [
          {guide: 78, find: 'usb audio 2.0'}
        ],
        capture: [
          {guide: 85, find: '48khz'},
          {guide: 78, find: 'usb audio 2.0'}
        ],
        signal: [
          {guide: 42, image: '077-inputs.svg', find: '3.5 mm stereo inputs'},
          {guide: 46, image: '082-input-example.svg', find: 'two ko2'},
          {guide: 25, image: '042-the-faders.svg', find: 'moved all the way down'},
          {guide: 69, image: '099-checkout-menu.svg', find: 'signal flow'}
        ],
        level: [
          {guide: 22, image: '028-the-gain-knob.svg', find: 'turn the gain knob'},
          {guide: 25, find: 'check level'}
        ]
      }
    }
  };
  /* [plsidekick] The operator's interface is the K.O. Sidekick (EP-136,
   * USB 2367:9420), not the K.O. II sampler (2026-10-01): a bare
   * Teenage Engineering id falls to its pages. */
  var DEFAULT_PROFILE = 'ep-136';

  /** Which profile a detected device (or a label) belongs to. The USB name
   *  wins over the station's friendly label: the label is a setting, the
   *  USB name is what the hardware says it is. */
  function profileFor(device) {
    if (!device) return null;
    /* The station's name for it first - it carries the operator's word for
     * what is plugged in - then what the USB descriptor says. */
    var names = typeof device === 'string' ? [device]
      : [device.name, device.label, device.usb_name, device.card_id, device.id];
    for (var i = 0; i < names.length; i += 1) {
      var n = String(names[i] || '');
      if (!n) continue;
      if (PROFILES['ep-136'].match.test(n)) return 'ep-136';
      if (PROFILES['ep-133'].match.test(n)) return 'ep-133';
    }
    if (typeof device === 'object' && /^2367:/i.test(String(device.usb_id || ''))) return DEFAULT_PROFILE;
    return null;
  }

  /* -------------------------------------------- [pldetect] detection */

  /** The instrument on the USB list. The USB descriptor decides: only a
   *  row whose usb_name (or a 2367: Teenage Engineering usb_id) matches a
   *  known profile can BE the instrument - a headset dongle, alone on the
   *  bus, is still not it. Among matching rows, ready beats busy, and
   *  more channels at a higher rate win. Null when no such row can
   *  capture: "found nothing" is the honest answer, never the best
   *  stranger. */
  function pickInstrument(devices) {
    var list = (devices && devices.usb) || [];
    var best = null, bestScore = -1;
    for (var i = 0; i < list.length; i += 1) {
      var d = list[i];
      if (!d || !d.capture) continue;
      var byUsb = profileFor(String(d.usb_name || ''))
        || (/^2367:/i.test(String(d.usb_id || '')) ? DEFAULT_PROFILE : null);
      if (!byUsb) continue;
      var rate = 0;
      if (Array.isArray(d.rates)) {
        for (var j = 0; j < d.rates.length; j += 1) rate = Math.max(rate, Number(d.rates[j]) || 0);
      }
      var score = (d.status === 'ready' ? 10000 : 0)
        + (Number(d.channels) || 0) * 100 + Math.min(99, Math.round(rate / 1000));
      if (score > bestScore) { bestScore = score; best = d; }
    }
    return best;
  }

  /** Every other capture on the bus - the rows to name honestly as
   *  not-the-instrument (the Nordic dongle, a webcam's mic). */
  function notInstrument(devices, pick) {
    var list = (devices && devices.usb) || [];
    var out = [];
    for (var i = 0; i < list.length; i += 1) {
      var d = list[i];
      if (!d || !d.capture) continue;
      if (pick && d.id === pick.id) continue;
      out.push(d);
    }
    return out;
  }

  /** The station's friendly label and the USB descriptor can disagree (the
   *  host labelled 2367:9420 "EP-133 K.O. II" until [plsidekick]; the descriptor says
   *  "Teenage Engineering EP-136"). One honest paragraph; '' when there is
   *  nothing to say. `shownProfile` is the profile whose pages are on
   *  screen. */
  function mismatchNote(dev, shownProfile) {
    if (!dev) return '';
    var byUsb = dev.usb_name ? profileFor(String(dev.usb_name)) : null;
    var byName = (dev.name || dev.label) ? profileFor(String(dev.name || dev.label)) : null;
    if (!byUsb) return '';
    var parts = [];
    if (byName && byName !== byUsb) {
      parts.push('The station labels this device "' + (dev.name || dev.label) + '" (the ' + PROFILES[byName].short
        + ') but its USB descriptor says "' + dev.usb_name + '"' + (dev.usb_id ? ' (USB ' + dev.usb_id + ')' : '')
        + (dev.channels ? ', delivering ' + dev.channels + ' channels' : '') + '.');
      parts.push(PROFILES[byUsb].name + ' is '
        + (byUsb === 'ep-136' ? 'the K.O.-sidekick, which its guide calls an 8 in / 4 out USB audio interface'
          : 'the K.O. II, which its notebook calls a 2-in/2-out USB audio interface')
        + '; the descriptor is what the hardware says it is.');
    }
    if (PROFILES[shownProfile] && shownProfile !== byUsb) {
      parts.push('The manual pages shown here are the ' + PROFILES[shownProfile].name + '\'s; if the '
        + PROFILES[byUsb].short + ' is what is plugged into the DGX, its pages are the ones to follow.');
    }
    return parts.join(' ');
  }

  /* What the maker's own pages say to SET on the device for USB audio into
   * a computer - and, just as loudly, what they do NOT say. Nothing below
   * is manual text: `quotes` rows are page numbers and find-phrases, and
   * the words on screen are read from the station's manual routes at the
   * moment they are shown. The `absences` lines are the station's own
   * honest statements about what those routes nowhere document. */
  var DEVICE_SETTINGS = {
    'ep-136': {
      summary: 'Nothing to set on the device. Its guide documents no USB-audio setting at all: plugged into the DGX with a data cable and switched on, the K.O.-sidekick IS the 8 in / 4 out interface.',
      quotes: [
        {guide: 50, find: 'usb-c port allows', why: 'The USB-C port is the interface'},
        {guide: 78, find: 'usb audio 2.0', why: 'Class compliant - nothing to install'},
        {guide: 64, image: '097-usb.svg', find: 'usb-c cable', why: 'Cable and power (USB-IF, 5 V / 1 A)'},
        {guide: 62, image: '095-switch-on.svg', find: 'power-switch', why: 'Switch it on'},
        {guide: 73, find: 'system button under the battery lid', why: 'The system menu - no USB-audio entry is documented in it'}
      ],
      absences: [
        'No device-side USB-audio setting exists in its guide: no on/off, no mode, no routing choice. There is nothing to hunt for.',
        'The guide nowhere says which of the 8 USB channels carry the main mix. Finding the pair is the level meter\'s job (Input, Channel pair), not the manual\'s.',
        'No sample rate or bit depth for USB audio is documented on the device. (The DGX observes it as 8 ch at 48 kHz - ALSA\'s observation, not a manual fact.)'
      ]
    },
    'ep-133': {
      summary: 'Nothing to set for USB audio OUT of the K.O. II: plug it in and choose it on the computer. The one documented USB setting on the device - the REC/MON input route - governs the other direction, computer audio INTO the K.O. II.',
      quotes: [
        {guide: 209, find: 'class compliant USB audio host', why: 'Plug in; the selecting happens on the computer'},
        {lib: 188, find: "'EP-133 2In/2Out'", why: 'The computer side of the selection'},
        {lib: 108, find: 'usb audio input route', why: 'REC / MON (quick codes 510 / 511) - the computer-into-K.O. II direction only'},
        {lib: 107, find: 'feedback loops', why: 'Both directions share one cable'}
      ],
      absences: [
        'For USB audio OUT the notebook documents no device-side setting: "just plug KO2 into your phone or computer and select it as an input or output" is the whole procedure.',
        'The SMP > USB choice (REC, the default, or MON; quick codes 510 / 511) only decides where COMPUTER audio is heard on the K.O. II - the send direction has no setting.'
      ]
    }
  };

  /* The station's own steps, per check. These are about the STATION (the
   * host service, the capture, the air, the cuts, the courier) - never
   * about the instrument, which is the manual's job. `ctx` carries the
   * state, the device and the profile so a step can name real numbers. */
  function stepsFor(id, ctx) {
    ctx = ctx || {};
    var st = ctx.state || {};
    var src = st.source || {};
    var dev = ctx.device || {};
    var prof = PROFILES[ctx.profile] || PROFILES[DEFAULT_PROFILE];
    var pair = Array.isArray(src.channel_pair) ? src.channel_pair.join('+') : '1+2';
    var chans = Number(dev.channels || src.channels) || 0;
    var rec = st.recording || {};
    switch (id) {
      case 'host': return [
        'The PineLive host service runs on the DGX Spark beside the station and owns the capture. Without it the station cannot open the ' + prof.short + ' at all.',
        (st.host && st.host.why) ? 'The station says: ' + st.host.why : 'The station has not heard from it recently.',
        'Starting it is a job on the DGX itself, not something this screen can do. Everything below waits on it.'
      ];
      case 'usb': return [
        'Use a USB-C cable that carries data. A charge-only cable powers the ' + prof.short + ' but the DGX never sees it.',
        'Plug the ' + prof.short + '\'s ' + prof.port + ' straight into a USB port on the DGX Spark - no hub while you are finding the fault.',
        'Switch it on, then press Scan again. The station lists every USB audio device the DGX can see.'
      ];
      case 'alsa': return [
        'The DGX sees the USB device, but no sound card came up for it.',
        'Unplug it, wait three seconds, plug it back in and Scan again.',
        prof.id === 'ep-133' ? 'USB audio arrived on the K.O. II with OS 2.5 - the manual pages below say so. A device that only offers MIDI over USB needs its OS updated with Teenage Engineering\'s updater.'
          : 'Keep the firmware current with Teenage Engineering\'s updater - the manual page below points to it.'
      ];
      case 'class': return [
        'A card exists, but the generic USB audio driver (snd-usb-audio) did not take it.',
        'Class-compliant audio needs no driver of its own; replug it and Scan again. The station\'s evidence line says what the host saw.'
      ];
      case 'free': return [
        'Only one program can hold a capture at a time, and another one has it (the evidence names it).',
        'Close that program, or stop the test that is holding it, then Run checks.'
      ];
      case 'capture': return [
        'The device is there but the capture would not open. The evidence says how it failed.',
        chans ? 'The station measured this device delivering ' + chans + ' channel' + (chans === 1 ? '' : 's') + (src.rate ? ' at ' + Math.round(src.rate / 100) / 10 + ' kHz' : '') + '; it opens it at its own rate and converts.'
          : 'The station opens the device at its own rate and converts.',
        'Press Test: it opens the capture for four seconds without going on air.'
      ];
      case 'signal': return [
        'The capture opens, but nothing above the silence floor is arriving.',
        'Play the instrument - pads, a pattern - and watch the audiograph above.',
        chans > 2 ? 'The device delivers ' + chans + ' channels and the station listens to ' + pair + '. If the audiograph stays dark, choose another pair in Input and press Test.'
          : 'Check the instrument\'s own volume and that USB audio is its output.'
      ];
      case 'level': return [
        'Aim for peaks around -6 dBFS: on the meter the peak line lives in the gold and never reaches the red.',
        'Set the instrument\'s own volume first; the station\'s trim (Input, -24 to +12 dB) is for the last few dB.',
        'The red lamp across the top of the meter means a sample hit full scale in the last two seconds.'
      ];
      case 'routed': return [
        'The input is captured but it is not the music on air.',
        'MX Live must be switched on and started (Event, Go live). While arming, the station waits for real audio before it takes the air' + (ctx.settings && ctx.settings.arm_timeout ? ' (up to ' + ctx.settings.arm_timeout + ' s)' : '') + '.',
        st.air && st.air.why_not ? 'The station says: ' + st.air.why_not : 'A paused station must be lifted first - Go live offers that when it is the reason.'
      ];
      case 'recording': return [
        'No cut pair is being written. Every ' + (rec.cut_seconds ? fmtCut(rec.cut_seconds) : '3.5 minutes') + ' the station closes two files: the live input alone in stereo, and the full broadcast mix.',
        'Recording, Write the cuts, must be on. The evidence says why the last write failed (disk, folder).'
      ];
      case 'courier': return [
        'The station writes the cuts on the DGX; Pine Box Desktop carries them to the QuickSwap folder.',
        'Open Pine Box Desktop on the PC - its courier takes the jobs. The Recording panel shows when a desk last took one.'
      ];
      case 'network': return [
        'The network road: the host listens on port 8095 for a sender on another machine.',
        'It is the second road - the USB cable into the DGX is the first.'
      ];
      case 'sender': return [
        'No sender is connected. Open the sender page on the machine the instrument is plugged into (Input, Network).',
        'A browser can only capture from a secure page; the sender page shows an ffmpeg line instead when it cannot.'
      ];
      default: return [];
    }
  }

  function fmtCut(s) {
    s = Number(s) || 0;
    if (s % 60 === 0) return (s / 60) + ' minute' + (s === 60 ? '' : 's');
    if (s > 60) return (Math.round(s / 6) / 10) + ' minutes';
    return s + ' seconds';
  }

  /* Which check a manual answers: `free` and the station-side ones have no
   * instrument pages. */
  function manualRefs(id, profile) {
    var prof = PROFILES[profile] || PROFILES[DEFAULT_PROFILE];
    return (prof.steps[id] || []).slice();
  }

  /* ------------------------------------------------------ manual quotations */

  function squash(text) {
    return String(text || '').replace(/\s*\|\s*/g, ' ').replace(/\s+/g, ' ').trim();
  }

  /** A quotation centred on `find` (case-insensitive), about `size`
   *  characters, cut at word boundaries; '' when there is no text. The
   *  words are the page's own - this only chooses where to start. */
  function excerpt(text, find, size) {
    var t = squash(text);
    if (!t) return '';
    size = size || 260;
    var at = find ? t.toLowerCase().indexOf(String(find).toLowerCase()) : -1;
    if (at < 0) at = 0;
    var start = Math.max(0, at - Math.round(size * 0.25));
    if (start > 0) {
      var dot = t.lastIndexOf('. ', at);
      if (dot >= start - 80 && dot < at) start = dot + 2;
      else {
        var sp = t.indexOf(' ', start);
        if (sp > 0 && sp < at) start = sp + 1;
      }
    }
    var end = Math.min(t.length, start + size);
    if (end < t.length) {
      var stop = t.lastIndexOf(' ', end);
      if (stop > start + 40) end = stop;
    }
    return (start > 0 ? '…' : '') + t.slice(start, end) + (end < t.length ? '…' : '');
  }

  /** The number a notebook page prints in its corner, from its heading
   *  ("179the koii ep133 notebook ..."); null for roman or none. */
  function printedPage(heading) {
    var m = /^\s*(\d{1,4})/.exec(String(heading || ''));
    return m ? Number(m[1]) : null;
  }

  /** The Library's notebook for a profile, from GET /api/manuals. */
  function libraryDoc(shelf, profile) {
    var prof = PROFILES[profile] || PROFILES[DEFAULT_PROFILE];
    if (!prof.library) return null;
    var docs = (shelf && shelf.documents) || [];
    var best = null;
    for (var i = 0; i < docs.length; i += 1) {
      var d = docs[i];
      var title = String(d.title || d.name || '');
      if (!prof.library.test(title)) continue;
      if (d.state && d.state !== 'ready') continue;
      if (d.kind && d.kind !== 'pdf') continue;
      if (!best || (d.reference && !best.reference) || Number(d.pages || 0) > Number(best.pages || 0)) best = d;
    }
    return best;
  }

  /** A gear-corpus page by its number, from GET /api/te/manual/<slug>. */
  function guidePage(doc, n) {
    var pages = (doc && doc.pages) || [];
    for (var i = 0; i < pages.length; i += 1) if (Number(pages[i].n) === Number(n)) return pages[i];
    return null;
  }

  /* ------------------------------------------------------------- svg bits */

  function svg(tag, attrs, parent, text) {
    var node = document.createElementNS(NS, tag);
    if (attrs) {
      for (var k in attrs) {
        if (Object.prototype.hasOwnProperty.call(attrs, k) && attrs[k] !== undefined && attrs[k] !== null) {
          node.setAttribute(k, String(attrs[k]));
        }
      }
    }
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (parent) parent.appendChild(node);
    return node;
  }

  var COLORS = {pass: '#54d18b', fail: '#ef6f5e', unknown: '#8fa0ad', skip: '#4a5a66',
    running: '#65c7da', warn: '#e3be63', line: '#35414c', text: '#dbe7eb', muted: '#8fa0ad',
    card: '#142029', ink: '#0b1217', accent: '#65c7da', orange: '#ff8a3d'};

  function resultOf(check) {
    var r = String((check && check.result) || 'unknown').toLowerCase();
    return COLORS[r] && ['pass', 'fail', 'unknown', 'skip', 'running'].indexOf(r) >= 0 ? r : 'unknown';
  }

  /** Worst of several results: fail > unknown > pass; all-skip = skip. */
  function worst(results) {
    var seen = {};
    results.forEach(function (r) { seen[r || 'unknown'] = true; });
    if (seen.fail) return 'fail';
    if (seen.running) return 'running';
    if (seen.unknown) return 'unknown';
    if (seen.pass) return 'pass';
    return seen.skip ? 'skip' : 'unknown';
  }

  function clip(text, chars) {
    text = String(text || '').replace(/\s+/g, ' ').trim();
    return text.length > chars ? text.slice(0, Math.max(1, chars - 1)).trim() + '…' : text;
  }

  var GROUPS = {
    host: 'STATION',
    usb: 'CABLE + CARD', alsa: 'CABLE + CARD', 'class': 'CABLE + CARD', network: 'NETWORK', sender: 'NETWORK',
    free: 'SOUND', capture: 'SOUND', signal: 'SOUND', level: 'SOUND',
    routed: 'AIR', recording: 'KEEP', courier: 'KEEP'
  };

  /* ------------------------------------------------------------ flowchart */

  var FC = {W: 340, X: 34, NW: 238, NH: 36, STEP: 48, TOP: 44};

  /** Where each check goes and how it looks - pure, so it can be tested
   *  without a DOM. */
  function flowLayout(checks, firstFail) {
    checks = Array.isArray(checks) ? checks : [];
    var failAt = -1;
    for (var i = 0; i < checks.length; i += 1) {
      if (firstFail ? checks[i].id === firstFail : resultOf(checks[i]) === 'fail') { failAt = i; break; }
    }
    if (failAt < 0 && firstFail) {
      for (var j = 0; j < checks.length; j += 1) if (resultOf(checks[j]) === 'fail') { failAt = j; break; }
    }
    var nodes = checks.map(function (c, k) {
      var result = resultOf(c);
      var sub = result === 'fail' ? (c.fix || c.evidence || 'this is where it stops')
        : result === 'pass' ? (c.evidence || 'yes')
          : result === 'skip' ? (c.evidence || 'not on this road')
            : result === 'running' ? 'checking now'
              : (c.evidence || 'not checked yet');
      return {
        id: String(c.id || ('check' + k)), label: String(c.label || c.id || 'check'),
        result: result, sub: sub, group: GROUPS[c.id] || '',
        x: FC.X, y: FC.TOP + k * FC.STEP, w: FC.NW, h: FC.NH,
        first: k === failAt, after: failAt >= 0 && k > failAt
      };
    });
    var height = FC.TOP + nodes.length * FC.STEP + 34;
    var groups = [];
    nodes.forEach(function (n) {
      var last = groups[groups.length - 1];
      if (last && last.name === n.group) last.to = n;
      else groups.push({name: n.group, from: n, to: n});
    });
    return {nodes: nodes, width: FC.W, height: height, failAt: failAt,
      groups: groups.filter(function (g) { return g.name; })};
  }

  function glyph(g, result, cx, cy) {
    var c = COLORS[result];
    svg('circle', {cx: cx, cy: cy, r: 9, fill: result === 'skip' ? 'none' : c, stroke: c, 'stroke-width': 1.5}, g);
    var ink = result === 'skip' ? c : COLORS.ink;
    if (result === 'pass') {
      svg('path', {d: 'M' + (cx - 4.2) + ' ' + cy + ' l3 3.2 l5.6 -6.4', fill: 'none', stroke: ink, 'stroke-width': 2, 'stroke-linecap': 'round', 'stroke-linejoin': 'round'}, g);
    } else if (result === 'fail') {
      svg('path', {d: 'M' + (cx - 3.6) + ' ' + (cy - 3.6) + ' l7.2 7.2 M' + (cx + 3.6) + ' ' + (cy - 3.6) + ' l-7.2 7.2', stroke: ink, 'stroke-width': 2, 'stroke-linecap': 'round'}, g);
    } else if (result === 'skip') {
      svg('path', {d: 'M' + (cx - 4) + ' ' + cy + ' h8', stroke: ink, 'stroke-width': 2, 'stroke-linecap': 'round'}, g);
    } else if (result === 'running') {
      svg('circle', {cx: cx, cy: cy, r: 3.2, fill: ink}, g);
    } else {
      svg('text', {x: cx, y: cy + 4, 'text-anchor': 'middle', 'font-size': 12, 'font-weight': 700, fill: ink}, g, '?');
    }
  }

  function arrow(parent, x1, y1, x2, y2, color, dashed) {
    svg('path', {d: 'M' + x1 + ' ' + y1 + ' L' + x2 + ' ' + y2, stroke: color, 'stroke-width': 1.6,
      fill: 'none', 'stroke-dasharray': dashed ? '4 3' : null}, parent);
    var ang = Math.atan2(y2 - y1, x2 - x1);
    var a = 5.5;
    var p1 = [x2 - a * Math.cos(ang - 0.45), y2 - a * Math.sin(ang - 0.45)];
    var p2 = [x2 - a * Math.cos(ang + 0.45), y2 - a * Math.sin(ang + 0.45)];
    svg('path', {d: 'M' + x2 + ' ' + y2 + ' L' + p1[0].toFixed(1) + ' ' + p1[1].toFixed(1) + ' L' + p2[0].toFixed(1) + ' ' + p2[1].toFixed(1) + ' Z', fill: color}, parent);
  }

  /** The flowchart as an <svg>. `opts.selected` is the chosen check id;
   *  `opts.start` / `opts.end` name the two ends of the road. Nodes carry
   *  data-check and are focusable; the caller wires clicks. */
  function flowchart(checks, opts) {
    opts = opts || {};
    var L = flowLayout(checks, opts.firstFail);
    var el = svg('svg', {viewBox: '0 0 ' + L.width + ' ' + L.height, width: '100%',
      'class': 'pl-fc', role: 'group', 'aria-label': 'Troubleshooting flowchart: where the sound stops'});
    svg('title', null, el, 'Where the sound stops');

    /* the two ends of the road */
    var startY = 8;
    var start = svg('g', {'class': 'pl-fc-end'}, el);
    svg('rect', {x: FC.X + 34, y: startY, width: FC.NW - 68, height: 24, rx: 12, fill: COLORS.card, stroke: COLORS.line}, start);
    svg('text', {x: FC.X + FC.NW / 2, y: startY + 16, 'text-anchor': 'middle', 'font-size': 11, fill: COLORS.muted}, start,
      opts.start || 'The instrument plays');

    L.groups.forEach(function (g) {
      var y1 = g.from.y + 3, y2 = g.to.y + g.to.h - 3;
      svg('path', {d: 'M14 ' + y1 + ' V' + y2, stroke: '#2c4450', 'stroke-width': 2, 'stroke-linecap': 'round'}, el);
      var my = (y1 + y2) / 2;
      svg('text', {x: 0, y: 0, transform: 'translate(9 ' + my + ') rotate(-90)', 'text-anchor': 'middle',
        'font-size': 8, 'letter-spacing': '0.08em', fill: '#6f8793'}, el, g.name);
    });

    var prevBottom = startY + 24;
    L.nodes.forEach(function (n, i) {
      var color = COLORS[n.result];
      var joinColor = n.after ? '#34424c' : (L.nodes[i - 1] && L.nodes[i - 1].result === 'pass') || i === 0 ? '#4d6b77' : '#34424c';
      arrow(el, FC.X + FC.NW / 2, prevBottom + 1, FC.X + FC.NW / 2, n.y - 2, joinColor, n.after);
      if (i > 0 && L.nodes[i - 1].result === 'pass') {
        svg('text', {x: FC.X + FC.NW / 2 + 6, y: (prevBottom + n.y) / 2 + 3, 'font-size': 8, fill: '#6f8793'}, el, 'yes');
      }
      var g = svg('g', {'class': 'pl-fc-node pl-fc-' + n.result + (n.first ? ' first' : '') + (n.after ? ' after' : '')
        + (opts.selected === n.id ? ' selected' : ''), 'data-check': n.id, tabindex: 0, role: 'button',
        'aria-label': n.label + ': ' + n.result + (n.sub ? '. ' + n.sub : '')}, el);
      if (n.first) {
        svg('rect', {x: n.x - 4, y: n.y - 4, width: n.w + 8, height: n.h + 8, rx: 10, fill: 'none',
          stroke: COLORS.fail, 'stroke-opacity': 0.35, 'stroke-width': 4, 'class': 'pl-fc-halo'}, g);
      }
      svg('rect', {x: n.x, y: n.y, width: n.w, height: n.h, rx: 7, fill: COLORS.card,
        stroke: opts.selected === n.id ? COLORS.accent : (n.result === 'fail' ? COLORS.fail : '#2f4450'),
        'stroke-width': opts.selected === n.id ? 2 : 1.2,
        'stroke-dasharray': n.result === 'skip' ? '4 3' : null}, g);
      glyph(g, n.result, n.x + 16, n.y + n.h / 2);
      svg('text', {x: n.x + 32, y: n.y + 15, 'font-size': 11.5, 'font-weight': 600,
        fill: n.result === 'skip' ? COLORS.muted : COLORS.text}, g, clip(n.label, 34));
      svg('text', {x: n.x + 32, y: n.y + 28, 'font-size': 9.5, fill: n.result === 'fail' ? '#f2a497' : COLORS.muted}, g,
        clip(n.sub, 40));
      if (n.result === 'fail') {
        /* the "no" branch: out to the right, to the thing to do */
        arrow(el, n.x + n.w + 1, n.y + n.h / 2, n.x + n.w + 20, n.y + n.h / 2, COLORS.fail);
        svg('text', {x: n.x + n.w + 4, y: n.y + n.h / 2 - 4, 'font-size': 8, fill: '#f2a497'}, el, 'no');
        var fix = svg('g', {'class': 'pl-fc-fix', 'data-check': n.id}, el);
        svg('rect', {x: n.x + n.w + 21, y: n.y + 7, width: 44, height: n.h - 14, rx: 11, fill: COLORS.fail}, fix);
        svg('text', {x: n.x + n.w + 43, y: n.y + n.h / 2 + 3.5, 'text-anchor': 'middle', 'font-size': 9.5,
          'font-weight': 700, fill: COLORS.ink}, fix, 'FIX');
      }
      prevBottom = n.y + n.h;
    });

    var endY = prevBottom + 18;
    var allPass = L.nodes.length && L.nodes.every(function (n) { return n.result === 'pass' || n.result === 'skip'; });
    arrow(el, FC.X + FC.NW / 2, prevBottom + 1, FC.X + FC.NW / 2, endY - 2, allPass ? '#4d6b77' : '#34424c', !allPass);
    var end = svg('g', {'class': 'pl-fc-end'}, el);
    svg('rect', {x: FC.X + 34, y: endY, width: FC.NW - 68, height: 24, rx: 12,
      fill: allPass ? '#173a2a' : COLORS.card, stroke: allPass ? COLORS.pass : COLORS.line}, end);
    svg('text', {x: FC.X + FC.NW / 2, y: endY + 16, 'text-anchor': 'middle', 'font-size': 11,
      fill: allPass ? COLORS.pass : COLORS.muted}, end, opts.end || 'On the air, and recorded');
    el.setAttribute('viewBox', '0 0 ' + L.width + ' ' + (endY + 30));
    return el;
  }

  /* ----------------------------------------------------- the infographic */

  function label(parent, x, y, text, size, color, anchor, weight) {
    return svg('text', {x: x, y: y, 'font-size': size || 12, fill: color || COLORS.text,
      'text-anchor': anchor || 'middle', 'font-weight': weight || null}, parent, text);
  }

  function drawKO2(g, x, y, w, h, color) {
    svg('rect', {x: x, y: y, width: w, height: h, rx: 5, fill: '#cfd3d3', stroke: color, 'stroke-width': 2}, g);
    svg('rect', {x: x + 6, y: y + 6, width: w * 0.46, height: h * 0.22, rx: 2, fill: '#1b2227'}, g);
    for (var r = 0; r < 3; r += 1) {
      for (var c = 0; c < 4; c += 1) {
        svg('rect', {x: x + w * 0.46 + c * (w * 0.12), y: y + h * 0.40 + r * (h * 0.17), width: w * 0.09, height: h * 0.12,
          rx: 1.5, fill: (r === 2 && c === 3) ? COLORS.orange : '#59616a'}, g);
      }
    }
    svg('circle', {cx: x + w * 0.16, cy: y + h * 0.55, r: h * 0.09, fill: '#e7e9ea', stroke: '#8a9196'}, g);
    svg('circle', {cx: x + w * 0.32, cy: y + h * 0.55, r: h * 0.09, fill: COLORS.orange}, g);
    svg('rect', {x: x + w * 0.12, y: y + h * 0.78, width: w * 0.22, height: h * 0.06, rx: 2, fill: '#59616a'}, g);
    /* the USB-C port on the top edge */
    svg('rect', {x: x + w * 0.70, y: y - 3, width: 12, height: 5, rx: 2, fill: '#59616a'}, g);
  }

  function drawSidekick(g, x, y, w, h, color) {
    svg('rect', {x: x, y: y, width: w, height: h, rx: 5, fill: '#cfd3d3', stroke: color, 'stroke-width': 2}, g);
    svg('circle', {cx: x + w * 0.3, cy: y + h * 0.2, r: w * 0.11, fill: COLORS.orange}, g);
    svg('circle', {cx: x + w * 0.62, cy: y + h * 0.2, r: w * 0.11, fill: COLORS.orange}, g);
    svg('rect', {x: x + w * 0.78, y: y + h * 0.1, width: w * 0.12, height: h * 0.2, rx: 1, fill: '#1b2227'}, g);
    [0.42, 0.56].forEach(function (fy) {
      svg('circle', {cx: x + w * 0.3, cy: y + h * fy, r: w * 0.07, fill: '#e7e9ea', stroke: '#8a9196'}, g);
      svg('circle', {cx: x + w * 0.62, cy: y + h * fy, r: w * 0.07, fill: '#e7e9ea', stroke: '#8a9196'}, g);
    });
    svg('path', {d: 'M' + (x + w * 0.3) + ' ' + (y + h * 0.7) + ' v' + (h * 0.2) + ' M' + (x + w * 0.62) + ' ' + (y + h * 0.7) + ' v' + (h * 0.2),
      stroke: '#59616a', 'stroke-width': 2}, g);
    svg('rect', {x: x + w * 0.6, y: y - 3, width: 11, height: 5, rx: 2, fill: '#59616a'}, g);
  }

  function drawLaptop(g, x, y, w, h, color) {
    svg('rect', {x: x + w * 0.1, y: y, width: w * 0.8, height: h * 0.72, rx: 4, fill: '#1b2227', stroke: color, 'stroke-width': 2}, g);
    svg('path', {d: 'M' + x + ' ' + (y + h * 0.84) + ' h' + w + ' l-' + (w * 0.06) + ' ' + (h * 0.12) + ' h-' + (w * 0.88) + ' Z',
      fill: '#cfd3d3', stroke: color, 'stroke-width': 1.5}, g);
  }

  function drawDGX(g, x, y, w, h, color) {
    svg('rect', {x: x, y: y, width: w, height: h, rx: 6, fill: '#2b2a22', stroke: color, 'stroke-width': 2}, g);
    for (var i = 0; i < 6; i += 1) {
      svg('path', {d: 'M' + (x + 10) + ' ' + (y + 9 + i * (h - 18) / 5) + ' h' + (w - 44), stroke: '#8d7a4f', 'stroke-width': 1.4}, g);
    }
    svg('rect', {x: x + w - 26, y: y + h * 0.36, width: 12, height: 6, rx: 2, fill: '#8d7a4f'}, g);
    svg('rect', {x: x + w - 26, y: y + h * 0.56, width: 12, height: 6, rx: 2, fill: '#8d7a4f'}, g);
  }

  function drawChip(g, x, y, w, h, color) {
    svg('rect', {x: x, y: y, width: w, height: h, rx: 8, fill: COLORS.card, stroke: color, 'stroke-width': 2}, g);
  }

  function drawTower(g, cx, cy, color) {
    svg('path', {d: 'M' + cx + ' ' + (cy - 14) + ' L' + (cx - 9) + ' ' + (cy + 16) + ' M' + cx + ' ' + (cy - 14) + ' L' + (cx + 9) + ' ' + (cy + 16)
      + ' M' + (cx - 5) + ' ' + (cy + 4) + ' h10', stroke: color, 'stroke-width': 2, fill: 'none', 'stroke-linecap': 'round'}, g);
    svg('circle', {cx: cx, cy: cy - 16, r: 3, fill: color}, g);
    svg('path', {d: 'M' + (cx - 10) + ' ' + (cy - 24) + ' a14 14 0 0 0 0 16 M' + (cx + 10) + ' ' + (cy - 24) + ' a14 14 0 0 1 0 16',
      stroke: color, 'stroke-width': 1.8, fill: 'none', 'stroke-linecap': 'round'}, g);
  }

  function drawPhones(g, cx, cy, color) {
    svg('path', {d: 'M' + (cx - 14) + ' ' + (cy + 6) + ' v-6 a14 14 0 0 1 28 0 v6', stroke: color, 'stroke-width': 2.4, fill: 'none'}, g);
    svg('rect', {x: cx - 17, y: cy + 2, width: 7, height: 12, rx: 3, fill: color}, g);
    svg('rect', {x: cx + 10, y: cy + 2, width: 7, height: 12, rx: 3, fill: color}, g);
  }

  function drawFile(g, x, y, color, text) {
    svg('path', {d: 'M' + x + ' ' + y + ' h16 l7 7 v23 h-23 Z', fill: COLORS.card, stroke: color, 'stroke-width': 1.6}, g);
    svg('path', {d: 'M' + (x + 16) + ' ' + y + ' v7 h7', fill: 'none', stroke: color, 'stroke-width': 1.2}, g);
    if (text) label(g, x + 11.5, y + 44, text, 10, COLORS.muted);
  }

  function drawFolder(g, x, y, color) {
    svg('path', {d: 'M' + x + ' ' + (y + 4) + ' h12 l4 4 h18 v22 h-34 Z', fill: COLORS.card, stroke: color, 'stroke-width': 1.8}, g);
  }

  function leg(parent, x1, y1, x2, y2, result, text) {
    var color = COLORS[result] || COLORS.unknown;
    var dashed = result !== 'pass';
    arrow(parent, x1, y1, x2, y2, color, dashed);
    if (text) label(parent, (x1 + x2) / 2, Math.min(y1, y2) - 7, text, 10, color);
  }

  function byId(checks) {
    var out = {};
    (checks || []).forEach(function (c) { if (c && c.id) out[c.id] = resultOf(c); });
    return out;
  }

  /** The road the sound takes, as an <svg>. `info` = {checks, state,
   *  device, profile, road: 'usb'|'network'}. */
  function connection(info) {
    info = info || {};
    var r = byId(info.checks);
    var st = info.state || {};
    var src = st.source || {};
    var rec = st.recording || {};
    var air = st.air || {};
    var dev = info.device || {};
    var prof = PROFILES[info.profile] || PROFILES[DEFAULT_PROFILE];
    var network = info.road === 'network';
    var el = svg('svg', {viewBox: '0 0 1000 214', width: '100%', 'class': 'pl-conn', role: 'img',
      'aria-label': 'How the sound gets from the instrument to the air and to the QuickSwap folder'});
    svg('title', null, el, 'How the sound travels');

    function col(res) { return COLORS[res] || COLORS.unknown; }

    /* 1. the instrument */
    var g1 = svg('g', null, el);
    var instrumentRes = network ? worst([r.sender]) : worst([r.usb]);
    if (network) drawLaptop(g1, 28, 34, 110, 64, col(instrumentRes));
    else if (prof.id === 'ep-136') drawSidekick(g1, 60, 22, 50, 84, col(instrumentRes));
    else drawKO2(g1, 22, 36, 124, 66, col(instrumentRes));
    label(g1, 85, 128, network ? 'Interface on a PC' : prof.name, 12.5, COLORS.text, 'middle', 600);
    label(g1, 85, 144, network ? 'the sender page captures it' : prof.port, 10, COLORS.muted);

    /* 2. the cable */
    var cableRes = network ? worst([r.network, r.sender]) : worst([r.usb]);
    leg(el, 150, 68, 296, 68, cableRes, network ? 'Wi-Fi or tailnet' : 'USB-C data cable');
    label(el, 223, 88, network ? 'port 8095' : 'straight into the DGX', 9.5, COLORS.muted);

    /* 3. the DGX and its card */
    var g3 = svg('g', null, el);
    var cardRes = network ? worst([r.network]) : worst([r.alsa, r['class'], r.free]);
    drawDGX(g3, 302, 38, 118, 60, col(cardRes));
    label(g3, 361, 128, 'DGX Spark', 12.5, COLORS.text, 'middle', 600);
    var cardLine = network ? 'network ingest'
      : (dev.card_id ? 'ALSA card ' + dev.card_id : (cardRes === 'fail' ? 'no sound card yet' : 'USB audio card'));
    label(g3, 361, 144, cardLine, 10, cardRes === 'fail' ? '#f2a497' : COLORS.muted);

    /* 4. the host capture */
    var capRes = worst([r.host, network ? r.sender : r.capture]);
    leg(el, 424, 68, 470, 68, capRes);
    var g4 = svg('g', null, el);
    drawChip(g4, 474, 40, 132, 56, col(capRes));
    label(g4, 540, 63, 'PineLive host', 12, COLORS.text, 'middle', 600);
    var rate = Number(src.rate || dev.rate || (dev.rates && dev.rates[0]) || 0);
    var pair = Array.isArray(src.channel_pair) ? src.channel_pair.join('+') : '1+2';
    label(g4, 540, 80, (rate ? Math.round(rate / 100) / 10 + ' kHz' : 'capture') + ' · ch ' + pair, 10, COLORS.muted);
    label(g4, 540, 128, 'captures + meters', 10, COLORS.muted);

    /* 5. the signal into the station */
    var sigRes = worst([r.signal, r.level]);
    leg(el, 610, 68, 656, 68, sigRes);
    var wave = svg('path', {d: 'M616 56 q4 -8 8 0 t8 0 t8 0 t8 0', fill: 'none', stroke: col(sigRes), 'stroke-width': 1.6}, el);
    wave.setAttribute('class', 'pl-conn-wave');

    /* 6. the station */
    var airRes = worst([r.routed]);
    var g6 = svg('g', null, el);
    drawChip(g6, 660, 34, 128, 68, col(airRes));
    drawTower(g6, 690, 72, col(airRes));
    label(g6, 744, 62, 'Station', 12, COLORS.text, 'middle', 600);
    label(g6, 744, 78, 'on the air', 10, COLORS.muted);
    label(g6, 744, 92, 'DJs duck it', 9.5, COLORS.muted);
    label(g6, 740, 128, st.live ? 'LIVE now' : (st.armed ? 'armed' : 'not live'), 10.5,
      st.live ? '#ff8f84' : COLORS.muted, 'middle', st.live ? 700 : null);

    /* 7. the listeners */
    leg(el, 792, 68, 836, 68, airRes);
    var g7 = svg('g', null, el);
    drawPhones(g7, 880, 62, col(airRes));
    label(g7, 880, 100, 'Listeners', 12, COLORS.text, 'middle', 600);
    var roads = [];
    if (air.stream) roads.push('stream');
    if (air.pages) roads.push('pages');
    if (air.box) roads.push('box');
    label(g7, 880, 116, roads.length ? roads.join(' · ') : 'stream · pages', 10, COLORS.muted);

    /* 8. the cuts and the courier, below the station */
    var recRes = worst([r.recording]);
    var courRes = worst([r.courier]);
    svg('path', {d: 'M684 104 V168 H652', stroke: col(recRes), 'stroke-width': 1.6, fill: 'none',
      'stroke-dasharray': recRes === 'pass' ? null : '4 3'}, el);
    var g8 = svg('g', null, el);
    drawFile(g8, 588, 150, col(recRes), 'input');
    drawFile(g8, 620, 150, col(recRes), 'mix');
    label(g8, 520, 162, 'every ' + fmtCut(rec.cut_seconds || 210), 10.5, COLORS.text, 'end', 600);
    label(g8, 520, 177, 'two files: input + full mix', 9.5, COLORS.muted, 'end');
    arrow(el, 584, 168, 440, 168, col(courRes), courRes !== 'pass');
    label(el, 512, 199, 'the desk carries them', 9.5, COLORS.muted);
    var g9 = svg('g', null, el);
    drawFolder(g9, 396, 150, col(courRes));
    label(g9, 380, 162, 'QuickSwap', 11, COLORS.text, 'end', 600);
    label(g9, 380, 177, 'PineBoxRecordings \\ Live Events', 9.5, COLORS.muted, 'end');
    return el;
  }

  var api = {PROFILES: PROFILES, DEFAULT_PROFILE: DEFAULT_PROFILE, profileFor: profileFor,
    stepsFor: stepsFor, manualRefs: manualRefs, excerpt: excerpt, printedPage: printedPage,
    libraryDoc: libraryDoc, guidePage: guidePage, flowLayout: flowLayout, flowchart: flowchart,
    connection: connection, resultOf: resultOf, worst: worst, fmtCut: fmtCut, COLORS: COLORS,
    pickInstrument: pickInstrument, notInstrument: notInstrument,
    mismatchNote: mismatchNote, DEVICE_SETTINGS: DEVICE_SETTINGS};
  root.PineLiveGuide = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
