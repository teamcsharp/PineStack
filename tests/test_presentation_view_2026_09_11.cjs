/* The Presentation view: the video wall, and the one throat the whole
 * screen speaks through.
 *
 * Two things are pinned here and they are the two that can actually hurt
 * something.
 *
 * 1. TRAFFIC. 38 concurrent requests in flight to this station measured a
 *    46-second media stall on the tablet on 2026-09-11 - which is why the
 *    tablet plays no audio today. A six-pane dashboard is the obvious way
 *    to make that worse, so the gate is tested for the property that
 *    matters: never more than one of our questions outstanding, whatever
 *    the panes do.
 *
 * 2. THE WALL SURVIVING THE STATION. /api/generations/image/{filename}
 *    (app.py:112044) reads off a bind mount and falls back to ComfyUI over
 *    HTTP, so it 404s for a name the log still carries, 502s when ComfyUI
 *    is down, and - the one that looks like success - can hand over a file
 *    with nothing in it. Each of those has its own test, because each of
 *    them used to be indistinguishable from "the wall is just black".
 *
 * The fixtures are shaped from data/generations.jsonl on this box: 267
 * records, seven of them kind "video" from wan2.2_ti2v_5B_fp16, six with a
 * finished .mp4, three rows carrying status "lost", and 60 Gazette plates.
 */
const { test } = require("node:test");
const assert = require("node:assert/strict");

const wallApi = require("../desktop/renderer/video-wall.js");
const sourceApi = require("../desktop/renderer/presentation-source.js");

const settle = () => new Promise((resolve) => setImmediate(resolve));
const HOUR = 3600 * 1000;

/* A generation log, shaped like the real one. `ts` is epoch SECONDS, which
 * is what append_generation writes (app.py:6966). */
function log(...rows) { return { generations: rows }; }
const video = (file, agoHours, extra) => Object.assign({
  ts: Math.round((NOW - agoHours * HOUR) / 1000),
  kind: "video",
  model: "wan2.2_ti2v_5B_fp16",
  request: "generate me a video of a tiny robot dancing on a synthesizer",
  tags: "tiny robot, dancing, synthesizer, neon lights",
  status: "done",
  files: [file]
}, extra || {});

const NOW = 1785600000000;

function wallHarness(payload, overrides) {
  let clock = NOW;
  const fetched = [];
  const released = [];
  let live = 0;
  let peakLive = 0;
  let inFlight = 0;
  let peakFetch = 0;
  const options = Object.assign({
    now: () => clock,
    random: () => 0,
    get: async (route) => {
      assert.equal(route, "/api/generations?limit=1000");
      return payload;
    },
    fetchClip: async (url) => {
      assert.ok(url.startsWith("/api/generations/image/"));
      inFlight += 1;
      peakFetch = Math.max(peakFetch, inFlight);
      fetched.push(decodeURIComponent(url.split("/").pop()));
      await settle();
      inFlight -= 1;
      live += 1;
      peakLive = Math.max(peakLive, live);
      return { src: "blob:" + url, bytes: 2 * 1024 * 1024 };
    },
    releaseClip: (clip) => { released.push(clip.src); live -= 1; }
  }, overrides || {});

  const wall = wallApi.create(options);
  return {
    wall, fetched, released,
    at(value) { clock = value; return clock; },
    tick(value) { if (value != null) clock = value; return wall.tick(clock); },
    async ready() { for (let i = 0; i < 8; i += 1) await settle(); },
    get live() { return live; },
    get peakLive() { return peakLive; },
    get peakFetch() { return peakFetch; }
  };
}

/* ---------------------------------------------------- what is on the shelf */

