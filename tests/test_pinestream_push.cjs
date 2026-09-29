/* [pinestream] desktop/pinestream-push.cjs - the desk's capture obeys the
 * station and the page, and sends nothing it should not.
 *
 *   node tests/test_pinestream_push.cjs
 */
'use strict';
const assert = require('node:assert');
const path = require('node:path');
const { PineStreamPush, DEADMAN_MS } = require(path.join(__dirname, '..', 'desktop', 'pinestream-push.cjs'));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function fakeWin(opts = {}) {
  let n = 0;
  return {
    minimized: false,
    isDestroyed: () => false,
    isMinimized() { return this.minimized; },
    isVisible: () => true,
    webContents: {
      capturePage: async () => {
        n += 1;
        const frame = opts.still ? 1 : n;
        return {
          isEmpty: () => false,
          getSize: () => ({ width: 1600, height: 900 }),
          resize: (o) => ({ toJPEG: (q) => Buffer.from([0xff, 0xd8, frame, o.width & 255, q, 0xff, 0xd9]) }),
          toJPEG: (q) => Buffer.from([0xff, 0xd8, frame, q, 0xff, 0xd9]),
        };
      },
    },
  };
}

function station(answers) {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, body: Buffer.from(init.body || []), headers: init.headers });
    const a = typeof answers === 'function' ? answers(calls.length) : answers;
    if (a instanceof Error) throw a;
    return { ok: true, status: 200, json: async () => a };
  };
  return { calls, fetchImpl };
}

async function main() {
  /* 1. it runs while the station says keep, and stops the moment it says no */
  {
    const st = station((n) => (n < 3 ? { keep: true, fps: 5, width: 640, quality: 60 }
      : { keep: false, say: 'PineStream is off - capture nothing' }));
    const p = new PineStreamPush({ getWin: () => fakeWin(), baseUrl: () => 'http://s', headers: () => ({ Authorization: 'Bearer k' }), fetchImpl: st.fetchImpl });
    p.run({ fps: 5, width: 640, quality: 60 });
    await sleep(900);
    assert.strictEqual(p.running, false, 'stopped on keep:false');
    assert.strictEqual(p.why, 'PineStream is off - capture nothing');
    assert.strictEqual(st.calls.length, 3, 'no post after the station said stop');
    assert.ok(st.calls[0].url.startsWith('http://s/api/pinestream/frame?source=pineapp'));
    assert.strictEqual(st.calls[0].headers.Authorization, 'Bearer k');
    assert.strictEqual(st.calls[0].headers['Content-Type'], 'image/jpeg');
    assert.strictEqual(st.calls[0].body[0], 0xff, 'a JPEG went');
    assert.strictEqual(st.calls[0].body[3], 640 & 255, 'resized to the width asked for');
  }
  /* 2. the dead man: a page that stops saying run stops the capture */
  {
    let now = 1000;
    const st = station({ keep: true, fps: 5 });
    const p = new PineStreamPush({ getWin: () => fakeWin(), fetchImpl: st.fetchImpl, now: () => now });
    p.run({ fps: 5 });
    await sleep(300);
    assert.strictEqual(p.running, true);
    now += DEADMAN_MS + 1;
    await sleep(400);
    assert.strictEqual(p.running, false);
    assert.strictEqual(p.why, 'the page stopped asking');
  }
  /* 3. private: no pixels, the reason in the query */
  {
    const st = station({ keep: true, fps: 5 });
    const p = new PineStreamPush({ getWin: () => fakeWin(), fetchImpl: st.fetchImpl });
    p.run({ fps: 5, private: true, why: 'a key field is on the screen' });
    await sleep(150);
    p.stop('test');
    assert.ok(st.calls.length >= 1);
    assert.strictEqual(st.calls[0].body.length, 0, 'no picture while private');
    assert.ok(/private=1&why=a%20key%20field/.test(st.calls[0].url), st.calls[0].url);
  }
  /* 4. an unchanged screen sends an empty keep-alive, not the same bytes */
  {
    const st = station({ keep: true, fps: 5 });
    const p = new PineStreamPush({ getWin: () => fakeWin({ still: true }), fetchImpl: st.fetchImpl });
    p.run({ fps: 5 });
    await sleep(700);
    p.stop('test');
    assert.ok(st.calls.length >= 3, 'several rounds: ' + st.calls.length);
    assert.ok(st.calls[0].body.length > 0);
    assert.strictEqual(st.calls[1].body.length, 0, 'unchanged: keep-alive');
    assert.ok(p.kept >= 1);
  }
  /* 5. a minimised window shows nothing true: private */
  {
    const st = station({ keep: true, fps: 5 });
    const w = fakeWin();
    w.minimized = true;
    const p = new PineStreamPush({ getWin: () => w, fetchImpl: st.fetchImpl });
    p.run({ fps: 5 });
    await sleep(150);
    p.stop('test');
    assert.ok(/private=1&why=the%20Pine%20app%20is%20minimised/.test(st.calls[0].url));
    assert.strictEqual(st.calls[0].body.length, 0);
  }
  /* 6. a station that is not there: five failures and it stops */
  {
    const st = station(new Error('connect ECONNREFUSED'));
    const p = new PineStreamPush({ getWin: () => fakeWin(), fetchImpl: st.fetchImpl });
    p.schedule = function (ms) { if (this.timer) clearTimeout(this.timer); this.timer = setTimeout(() => { this.tick(); }, Math.min(ms, 5)); };
    p.run({ fps: 5 });
    await sleep(300);
    assert.strictEqual(p.running, false);
    assert.ok(/did not answer 5 times/.test(p.why), p.why);
  }
  /* 7. stop is honoured and the verbs answer state */
  {
    const p = new PineStreamPush({ getWin: () => fakeWin(), fetchImpl: station({ keep: true }).fetchImpl });
    const s = p.verb('run', { fps: 99, width: 5000, quality: 1 });
    assert.deepStrictEqual([s.fps, s.width, s.quality], [5, 960, 30], 'clamped');
    const s2 = p.verb('stop', { why: 'bye' });
    assert.strictEqual(s2.running, false);
    assert.strictEqual(s2.why, 'bye');
  }
  console.log('test_pinestream_push: 7 groups ok');
}

main().catch((err) => { console.error(err); process.exit(1); });
