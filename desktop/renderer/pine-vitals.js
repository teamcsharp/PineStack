/* THE TABLET'S VITAL SIGNS, PAINTED THE SAME WAY EVERYWHERE.
 *
 * "Show connection information here and detailed information about the
 *  heartbeat and the graphics information on how it's taxing the system and
 *  the tablet and how it's impacting the battery life, along with showing a
 *  numerical overlay of how much battery life is on the tablet and how much
 *  battery life is left."
 *
 * One component, two homes: the sidebar of the panel, and the live mirror
 * window. Written once because two copies of a readout drift, and a readout
 * that disagrees with itself is worse than no readout.
 *
 * IT SAYS WHAT IT MEASURED, NOT WHAT IT ASSUMES. Time left comes from the
 * charge counter divided by the current draw - real microamp-hours over real
 * microamps - so a tablet at 14% pulling 1.3 A honestly reports half an
 * hour, where a percentage-based guess would have said hours. When a figure
 * cannot be read the row says so rather than printing a zero.
 *
 * THE COLOURS ARE THRESHOLDS, NOT DECORATION. Amber and red mean a number
 * has crossed a line worth acting on, and nothing else in here is coloured,
 * so a glance at the block is enough.
 */
(function (root) {
  'use strict';

  /* Where a number stops being fine. Chosen from what this tablet actually
   * does: it idles near 1.5 load with the station running, and a janky
   * percentage over about a fifth is visible to the eye. */
  const LINES = {
    percent: { bad: 10, poor: 20 },        /* battery, lower is worse */
    hoursLeft: { bad: 0.5, poor: 1.5 },
    rttMs: { bad: 600, poor: 250 },
    load: { bad: 12, poor: 6 },
    freeMb: { bad: 300, poor: 700 },
    jankyPercent: { bad: 40, poor: 20 },
    tempC: { bad: 45, poor: 40 }
  };

  /* Lower-is-better for some, higher-is-better for others. Said once here
   * rather than at every call site. */
  const HIGHER_IS_WORSE = new Set(['rttMs', 'load', 'jankyPercent', 'tempC']);

  function grade(key, value) {
    const line = LINES[key];
    if (!line || value == null || !isFinite(value)) return '';
    const worse = HIGHER_IS_WORSE.has(key);
    if (worse ? value >= line.bad : value <= line.bad) return 'bad';
    if (worse ? value >= line.poor : value <= line.poor) return 'poor';
    return 'good';
  }

  function hoursWords(hours) {
    if (hours == null) return null;
    if (hours >= 10) return hours.toFixed(0) + ' h';
    const whole = Math.floor(hours);
    const mins = Math.round((hours - whole) * 60);
    return whole > 0 ? whole + ' h ' + mins + ' m' : mins + ' m';
  }

  function say(value, unit, digits) {
    if (value == null || !isFinite(value)) return '—';
    return (digits == null ? value : Number(value).toFixed(digits)) + (unit || '');
  }

  function row(label, value, mark, hint) {
    const line = document.createElement('div');
    line.className = 'pv-row' + (mark ? ' pv-' + mark : '');
    if (hint) line.title = hint;
    const name = document.createElement('span');
    name.className = 'pv-name';
    name.textContent = label;
    const said = document.createElement('span');
    said.className = 'pv-value';
    said.textContent = value;
    line.appendChild(name);
    line.appendChild(said);
    return line;
  }

  function head(text) {
    const bar = document.createElement('div');
    bar.className = 'pv-head';
    bar.textContent = text;
    return bar;
  }

  /**
   * Paint one reading into [into].
   *
   * `extra` carries what only the caller knows - the mirror's own frame rate
   * and bandwidth, which are measured on this side of the wire and have no
   * business being asked of the tablet.
   */
  function paint(into, said, extra) {
    into.textContent = '';
    if (!said || !said.ok) {
      into.appendChild(row('Tablet', said && said.why ? said.why : 'not reachable', 'bad'));
      return;
    }

    const b = said.battery || {};
    const g = said.graphics || {};
    const l = said.load || {};
    const m = said.memory || {};
    const c = said.connection || {};

    /* ---- the number that was asked for first, and biggest -------------- */
    const crown = document.createElement('div');
    crown.className = 'pv-crown ' + grade('percent', b.percent);
    const pc = document.createElement('span');
    pc.className = 'pv-pc';
    pc.textContent = b.percent == null ? '—' : b.percent + '%';
    crown.appendChild(pc);

    const left = document.createElement('span');
    left.className = 'pv-left ' + grade('hoursLeft', b.hoursLeft);
    /* A tablet on the cable has no "time left", and printing one would be
     * an invention. */
    left.textContent = b.charging
      ? (b.status === 'full' ? 'charged' : 'charging')
      : (hoursWords(b.hoursLeft) ? hoursWords(b.hoursLeft) + ' left' : 'time unknown');
    crown.appendChild(left);
    into.appendChild(crown);

    /* ---- what it is spending -------------------------------------------*/
    into.appendChild(head('Battery'));
    into.appendChild(row('Draw', b.drawMa == null ? '—'
      : say(b.drawMa, ' mA', 0) + (b.watts != null ? '  ·  ' + say(b.watts, ' W', 2) : ''),
      '', 'How much current the tablet is pulling right now'));
    if (b.sinceMirrorMa != null) {
      /* THE MIRROR'S OWN COST, which is the question behind "how is it
       * impacting the battery life" - not what the tablet costs, but what
       * watching it costs. */
      into.appendChild(row('Since mirror',
        (b.sinceMirrorMa >= 0 ? '+' : '') + say(b.sinceMirrorMa, ' mA', 0),
        b.sinceMirrorMa > 300 ? 'poor' : '',
        'The change in draw since the live view was opened'));
    }
    into.appendChild(row('Charge', b.chargeMah == null ? '—' : say(b.chargeMah, ' mAh', 0)
      + (b.volts != null ? '  ·  ' + say(b.volts, ' V', 2) : ''), ''));
    into.appendChild(row('Temperature', say(b.tempC, ' °C', 1), grade('tempC', b.tempC)));

    /* ---- the link ------------------------------------------------------*/
    into.appendChild(head('Connection'));
    into.appendChild(row('Heartbeat', say(said.rttMs, ' ms', 0),
      grade('rttMs', said.rttMs),
      'How long the tablet took to answer this sweep'));
    into.appendChild(row('Over', c.how + (c.address ? '  ·  ' + c.address : ''), '',
      c.serial));

    /* ---- what it is costing the tablet ---------------------------------*/
    into.appendChild(head('Load on the tablet'));
    into.appendChild(row('Load average', say(l.one, '', 2)
      + (l.five != null ? '  ·  ' + say(l.five, '', 2) : ''),
      grade('load', l.one),
      'One minute and five minute load average'
        + (l.threads ? '. ' + l.running + ' of ' + l.threads + ' threads running' : '')));
    into.appendChild(row('Memory free', m.freeMb == null ? '—'
      : say(m.freeMb, ' MB', 0) + (m.totalMb ? ' of ' + say(m.totalMb, ' MB', 0) : ''),
      grade('freeMb', m.freeMb)));

    /* ---- what the drawing is doing -------------------------------------*/
    into.appendChild(head('Graphics'));
    into.appendChild(row('Janky frames', g.jankyPercent == null ? '—'
      : say(g.jankyPercent, '%', 1) + (g.janky != null ? '  ·  ' + g.janky : ''),
      grade('jankyPercent', g.jankyPercent),
      'Frames the tablet did not draw in time, of ' + say(g.frames, '', 0) + ' rendered'));
    into.appendChild(row('Frame time', g.p50 == null ? '—'
      : say(g.p50, 'ms', 0) + ' / ' + say(g.p90, 'ms', 0) + ' / ' + say(g.p99, 'ms', 0),
      '', 'Median, 90th and 99th percentile frame times'));
    if (g.gpu90 != null) {
      into.appendChild(row('GPU 90th', say(g.gpu90, ' ms', 0), '',
        'How long the GPU takes for nine frames in ten'));
    }

    /* ---- and what this end is doing ------------------------------------*/
    if (extra && extra.mirror) {
      const mirror = extra.mirror;
      into.appendChild(head('The live view'));
      into.appendChild(row('Stream', mirror.live
        ? mirror.width + '×' + mirror.height
        : 'not running', mirror.live ? '' : 'poor'));
      if (mirror.fps != null) {
        into.appendChild(row('Frames', say(mirror.fps, ' /s', 1)
          + (mirror.kbps != null ? '  ·  ' + say(mirror.kbps, ' kB/s', 0) : ''), ''));
      }
      if (mirror.restarts) {
        into.appendChild(row('Restarts', String(mirror.restarts),
          mirror.restarts > 3 ? 'poor' : ''));
      }
    }
  }

  /**
   * Keep [into] painted. Returns a stop function.
   *
   * EVERY WATCHER IS ONE MORE SWEEP OF A BUSY TABLET, so the interval is
   * generous by default and the caller is expected to stop when its window
   * is not being looked at.
   */
  function watch(into, options) {
    const api = window.pineDesktop || {};
    const every = (options && options.every) || 4000;
    const more = (options && options.extra) || (() => null);
    let alive = true;
    let timer = 0;

    async function turn() {
      if (!alive) return;
      try {
        const said = await api.tabletVitals();
        if (alive) paint(into, said, await more());
      } catch (error) {
        if (alive) paint(into, { ok: false, why: error.message });
      }
      if (alive) timer = setTimeout(turn, every);
    }
    turn();

    return function stop() {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }

  root.pineVitals = { paint, watch, grade, hoursWords };
})(window);