test("the wall keeps playable media, drops lost renders, duplicates and unsafe names", async () => {
  const shelf = wallApi.catalogue(log(
    { kind: "image", ts: 1, files: ["a-picture.png"] },
    { kind: "video", ts: 3, status: "lost", files: ["never-arrived.mp4"] },
    { kind: "video", ts: 4, files: ["PineBox_00043_.mp4", "PineBox_00043_.mp4"] },
    { kind: "video", ts: 5, files: ["../outside.mp4", "sub/inside.webm", "ok name (2).webm"] },
    { kind: "video", ts: 6, files: ["PineBox_00047_.MP4"] },
    null,
    { kind: "video", ts: 7, files: "not an array" }
  ), NOW, {});
  assert.deepEqual(shelf.map((row) => row.file),
    ["PineBox_00047_.MP4", "ok name (2).webm", "PineBox_00043_.mp4", "a-picture.png"]);
  /* Newest first, so a recency draw with a low roll lands on new work. */
  assert.deepEqual(shelf.map((row) => row.ts), [6, 5, 4, 1]);
});

/* The LCD gallery EXCLUDES Gazette plates because a newspaper snapshot is
 * not a picture anybody wants in a slideshow. The wall does not exclude
 * them, it LABELS them - and in practice it never has to, because the
 * press writes PNGs (paper_snapshot_write, app.py:124940) and cannot
 * produce video at all. Pinned so the difference is deliberate rather
 * than a rule somebody forgot to copy across. */
test("a Gazette row is labelled rather than hidden, which is the difference from the LCD gallery", () => {
  const shelf = wallApi.catalogue(log(
    { kind: "paper", model: "gazette", ts: 2, files: ["gazette-2026-09-11-01.mp4"] }
  ), NOW, {});
  assert.deepEqual(shelf.map((row) => [row.file, row.activity, row.label]),
    [["gazette-2026-09-11-01.mp4", "gazette", "the Gazette"]]);
});

test("a Gazette plate is attributed to the Gazette even though its tags are a prompt everywhere else", () => {
  assert.equal(wallApi.activityOf({ kind: "paper", model: "gazette" }, {}).key, "gazette");
  assert.equal(wallApi.activityOf({ model: "gazette" }, {}).key, "gazette");
  assert.equal(wallApi.activityOf({ request: "Regenerated from gallery" }, {}).key, "gallery");
  assert.equal(wallApi.activityOf({ request: "the orchestrator's own board" }, {}).key, "orchestrator");
  assert.equal(wallApi.activityOf({ request: "a blue heron by a river" }, {}).key, "station");
});

test("a clip is tied to a DJ only by a whole name off the live cast, never by a fragment", () => {
  const cast = { host: "Caine", cohost: "Skip", sfx: "Pine" };
  assert.deepEqual(
    [wallApi.activityOf({ request: "Caine at the desk" }, cast).key,
      wallApi.activityOf({ request: "Caine at the desk" }, cast).label],
    ["booth", "Caine on air"]);
  /* "Pine" inside "Pinebox" is the building, not the sound effects guy. */
  assert.equal(wallApi.activityOf({ tags: "the Pinebox gallery" }, cast).key, "station");
  assert.equal(wallApi.activityOf({ tags: "Skip, mid-rant" }, cast).label, "Skip on air");
});

test("recency halves every twelve hours and never reaches zero, so an old clip is rare but reachable", () => {
  const fresh = wallApi.weightAt(NOW / 1000, NOW);
  const half = wallApi.weightAt((NOW - 12 * HOUR) / 1000, NOW);
  const ancient = wallApi.weightAt((NOW - 40 * 24 * HOUR) / 1000, NOW);
  assert.ok(fresh > 0.99);
  assert.ok(Math.abs(half - (wallApi.WEIGHT_FLOOR + (1 - wallApi.WEIGHT_FLOOR) / 2)) < 1e-9);
  assert.ok(ancient >= wallApi.WEIGHT_FLOOR);
  assert.ok(ancient < 0.05);
  /* A row with no usable timestamp is treated as the OLDEST thing, not
   * the newest - the safe way round for a wall about what is happening now. */
  assert.equal(wallApi.weightAt(0, NOW), wallApi.WEIGHT_FLOOR);
  assert.equal(wallApi.weightAt("nonsense", NOW), wallApi.WEIGHT_FLOOR);
});

test("the draw is weighted: a low roll takes recent work, a high roll reaches the back of the shelf", () => {
  const shelf = wallApi.catalogue(
    log(video("new.mp4", 0), video("mid.mp4", 12), video("old.mp4", 240)), NOW, {});
  assert.equal(wallApi.weighted(shelf, 0).file, "new.mp4");
  assert.equal(wallApi.weighted(shelf, 0.999999).file, "old.mp4");
  /* Its total weight is dominated by the fresh clip, which is the point. */
  assert.ok(shelf[0].weight > shelf[2].weight * 10);
});

