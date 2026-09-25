/* window.PineScriptLineage - how a moment came to be, read off one payload.
 *
 * THIS FILE IS THE PART THAT CAN BE TESTED. script.js is DOM and gestures,
 * script-stage.js is three.js; both of them ask this module what the
 * station actually said, and neither of them decides anything itself.
 *
 * It reads ONE endpoint - GET /api/dj/provenance/{id} (app.py:95141) -
 * which is already rich: the prompt as sent, the script that came back,
 * model/temp/num_ctx, the render engine and what it fell back from, the
 * crystal shards with `in_prompt` flags, the vector searches, the source
 * documents with `quoted` flags, the schedule slot, the armed system
 * prompt, and whether the audio was prepared ahead or made live.
 *
 * THREE MEASURED FACTS SHAPE EVERY LINE BELOW.
 *
 * 1. THE PAPERWORK EXPIRES. That route answers off `_RADIO["chat"]`, and
 *    the booth ring is trimmed to 240 rows in a dozen places (app.py:24334,
 *    24750, 24989, 52317, 52984 …). Past that it raises 404 with the detail
 *    "That line is no longer in the booth" (app.py:95171). Roughly the last
 *    hour, and a restart empties it. This is a REAL LIMIT, not a bug, and
 *    the operator must be told which of the two he is looking at - hence
 *    readFailure() below, which exists for no other reason.
 *
 * 2. THE BRIDGE THROWS AWAY THE STATUS CODE. `window.pineDesktop.get()`
 *    goes through main.js `fetchJson` (desktop/main.js:422-438), which on a
 *    non-2xx throws `new Error(detail)` - the FastAPI detail string and
 *    nothing else. There is no `.status` to test. The Android bridge is
 *    specified the same way (OkHttp to baseUrl + route). So a 404 reaches
 *    this module AS A SENTENCE, and the only honest thing to do is
 *    recognise the sentence and say so aloud in a comment, which is what
 *    GONE_MARKS is. If someone reworks that detail string in app.py, the
 *    test beside this file fails and names the coupling.
 *
 *    Why not fetch() directly, as sampler.js does for audio bytes? Because
 *    the station sets no Access-Control-Allow-Origin anywhere (there is no
 *    CORS middleware in app.py at all), and the desktop renderer is loaded
 *    from file://. Audio is fetched direct because it has to become bytes;
 *    JSON has a bridge that already works in BOTH products, so it uses it.
 *
 * 3. WHAT IS NOT IN THE PAYLOAD IS AS IMPORTANT AS WHAT IS. There is no
 *    tint before/after, no grader verdict and nothing about learning on
 *    this route. A station drawn empty because nothing happened and a
 *    station drawn empty because the server does not report it are
 *    completely different facts, and merging them is how a pane starts
 *    lying. Every spine station therefore carries `stage2` and, when set, a
 *    `note` naming the server work that would fill it.
 */