/* ------------------------------------------------------- holding two clips */

test("the wall holds only the current and next clip, and releases every one it lets go", async () => {
  const h = wallHarness(log(video("a.mp4", 0), video("b.mp4", 1), video("c.mp4", 2)),
    { random: () => 0.4 });
  h.tick();
  await h.ready();
  const first = h.tick();
  assert.equal(first.ready, true);
  assert.equal(first.holding, 2);
  assert.equal(h.live, 2);
  /* One clip fetched at a time - a wall that downloaded three videos at
   * once would be the very traffic this screen exists to avoid. */
  assert.equal(h.peakFetch, 1);

  h.wall.advance();
  await h.ready();
  const second = h.tick();
  assert.notEqual(second.file, first.file);
  assert.equal(h.released.length, 1);
  assert.equal(h.live, 2);
  assert.equal(h.peakLive, 2);

  h.wall.destroy();
  assert.equal(h.live, 0);
});

test("one clip in the gallery loops instead of going dark, and never fetches a second copy", async () => {
  const h = wallHarness(log(video("only.mp4", 0)));
  h.tick();
  await h.ready();
  const state = h.tick();
  assert.equal(state.file, "only.mp4");
  assert.equal(state.holding, 1);
  h.wall.advance();
  await h.ready();
  assert.equal(h.tick().file, "only.mp4");
  assert.deepEqual(h.fetched, ["only.mp4"]);
  assert.equal(h.released.length, 0);
  h.wall.destroy();
});

/* ----------------------------------------------------- when it goes wrong */

test("a clip that 404s is remembered, never retried hot, and the wall plays something else", async () => {
  const asked = [];
  const h = wallHarness(log(video("gone.mp4", 0), video("good.mp4", 1)), {
    random: () => 0,
    fetchClip: async (url) => {
      const name = decodeURIComponent(url.split("/").pop());
      asked.push(name);
      if (name === "gone.mp4") throw new Error("The station could not provide that (HTTP 404).");
      return { src: "blob:" + name, bytes: 1024 };
    }
  });
  h.tick();
  await h.ready();
  /* The failure does NOT schedule its own retry: a hundred paints cannot
   * turn one missing file into a hundred requests. */
  for (let i = 0; i < 100; i += 1) h.tick(NOW + 1);
  await h.ready();
  assert.deepEqual(asked, ["gone.mp4"]);

  h.tick(NOW + 400);
  await h.ready();
  const state = h.tick(NOW + 400);
  assert.equal(state.file, "good.mp4");
  assert.equal(state.ready, true);
  assert.ok(/404/.test(state.note) === false || state.file === "good.mp4");
  h.wall.destroy();
});

test("a zero-length file is named as empty rather than shown as a black rectangle, and its bytes are released", async () => {
  const released = [];
  const h = wallHarness(log(video("empty.mp4", 0), video("real.mp4", 1)), {
    random: () => 0,
    fetchClip: async (url) => {
      const name = decodeURIComponent(url.split("/").pop());
      return { src: "blob:" + name, bytes: name === "empty.mp4" ? 0 : 4096 };
    },
    releaseClip: (clip) => released.push(clip.src)
  });
  h.tick();
  await h.ready();
  const failed = h.tick();
  assert.equal(failed.ready, false);
  assert.match(failed.note, /empty.mp4 is an empty file/);
  /* The object URL for the empty blob is revoked. An unreleased one is a
   * leak the browser will not collect. */
  assert.deepEqual(released, ["blob:empty.mp4"]);

  h.tick(NOW + 400);
  await h.ready();
  assert.equal(h.tick(NOW + 400).file, "real.mp4");
  h.wall.destroy();
});

test("a clip too long to hold is refused by name, and the refusal says why: that route has no Range support", async () => {
  const h = wallHarness(log(video("feature-length.mp4", 0)), {
    fetchClip: async () => ({ src: "blob:big", bytes: 400 * 1024 * 1024 })
  });
  h.tick();
  await h.ready();
  const state = h.tick();
  assert.equal(state.ready, false);
  assert.match(state.note, /feature-length\.mp4 is 400 MB/);
  assert.match(state.note, /no Range support/);
  h.wall.destroy();
});

test("ComfyUI being down does not take the wall with it: what is playing keeps playing, and it recovers", async () => {
  let down = false;
  const h = wallHarness(null, {
    random: () => 0,
    /* The backstop is pushed out of the way: this test is about the
     * gallery read failing, not about a clip outstaying its welcome. */
    maxClipMs: 10 * 60 * 1000,
    get: async () => {
      if (down) throw new Error("ComfyUI unreachable: connection refused");
      return log(video("a.mp4", 0), video("b.mp4", 1));
    }
  });
  h.tick();
  await h.ready();
  const playing = h.tick();
  assert.equal(playing.ready, true);
  assert.equal(playing.error, "");

  down = true;
  h.tick(NOW + 61000);
  await h.ready();
  const stalled = h.tick(NOW + 61000);
  assert.equal(stalled.ready, true, "the clip already in hand keeps playing");
  assert.equal(stalled.file, playing.file);
  assert.match(stalled.error, /ComfyUI unreachable/);
  assert.ok(stalled.total > 0, "the shelf is not emptied by a failed read");

  down = false;
  h.tick(NOW + 130000);
  await h.ready();
  assert.equal(h.tick(NOW + 130000).error, "");
  h.wall.destroy();
});

test("a still keeps the wall alive when the gallery has no clips", async () => {
  const h = wallHarness(log({ kind: "image", ts: 1, files: ["only-a-picture.png"] }));
  h.tick();
  await h.ready();
  const state = h.tick();
  assert.equal(state.ready, true);
  assert.equal(state.total, 1);
  assert.equal(state.state, "playing");
  assert.equal(state.file, "only-a-picture.png");
  assert.equal(state.error, "");
  h.wall.destroy();
});

test("a clip that never ends is taken off the wall by the backstop, and the log is re-read at most once a minute", async () => {
  let reads = 0;
  const h = wallHarness(log(video("a.mp4", 0), video("b.mp4", 1)), {
    random: () => 0,
    get: async () => { reads += 1; return log(video("a.mp4", 0), video("b.mp4", 1)); }
  });
  h.tick();
  await h.ready();
  const first = h.tick();
  for (let i = 1; i < 50; i += 1) h.tick(NOW + i * 100);
  assert.equal(reads, 1, "fifty paints are not fifty reads of a 1,000-row log");
  assert.equal(h.tick(NOW + 5000).file, first.file);

  const moved = h.tick(NOW + 61000);
  assert.notEqual(moved.file, first.file, "the backstop takes it off the wall");
  await h.ready();
  assert.equal(reads, 2, "and a minute on, the log is worth re-reading");
  h.wall.destroy();
});

test("destroy releases both held clips and stops every road", async () => {
  const h = wallHarness(log(video("a.mp4", 0), video("b.mp4", 1)));
  h.tick();
  await h.ready();
  assert.equal(h.live, 2);
  h.wall.destroy();
  assert.equal(h.live, 0);
  const after = h.tick();
  assert.equal(after.ready, false);
  assert.equal(h.fetched.length, 2, "nothing is fetched after destroy");
});

/* --------------------------------------------------------------- the gate */

function sourceHarness(overrides) {
  let clock = NOW;
  const asked = [];
  const posted = [];
  let inFlight = 0;
  let peak = 0;
  let hold = null;
  const options = Object.assign({
    now: () => clock,
    get: async (route) => {
      asked.push(route);
      inFlight += 1;
      peak = Math.max(peak, inFlight);
      if (hold) await hold;
      await settle();
      inFlight -= 1;
      return { route, at: clock };
    },
    post: async (route, body) => {
      posted.push([route, body]);
      inFlight += 1;
      peak = Math.max(peak, inFlight);
      await settle();
      inFlight -= 1;
      return { ok: true };
    }
  }, overrides || {});
  const source = sourceApi.create(options);
  return {
    source, asked, posted,
    at(value) { clock = value; },
    hold(promise) { hold = promise; },
    get peak() { return peak; },
    async ready() { for (let i = 0; i < 12; i += 1) await settle(); }
  };
}