(function (root) {
  "use strict";

  /* app.py trims _RADIO["chat"] to this in every writer. */
  const RING_ROWS = 240;

  /* THE SPINE IS THE RAPASSEMBLY SPINE, unchanged.
   *
   * docs/RapAssembly.md and rap_assembly_state() (app.py:129825+) name ten
   * stations in this order: ideation, writing, crystal, tint, grader,
   * recording, stores, schedule, air, learning. /api/rapassembly is a
   * whole-station throughput dashboard with no line identity in it, so
   * none of its DATA is reused - but the spine is the lineage spine, and
   * an operator who knows the 🎛 view should not have to learn a second
   * vocabulary to read this one. */
  const SPINE = [
    {key: "ideation", label: "Ideation",
     what: "the subject, and the material it was built out of"},
    {key: "writing", label: "The writing room",
     what: "who asked the model, with what prompt, and what came back"},
    {key: "crystal", label: "The crystal",
     what: "the shards tinting the water when this line was written"},
    {key: "tint", label: "The tint",
     what: "prose turned into bars - plain script against tinted script"},
    {key: "grader", label: "The grader",
     what: "meaning, rhyme, transformation, copying - pass or refuse"},
    {key: "recording", label: "The recording room",
     what: "which engine spoke it, and what it fell back from"},
    {key: "stores", label: "The stores",
     what: "prepared ahead on the shelf, or made live while you listened"},
    {key: "schedule", label: "The running order",
     what: "the slot this line was written for"},
    {key: "air", label: "On the air",
     what: "how it went out, and the span it occupies in its round"},
    {key: "learning", label: "Learning",
     what: "what the station took from this line afterwards"}
  ];

  /* The three stations the live route cannot fill, and the server work
   * that would. Named here rather than in the view so the same sentence
   * reaches the Script page, the Transcript and the 3D plate. */
  const STAGE2 = {
    tint: "The live provenance route carries no tint. The round's plain "
      + "and tinted scripts are stamped per ROUND under an `sid` "
      + "(data/larder.json, director_scripts.json) and nothing ties an "
      + "aired line id to that sid - app.py:7660 says so outright. Stage 2 "
      + "is that join.",
    grader: "_TINT_JUDGE_RING is 40 entries and memory only (app.py "
      + "rap_assembly_state/_grader), so a verdict older than about a "
      + "minute does not exist to be shown. Stage 2 persists it and puts "
      + "the matching verdict on the per-line payload.",
    learning: "Outcomes, fault memos and repair hints are keyed by road "
      + "and by text fingerprint (data/line_review.sqlite3, 3.0 GB), not "
      + "by line id. Stage 2 is a `?line_id=` lookup built on "
      + "line_review.find_occurrence."
  };

  /* Seats that keep no paperwork. screenplay_pick_lines (app.py:113490)
   * skips a ring row with no `trace` and says why: "a sting has no
   * provenance to keep". This is a HINT on the row, never a gate - see
   * paperworkHint below. */
  const NO_PAPERWORK_KINDS = ["sfx", "marker", "sting"];

  /* The 404 as it actually arrives. See fact (2) in the header: by the
   * time this module sees it, the status code is gone and only the
   * FastAPI detail survives, so the detail IS the status. */
  const GONE_MARKS = [
    "no longer in the booth",      /* app.py:95171, verbatim */
    "no such line",                /* the screenplay routes' wording */
    "404"                          /* the bridge's fallback when detail is lost */
  ];
  const UNREACHABLE_MARKS = [
    "fetch failed", "failed to fetch", "network", "econnrefused",
    "econnreset", "etimedout", "enotfound", "timeout", "timed out",
    "aborted", "socket hang up"
  ];

  function text(value) { return value == null ? "" : String(value); }
  function lower(value) { return text(value).toLowerCase(); }

  /* Punctuation, case and the "A:" speaker marks are all noise when the
   * question is "is this the same sentence". */
  function bare(value) {
    return lower(value)
      .replace(/^\s*[a-e]\s*:\s*/gm, " ")
      .replace(/[^a-z0-9]+/g, " ")
      .trim();
  }

  /* ------------------------------------------------------------ failure */

  /* The pane must NEVER go blank and leave the operator wondering whether
   * it is broken. Every failure becomes a sentence with a cause. */
  function readFailure(err) {
    const raw = text(err && err.message ? err.message : err).trim();
    const probe = lower(raw);

    if (!raw) {
      return {
        kind: "unknown",
        title: "The station answered with nothing",
        say: "The request failed and carried no message at all. That is "
          + "the bridge, not the booth - try the line again.",
        detail: ""
      };
    }
    if (GONE_MARKS.some((mark) => probe.indexOf(mark) >= 0)) {
      return {
        kind: "gone",
        title: "That line is no longer in the booth",
        say: "Nothing is broken. Provenance is answered off the live booth "
          + "ring, and the station trims that ring to " + RING_ROWS
          + " rows - roughly the last hour, and a restart empties it. Past "
          + "that the paperwork is simply gone (app.py:95171).",
        /* Worth saying, because the operator's next question is "so is it
         * gone forever?" and the answer is no. */
        stage2: "A narrower durable record IS kept: data/screenplay_lines."
          + "jsonl holds the model call and the render for 48 h, and "
          + "/api/screenplay/{hour_key}/line/{line_id} already serves it. "
          + "This view is stage 1 and does not read it yet.",
        detail: raw
      };
    }
    if (UNREACHABLE_MARKS.some((mark) => probe.indexOf(mark) >= 0)) {
      return {
        kind: "unreachable",
        title: "The station did not answer",
        say: "The box could not be reached. It is a live radio station "
          + "writing and recording audio, so a request can also simply "
          + "queue behind that work - try it again before assuming it is "
          + "down.",
        detail: raw
      };
    }
    return {
      kind: "unknown",
      title: "The station refused that line",
      /* Verbatim, never paraphrased: an unrecognised error is exactly the
       * case where guessing at the cause does the most damage. */
      say: raw,
      detail: raw
    };
  }

  /* -------------------------------------------------------------- hints */

  /* Is there likely to be paperwork behind this feed row? A hint drawn on
   * the row, and nothing more. The route does not gate on kind - it gates
   * on the id being in the ring - so gating the TAP here would invent a
   * refusal the station never made. */
  function paperworkHint(row) {
    const one = row || {};
    const kind = lower(one.kind);
    if (!text(one.id)) {
      return {tappable: false, keeps: false,
        why: "that row has no id, so there is nothing to ask about"};
    }
    if (one.sfx || NO_PAPERWORK_KINDS.indexOf(kind) >= 0) {
      return {tappable: true, keeps: false,
        why: "a sting has no provenance to keep"};
    }
    return {tappable: true, keeps: true, why: ""};
  }

  /* ------------------------------------------------------- the transcript */

  /* THE ROUND, RECONSTRUCTED FROM THE FEED - no server change needed.
   *
   * A welded round is one audio file; every turn inside it carries the
   * same `clip_media` plus its own `clip_from`/`clip_until` span
   * (app.py:25295 and the #908 note on the provenance payload). So the
   * rows that share a clip_media ARE the round, and their spans order
   * them. That is a real join, available today, and it is what the
   * Transcript presentation shows.
   *
   * It is NOT the sid join. It recovers the turns that were welded into
   * one file, which is a narrower thing than the round the writer wrote. */
  function roundOf(rows, id) {
    const all = Array.isArray(rows) ? rows : [];
    const want = text(id);
    let here = null;
    for (const row of all) {
      if (text(row && row.id) === want) { here = row; break; }
    }
    if (!here) return {rows: [], welded: false, key: "", found: false};

    const key = text(here.clip_media);
    if (!key) {
      return {rows: [mark(here, want)], welded: false, key: "", found: true};
    }
    const kin = all.filter((row) => text(row && row.clip_media) === key);
    kin.sort((a, b) => Number(a.clip_from || 0) - Number(b.clip_from || 0));
    return {
      rows: kin.map((row) => mark(row, want)),
      welded: kin.length > 1,
      key,
      found: true
    };
  }

  function mark(row, want) {
    const one = row || {};
    return {
      id: text(one.id),
      who: text(one.name || one.who || one.kind || "booth"),
      text: text(one.text),
      from: Number(one.clip_from || 0),
      until: Number(one.clip_until || 0),
      aired: text(one.aired),
      here: text(one.id) === want
    };
  }

  /* ------------------------------------------------------- the stations */

  function station(key, filled, head, rows, leaves) {
    const spec = SPINE.find((s) => s.key === key) || {key, label: key, what: ""};
    const note = STAGE2[key] || "";
    return {
      n: SPINE.indexOf(spec) + 1,
      key: spec.key,
      label: spec.label,
      what: spec.what,
      /* A station the server cannot report is never "filled", whatever
       * arrives in the payload. Drawing it lit would be the pane claiming
       * knowledge it does not have. */
      filled: note ? false : !!filled,
      stage2: !!note,
      note,
      head: text(head),
      rows: (rows || []).filter(Boolean).map(text),
      leaves: (leaves || []).filter(Boolean)
    };
  }

  /* A leaf is one contributing item, and `on` is the ONE thing that
   * matters about it: did it actually reach the prompt, or was it merely
   * staged nearby? The route computes both flags (`in_prompt` on crystal
   * shards, `quoted` on documents) by substring against the prompt as
   * sent, so this is the station's own answer, not an inference. */
  function leaf(body, on, why) {
    return {text: text(body), on: !!on, why: text(why)};
  }

  /* ---------------------------------------------------------------- read */

  function read(payload) {
    const got = payload && typeof payload === "object" ? payload : {};
    const line = got.line || {};
    const written = got.written || {};
    const render = got.render || {};
    const sched = got.schedule || {};
    const system = got.system || {};
    const docs = Array.isArray(got.documents) ? got.documents : [];
    const shards = Array.isArray(got.crystal) ? got.crystal : [];
    const vectors = Array.isArray(got.vectors) ? got.vectors : [];
    const material = Array.isArray(got.material) ? got.material : [];
    const requests = Array.isArray(got.requests) ? got.requests : [];

    const said = text(line.text || line.analysis);
    const answered = text(written.script);
    const prompt = text(written.prompt);

    const spine = [];

    spine.push(station("ideation",
      docs.length || text(line.source) || vectors.length,
      text(line.source) || (docs.length ? docs.length + " document(s) reached this line" : ""),
      [
        line.kind ? "filed as a " + text(line.kind) + " line" : "",
        vectors.length ? vectors.length + " vector search(es) around it" : "",
        requests.length ? requests.length + " standing request(s) in view" : ""
      ],
      docs.map((d) => leaf(
        text(d.file) + (d.how ? " - " + text(d.how) : ""),
        d.quoted,
        d.quoted ? "quoted in the prompt as sent"
          : "reached the line, but its words are not in the prompt"))
        .concat(vectors.map((v) => leaf(
          text(v.file || v.query || "a search")
            + (v.score != null ? " · " + v.score : ""), true, "a vector hit")))));

    spine.push(station("writing",
      !!(text(written.model) || prompt || answered),
      text(written.model),
      [
        written.temp != null ? "temperature " + written.temp : "",
        written.num_ctx ? "context window " + written.num_ctx : "",
        written.ms ? "wrote it in " + written.ms + " ms" : "",
        written.chars ? written.chars + " characters came back" : "",
        written.budget ? "budget " + text(written.budget) : "",
        prompt ? prompt.length + " characters of prompt, as sent"
          : "the prompt was not kept for this row",
        system.name ? "armed: " + text(system.name) : "",
        /* #983, and the route reports it as two: the agent's prompt
         * governs the assistant and NOTHING about the booth. Repeating
         * that here keeps the two from being read as one. */
        system.station_followed
          ? "the booth is following the station's standing instructions"
          : "the booth is not bound to the agent's armed prompt"
      ],
      material.map((m) => leaf(
        text(m.text), true,
        m.tally ? "a tally about him was in the prompt"
          : "his own material, in the prompt"))));

    const inPrompt = shards.filter((s) => s && s.in_prompt).length;
    spine.push(station("crystal", shards.length,
      shards.length
        ? inPrompt + " of " + shards.length + " shard(s) reached the prompt"
        : "",
      shards.length
        ? []
        : ["no crystal material was staged around this line"],
      shards.map((s) => leaf(
        text(s.text || s.file), s.in_prompt,
        s.in_prompt ? "in the prompt as sent"
          : "staged for the booth, but not in this prompt"))));

    spine.push(station("tint", false, "", [], []));
    spine.push(station("grader", false, "", [], []));

    spine.push(station("recording",
      !!(text(render.engine) || text(line.engine) || text(line.voice)),
      text(line.voice) + (line.engine || render.engine
        ? " · " + text(line.engine || render.engine) : ""),
      [
        render.ms ? "rendered in " + render.ms + " ms" : "",
        render.kb ? render.kb + " kB of audio" : "",
        line.seconds ? line.seconds + "s on air" : "",
        render.fallback ? "fell back from " + text(render.fallback) : "",
        (render.tried || []).length ? "tried: " + (render.tried || []).join(", ") : "",
        text(render.service)
      ], []));

    spine.push(station("stores",
      !!(text(got.prepared) || text(got.how)),
      text(got.prepared),
      [text(got.how) ? "the room stamped this take \"" + text(got.how) + "\"" : ""],
      []));

    spine.push(station("schedule",
      !!(text(sched.kind) || text(sched.prompt)),
      text(sched.kind) || text(sched.kind_now),
      [
        text(sched.prompt) || text(sched.prompt_now),
        sched.kind && sched.kind_now && sched.kind !== sched.kind_now
          ? "the hour has moved on - it is a " + text(sched.kind_now)
            + " slot now" : ""
      ], []));

    spine.push(station("air",
      !!(text(line.aired) || got.burst || text(line.clip_media)),
      text(line.aired) ? "went out " + text(line.aired) : "",
      [
        got.burst ? "aired in a burst of " + got.burst : "",
        text(line.clip_media)
          ? "welded into " + text(line.clip_media) + " at "
            + Number(line.clip_from || 0).toFixed(2) + "-"
            + Number(line.clip_until || 0).toFixed(2) + "s"
          : "not welded into a round - it has its own take",
        line.ts ? "written at " + new Date(Number(line.ts) * 1000).toLocaleTimeString() : ""
      ], []));

    spine.push(station("learning", false, "", [], []));

    return {
      ok: true,
      id: text(got.id || line.id),
      line,
      said,
      answered,
      prompt,
      diverged: divergence(said, answered),
      spine,
      filled: spine.filter((s) => s.filled).length,
      pending: spine.filter((s) => s.stage2).length
    };
  }

  /* DID THE LINE GO OUT THE WAY THE MODEL WROTE IT?
   *
   * `written.script` is what came back from the model - usually the WHOLE
   * round, several turns of it. The aired line is one turn out of that, so
   * the honest test is containment, not equality. When the aired words are
   * not in the script the model returned, something changed them after the
   * answer: the tint, a repair, or the trim. Stage 1 cannot say WHICH -
   * that is the tint history, and the tint history is keyed by sid. So it
   * reports the fact and names the gap rather than picking a culprit. */
  function divergence(said, answered) {
    if (!said) {
      return {known: false, verbatim: false,
        why: "there is no aired text on this row to compare"};
    }
    if (!answered) {
      return {known: false, verbatim: false,
        why: "the script the model returned was not kept for this row, so "
          + "there is nothing to compare the aired line against"};
    }
    const needle = bare(said);
    const hay = bare(answered);
    if (needle && hay.indexOf(needle) >= 0) {
      return {known: true, verbatim: true,
        why: "the line went out as the model wrote it"};
    }
    return {known: true, verbatim: false,
      why: "the line as aired is not in the script the model returned - "
        + "the tint, a repair or the trim changed it after the answer. "
        + "Which one is stage 2: the tint history is keyed by the round's "
        + "sid, and no sid reaches an aired line today (app.py:7660)."};
  }

  /* ---------------------------------------------------------- the pages */

  /* The Script presentation, as ordered sections. The order is an
   * argument, not a layout: the line, then the answer it came out of,
   * then the question that produced the answer, then everything that fed
   * the question. Reading down the page is reading backwards in time. */
  function page(lineage) {
    const got = lineage || {};
    const out = [
      {key: "said", title: "The line, as it aired", body: got.said,
       kind: "quote"},
      {key: "answered", title: "The script the model returned",
       body: got.answered, kind: "script",
       note: (got.diverged || {}).why || ""},
      {key: "prompt", title: "The prompt, as sent", body: got.prompt,
       kind: "prompt",
       /* Never truncated. The prompt is the thing the operator opened
        * this view for; a clipped prompt answers a different question
        * from the one he asked. */
       note: got.prompt ? got.prompt.length + " characters" : ""}
    ];
    for (const one of got.spine || []) out.push({
      key: one.key, title: one.n + ". " + one.label, kind: "station",
      station: one
    });
    return out;
  }

  const lineage = {
    RING_ROWS, SPINE, STAGE2,
    read, readFailure, paperworkHint, roundOf, page, divergence,
    /* exported for the tests and for script-stage.js, which draws the
     * same normalisation on its plates */
    bare
  };

  if (typeof module !== "undefined" && module.exports) module.exports = lineage;
  root.PineScriptLineage = lineage;
})(typeof window !== "undefined" ? window : globalThis);