test("six panes asking at once put exactly ONE question to the station at a time", async () => {
  const h = sourceHarness();
  const wanted = ["/api/schedule/hours?count=3", "/api/generations?limit=1000",
    "/api/music/browse?limit=24", "/api/schedule/segment?hour=x&slot=y",
    "/api/schedule/aired?probe=1", "/api/dj/requested"];
  await Promise.all(wanted.map((route) => h.source.ask(route)));
  assert.equal(h.peak, 1, "the 46-second stall was 38 of these at once");
  assert.equal(h.source.peak(), 1);
  assert.deepEqual(h.asked.slice().sort(), wanted.slice().sort());
  assert.equal(h.source.inFlight(), 0);
});

test("two panes wanting the same route ask it once, and a fresh answer costs no request at all", async () => {
  const h = sourceHarness();
  const route = "/api/generations?limit=1000";
  const [one, two] = await Promise.all([h.source.ask(route), h.source.ask(route)]);
  assert.equal(h.asked.length, 1);
  assert.equal(one, two);

  await h.source.ask(route);
  assert.equal(h.asked.length, 1, "inside its age it is a read of memory");

  /* The gallery log's age is a minute: a render on this box measured
   * 84-102s, so a faster read could not find anything newer. */
  h.at(NOW + 30000);
  await h.source.ask(route);
  assert.equal(h.asked.length, 1);
  h.at(NOW + 61000);
  await h.source.ask(route);
  assert.equal(h.asked.length, 2);
});

test("a failed read keeps the last good answer, so one busy moment does not blank six panes", async () => {
  let fail = false;
  const h = sourceHarness({
    get: async (route) => {
      if (fail) throw new Error("The station is busy.");
      return { route, good: true };
    }
  });
  const route = "/api/schedule/hours?count=3";
  const good = await h.source.ask(route);
  assert.equal(good.good, true);

  fail = true;
  h.at(NOW + 60000);
  await assert.rejects(() => h.source.ask(route), /busy/);
  assert.equal(h.source.held(route).good, true, "the pane still has something to paint");
  assert.match(h.source.trouble(route), /busy/);
});

test("a runaway caller is refused with a sentence instead of piling the queue up", async () => {
  const gate = {};
  gate.promise = new Promise((resolve) => { gate.open = resolve; });
  const h = sourceHarness();
  h.hold(gate.promise);
  const flight = [];
  for (let i = 0; i < sourceApi.QUEUE_MOST + 4; i += 1) {
    flight.push(h.source.ask("/api/thing/" + i).catch((error) => error.message));
  }
  gate.open();
  const done = await Promise.all(flight);
  const refused = done.filter((row) => typeof row === "string" && /dropped rather than piled on/.test(row));
  assert.ok(refused.length >= 1, "the queue has a ceiling");
  assert.equal(h.peak, 1);
});

/* ----------------------------------------------- votes, and only two roads */

test("a line that was CUT votes on the review store the LCD already uses", () => {
  const road = sourceApi.voteRoad({ id: "line-9", review_id: "rej-abc", review_seq: 4 });
  assert.equal(road.road, "review");
  assert.equal(road.route, "/api/orchestrator/rejections/rej-abc");
  assert.equal(sourceApi.voteWord("review", "up"), "allow");
  assert.equal(sourceApi.voteWord("review", "down"), "keep");
});

test("a line that AIRED votes on the station's own feedback store, and there is no third store", () => {
  for (const row of [{ id: "a" }, { id: "b", review_id: "" }, { id: "c", review_id: "x", review_seq: 0 }]) {
    const road = sourceApi.voteRoad(row);
    assert.equal(road.road, "feedback");
    assert.equal(road.route, "/api/feedback");
  }
  assert.equal(sourceApi.voteWord("feedback", "up"), "up");
  assert.equal(sourceApi.voteWord("feedback", "down"), "down");
});

test("an aired line's vote and its note go to /api/feedback in the fields that store already has", async () => {
  const h = sourceHarness();
  const done = await h.source.vote({ id: "row-1", text: "The heron took the whole bridge." },
    "up", "this is the one");
  assert.equal(done.road, "feedback");
  assert.deepEqual(h.posted.length, 1);
  const [route, body] = h.posted[0];
  assert.equal(route, "/api/feedback");
  assert.equal(body.vote, "up");
  assert.match(body.text, /The heron took the whole bridge/);
  assert.match(body.text, /this is the one/);
  assert.ok(body.text.length <= 400, "the store caps text at 400 (app.py:109957)");
  assert.deepEqual(Object.keys(body).sort(), ["text", "vote"]);
});

test("a cut line's vote reads the review first and carries its revision, exactly as the LCD does", async () => {
  const h = sourceHarness({
    get: async (route) => {
      assert.equal(route, "/api/orchestrator/rejections/rej-abc?event_seq=4");
      return { id: "rej-abc", event_seq: 4, revision: 7, review_status: "kept" };
    },
    post: async (route, body) => ({ ok: true, route, body,
      effect: { say: "Wording accepted." } })
  });
  const done = await h.source.vote({ id: "line-9", review_id: "rej-abc", review_seq: 4,
    text: "the cut wording" }, "up", "reads fine to me");
  assert.equal(done.road, "review");
  assert.equal(done.stored.route, "/api/orchestrator/rejections/rej-abc");
  assert.deepEqual(done.stored.body, {
    action: "allow", expected_revision: 7, expected_event_seq: 4, note: "reads fine to me"
  });
  assert.equal(done.why, "Wording accepted.");
});

test("a cut that moved on refuses the vote rather than overwriting somebody else's evidence", async () => {
  const cases = [
    [{ id: "other", event_seq: 4, revision: 7 }, /different cut/],
    [{ id: "rej-abc", event_seq: 9, revision: 7 }, /changed/],
    [{ id: "rej-abc", event_seq: 4 }, /no current review revision/],
    [{ id: "rej-abc", event_seq: 4, revision: 7, occurrence_current: false }, /read-only/]
  ];
  for (const [record, pattern] of cases) {
    const h = sourceHarness({ get: async () => record });
    await assert.rejects(
      () => h.source.vote({ review_id: "rej-abc", review_seq: 4 }, "up", ""),
      pattern);
    assert.equal(h.posted.length, 0, "nothing is written when the evidence is stale");
  }
});

test("every vote goes through the same one-at-a-time gate as the reads", async () => {
  const h = sourceHarness();
  await Promise.all([
    h.source.ask("/api/schedule/hours?count=3"),
    h.source.vote({ id: "a", text: "one" }, "up", ""),
    h.source.vote({ id: "b", text: "two" }, "down", ""),
    h.source.ask("/api/generations?limit=1000")
  ]);
  assert.equal(h.peak, 1);
  assert.equal(h.posted.length, 2);
});

/* ------------------------------------------------------------ the subscription */

test("the view subscribes to the SHARED station feed and starts no poller of its own", async () => {
  let started = 0;
  let stopped = 0;
  let emit = null;
  const source = sourceApi.create({
    get: async () => ({}),
    subscribe: (fn) => { started += 1; emit = fn; return () => { stopped += 1; }; }
  });
  const seen = [];
  const off = source.on((payload) => seen.push(payload.kind));
  source.start();
  source.start();
  assert.equal(started, 1, "twice mounted is still one subscription");

  emit({ kind: "poll", station: { on: true }, rows: [], now: null, at: NOW });
  emit({ kind: "tick", station: { on: true }, rows: [], now: null, at: NOW + 250 });
  assert.deepEqual(seen, ["poll", "tick"]);

  off();
  source.stop();
  assert.equal(stopped, 1);
});

test("a pane that throws never stops the beat reaching the others", () => {
  const source = sourceApi.create({ get: async () => ({}), subscribe: (fn) => { source.fire = fn; return () => {}; } });
  const reached = [];
  source.on(() => { throw new Error("this pane is broken"); });
  source.on((payload) => reached.push(payload.kind));
  source.start();
  source.fire({ kind: "poll", station: null, rows: [], at: NOW });
  assert.deepEqual(reached, ["poll"]);
});
