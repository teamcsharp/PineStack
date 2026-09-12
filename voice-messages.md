# Voice messages: a text-to-speech system you can rebuild anywhere

A technical specification for adding **spoken messages** to any messaging
application: the user types text, picks a voice, and sends it as audio that plays
in the conversation.

This document is implementation-agnostic. It assumes nothing about your
framework, language, database, or hosting. Code samples are illustrative — the
contracts and invariants are the deliverable.

**Contents**

1. [The core design decision](#1-the-core-design-decision)
2. [Architecture](#2-architecture)
3. [The synthesis provider](#3-the-synthesis-provider)
4. [The generation endpoint](#4-the-generation-endpoint)
5. [Storage and serving](#5-storage-and-serving)
6. [Spend control](#6-spend-control)
7. [The caption](#7-the-caption)
8. [The client: composer](#8-the-client-composer)
9. [The client: renderer](#9-the-client-renderer)
10. [Optional: ephemeral voice notes](#10-optional-ephemeral-voice-notes)
11. [Testing](#11-testing)
12. [Security and correctness invariants](#12-security-and-correctness-invariants)
13. [Failure modes that will bite you](#13-failure-modes-that-will-bite-you)
14. [Scope boundaries](#14-scope-boundaries)

---

## 1. The core design decision

**A voice message is not a message type.**

This single decision determines how much code the feature costs. The intuitive
design adds a discriminator — a `kind` column, a `{type: 'voice'}` event, a
dedicated component, a voice-specific delete path, a voice-specific history
query. Every one of those is avoidable.

Instead: **a voice message is an ordinary text message whose body is a media
URL.**

```
body = "/media/9f3c1a2b4d5e6f708192a3b4c5d6e7f8.mp3"
```

The renderer inspects the body. If it matches the shape of a media path, it
renders a player instead of text. Nothing else in the system knows voice
messages exist.

### What this buys you

If your application already supports **any** kind of media message — image
attachments, file uploads, voice recordings — then adding TTS inherits all of
this for free, with zero new code in each area:

| Capability | Comes from |
|---|---|
| Renders as an audio player | Your existing media renderer |
| Playback controls | The native `<audio>` element |
| Persistence and history | It's a normal message row |
| Direct messages / private channels | Your DM path already accepts any body |
| Deletion (including the stored bytes) | Your existing media delete cascade |
| Access control on the audio | Your existing media route's auth |
| Storage accounting | Your existing storage ledger |
| Range requests / seeking | Your existing media serving |
| Search, pagination, unread counts | Untouched — it's a normal row |

**If your app has no media messages yet, build that first.** An upload endpoint
plus a media renderer is more broadly useful than anything TTS-specific, and
once it exists, TTS is roughly a hundred lines on top of it.

### What genuinely needs building

Only three things:

1. **A generation endpoint** — text + voice in, stored audio URL out.
2. **A voice picker** in the composer.
3. **A caption field** — the text the audio was spoken from, stored alongside
   the message. Optional in principle; in practice it is what makes the feature
   accessible, searchable, and readable on mute.

Plus one optional layer: **ephemerality** (§10), if you want speech to behave
like a moment rather than a permanent artifact.

---

## 2. Architecture

```
┌─ CLIENT ────────────────────────────────────────────────────────────┐
│                                                                     │
│  Composer, with voice "V" selected                                  │
│  User types TEXT → Send                                             │
│                                                                     │
│                 POST /api/say { text: TEXT, voice: V }              │
└────────────────────────────────┬────────────────────────────────────┘
                                 ▼
┌─ SERVER: generation endpoint ───────────────────────────────────────┐
│                                                                     │
│  1. authenticate ......................... 401                      │
│  2. voice ∈ ALLOWLIST .................... 400                      │
│  3. len(text) ≤ MAX_CHARS ................ 413                      │
│  4. reserve budget (atomic) .............. 429                      │
│  5. audio = synthesize(text, voice)                                 │
│        └── on failure: refund budget ..... 502                      │
│  6. key = random_hex(16) + "." + EXT   ← SERVER mints the key       │
│  7. store(key, audio, content_type=..., metadata=...)               │
│  8. → { path: "/media/<key>" }                                      │
└────────────────────────────────┬────────────────────────────────────┘
                                 ▼
┌─ CLIENT ────────────────────────────────────────────────────────────┐
│                                                                     │
│  send_message({ body: "/media/<key>", caption: TEXT })              │
│                            ▲                                        │
│              the returned path IS the message body                  │
└────────────────────────────────┬────────────────────────────────────┘
                                 ▼
┌─ SERVER: message store (unchanged except for `caption`) ────────────┐
│                                                                     │
│  caption = sanitize_caption(caption, body)  ← only kept on media    │
│  INSERT INTO messages (..., body, caption)                          │
│  broadcast to recipients                                            │
└────────────────────────────────┬────────────────────────────────────┘
                                 ▼
┌─ EVERY CLIENT ──────────────────────────────────────────────────────┐
│                                                                     │
│  render(message, is_live)                                           │
│    MEDIA_PATH.test(body)?                                           │
│      ├── yes + caption → voice note:  <audio> + caption text        │
│      ├── yes, no caption → ordinary media attachment                │
│      └── no → plain text (textContent, never innerHTML)             │
│                                                                     │
│  <audio src="/media/<key>"> → GET, authenticated, served with the   │
│  server's own Content-Type + nosniff                                │
└─────────────────────────────────────────────────────────────────────┘
```

### Why synchronous generation

The endpoint blocks until the audio exists — typically 0.5–2 seconds — and only
then is a message created. This is deliberate and, for messages of a few hundred
characters, correct:

- **No job queue, no worker pool, no polling.** Substantial infrastructure that
  buys nothing at this latency.
- **No placeholder message that later mutates.** A "generating…" bubble that
  becomes a player is more states, more races, and worse history.
- **A failure creates no message at all.** The error is local and ephemeral to
  the sender. Nobody else sees a broken bubble, and nothing is left in history
  to clean up.

Show a local, non-persisted status line while the request is in flight
("*generating…*"), and rewrite it in place on failure.

**Reconsider this** only if you allow long text (thousands of characters) or your
provider is slow. Then generate asynchronously and have the completion path send
the message — but keep the rule that a message is only created on success.

---

## 3. The synthesis provider

Isolate the provider behind one function. Nothing else in the system should know
which engine you use:

```
synthesize(text: string, voice: string) -> bytes
```

That is the entire seam. The endpoint, the caps, the storage, the client, and
the tests are all provider-independent.

### Choosing an engine

| Option | Voices | Cost model | Runs where | Notes |
|---|---|---|---|---|
| **Hosted TTS API** | Many, named | Per character or per second | Anywhere with outbound HTTP | Lowest integration cost; no model to host; recurring spend |
| **Platform AI binding** | Depends | Per character | Serverless platforms that offer one | Same as above, minus API key management |
| **Small local model** (Piper class) | One model *per voice*, 20–60 MB each | Free after download | Any real OS with a filesystem | "Variety of voices" costs one model per voice |
| **Compact multi-voice model** (Kokoro-82M class) | ~50 in a single ~86 MB model | Free after download | Server *or* browser (ONNX / WASM / WebGPU) | Best fit for "small, optimized, many voices" |
| **Browser `speechSynthesis`** | OS voices | Free | Browser only | ⚠️ **Cannot produce an audio file** — see below |

### Serverless constraints

If your server runs in a constrained sandbox — edge runtimes, isolate-based
workers, environments without a filesystem or native module support — **a local
model is not an option.** There is nowhere to place model weights and no
inference runtime to load them. Your choices reduce to a hosted API, a platform
binding, or moving generation into the browser (§3.2).

Check for: filesystem access, native addon support (ONNX runtime, ffmpeg),
memory ceiling, and request duration limits.

### 3.1 Reference: a hosted HTTP provider

```js
async function synthesize(text, voice) {
  const r = await fetch(`${PROVIDER_URL}?model=${voice}&encoding=mp3`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${process.env.TTS_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ text }),
  });
  if (!r.ok) throw new Error(`tts ${r.status}`);
  return Buffer.from(await r.arrayBuffer());
}
```

If your platform exposes TTS as a binding rather than an HTTP API, the body of
this function is the only thing that changes:

```js
async function synthesize(text, voice) {
  const stream = await platform.ai.run(MODEL_ID, {
    text, speaker: voice, encoding: 'mp3',
  });
  return Buffer.from(await new Response(stream).arrayBuffer());
}
```

Note the **buffering**. Piping the provider's stream directly into storage is
tempting but costs you two things: an exact byte count for the ledger, and the
ability to detect an empty or truncated generation *before* anything is written.
For a few hundred KB, buffer.

### 3.2 Reference: generating in the browser

Structurally this changes **nothing** downstream:

```
generate audio in-browser (WASM / WebGPU)
  → POST the blob to your existing upload endpoint
  → receive "/media/<key>.wav"
  → send it as the message body, exactly as before
```

You add the new extension to your content-type table and your renderer's tag
map. The message model, caption, storage, history, deletion, and DMs are
untouched. This is the payoff of §1: the engine is swappable because nothing
downstream knows there was an engine.

Trade-offs: a one-time model download per device (tens to hundreds of MB — check
whether your static-asset host has a per-file size cap; many do), a WASM/WebGPU
capability check with a server-side fallback, and generation time on the user's
hardware. Excellent on desktop, often unacceptable on phones.

### 3.3 Why `speechSynthesis` cannot do this

The browser's built-in speech API looks like the free answer. It is not, for one
structural reason: **there is no reliable way to capture its output to a blob.**

Consequences:
- No audio file exists, so nothing can be stored, sent, or replayed later.
- Every recipient hears their own device's voices, which differ by OS and
  browser and may not include the voice the sender chose.
- History holds no artifact — only text you re-speak locally.

That is a different, weaker feature ("read this message aloud to me"), not an
implementation detail of this one. If it's what you want, build it; just don't
expect it to satisfy "send a voice message."

### 3.4 Encoding and extension must agree

Most TTS APIs default to uncompressed WAV or raw PCM (`linear16`), **not** MP3.
Request your encoding explicitly.

This matters because of invariant §12.5: you serve media with a `Content-Type`
derived from **your own** extension table, never from the stored file. So a
`.mp3` key holding WAV bytes is served as `audio/mpeg` and produces a player
that silently does nothing.

> **Change these four together, always:** the requested encoding, the file
> extension, the content-type table entry, and the renderer's tag-map entry.

---

## 4. The generation endpoint

```js
const VOICES = new Set(['alloy', 'ember', 'sage', /* … */]);  // your provider's voices
const MAX_CHARS = 300;
const DAILY_CHARS = 20_000;
const EXT = 'mp3';

app.post('/api/say', async (req, res) => {
  // 1. AUTHENTICATE. This endpoint costs money per call.
  const user = await authenticate(req);
  if (!user) return res.status(401).json({ error: 'unauthorized' });

  // 2. Degrade gracefully if the provider isn't configured yet, so that
  //    deploying this code before enabling the provider cannot break the app.
  if (!providerReady()) return res.status(503).json({ error: 'voices not enabled' });

  const text  = String(req.body?.text  ?? '').trim();
  const voice = String(req.body?.voice ?? '');

  // 3. VALIDATE. The voice allowlist is server-side and is the actual gate;
  //    the client picker is convenience. Never pass a client-supplied string
  //    through to a model, a URL, or a filename.
  if (!text)                return res.status(400).json({ error: 'nothing to say' });
  if (!VOICES.has(voice))   return res.status(400).json({ error: 'no such voice' });
  if (text.length > MAX_CHARS)
    return res.status(413).json({ error: `${MAX_CHARS} characters max` });

  // 4. RESERVE the budget atomically, before spending it (§6).
  const period = budgetKey();
  if (!await reserve(period, text.length, DAILY_CHARS))
    return res.status(429).json({ error: 'daily voice budget spent' });

  // 5. SYNTHESIZE. Refund on failure so a broken provider doesn't bill users.
  let audio;
  try {
    audio = await synthesize(text, voice);
  } catch (err) {
    await refund(period, text.length);
    return res.status(502).json({ error: `synthesis failed — ${err.message}` });
  }
  if (!audio?.length) {
    await refund(period, text.length);
    return res.status(502).json({ error: 'synthesis returned nothing' });
  }

  // 6. THE SERVER MINTS THE KEY. Never a client-supplied name (§12.4).
  const key = randomHex(16) + '.' + EXT;

  // 7. STORE with an explicit content type, and metadata if you want a TTL.
  await mediaStore.put(key, audio, {
    contentType: 'audio/mpeg',
    metadata: { voice: '1' },      // only if implementing §10
  });

  res.json({ ok: true, path: `/media/${key}` });
});
```

### Status codes

Use distinguishable codes — the client surfaces the message verbatim, and you
will debug this from logs.

| Code | Meaning |
|---|---|
| `400` | Empty text, or a voice not on the allowlist |
| `401` | Not authenticated |
| `413` | Over the per-message character cap |
| `429` | Over the period budget |
| `502` | The provider failed or returned nothing |
| `503` | The provider isn't configured — deploy-safe degradation |

### Deploy-safe degradation

Guard on provider configuration and return `503` rather than throwing. This lets
you ship the code before enabling the provider (or with the credential absent in
some environments) without breaking anything else in the app. A missing feature
should be a disabled button, not a crash.

---

## 5. Storage and serving

### Key shape

The server generates the key. It must have a **fixed, validatable shape**:

```
^[a-f0-9]{32}\.(mp3|wav)$
```

Validate against this regex on **every read**, before touching storage. This
single check defeats path traversal (`../../etc/passwd`), absolute paths, and
null-byte tricks — because none of them match.

128 bits of randomness makes the key unguessable, but **unguessable is not
access control** (§12.2).

### Serving

```js
const MEDIA_TYPES = { mp3: 'audio/mpeg', wav: 'audio/wav' };
const KEY_SHAPE = /^[a-f0-9]{32}\.[a-z0-9]+$/;

app.get('/media/:key', async (req, res) => {
  // Auth first — if messages are private, so is their audio.
  if (!await authenticate(req)) return res.sendStatus(401);

  const { key } = req.params;
  const ext = key.split('.').pop();

  // hasOwn, not a bare lookup — see §12.6. This is not paranoia.
  if (!KEY_SHAPE.test(key) || !Object.hasOwn(MEDIA_TYPES, ext)) {
    return res.sendStatus(404);
  }

  const obj = await mediaStore.get(key);
  if (!obj) return res.sendStatus(404);

  res.set({
    'Content-Type': MEDIA_TYPES[ext],        // OURS, never the stored file's
    'X-Content-Type-Options': 'nosniff',
    'Accept-Ranges': 'bytes',
    'Cache-Control': 'private, max-age=31536000, immutable',
  });
  return sendWithRangeSupport(res, obj, req.headers.range);
});
```

**Range support is not optional.** Some mobile browsers — iOS Safari most
notably — refuse to play media they cannot seek within. Most server frameworks'
static-file helpers implement `Range` already; if you stream from object storage
by hand, you must implement `206 Partial Content` yourself.

**Immutable caching is safe** because keys are random and content is never
overwritten. Mark it `private` so shared caches don't retain authenticated
media.

### Deletion

If your app deletes messages, cascade to the stored bytes — and check that no
other message references the same path before deleting, since forwarding or
duplication can create shared references:

```sql
SELECT COUNT(*) FROM messages WHERE body = ?
```

Refund the storage ledger by the deleted object's size.

---

## 6. Spend control

A TTS endpoint behind a session cookie is **a metered faucet**. One user with a
paste buffer, one script, or one leaked credential and the bill is unbounded.
This is the single most important non-obvious part of the feature.

Two caps, both enforced server-side, both hard:

```js
const MAX_CHARS  = 300;      // per message
const DAILY_CHARS = 20_000;  // per period, across all users
```

**Both are required.** A per-message cap alone still permits unlimited messages.
A period cap alone still permits one enormous request.

Size the period cap by working backwards from a bill you'd accept. At a typical
$0.015 per 1,000 characters, 20,000 characters/day is roughly $0.30/day —
a ceiling, not a budget you expect to reach.

### Reserve, don't read-then-write

This is the part that is easy to get wrong, and the wrong version passes every
single-threaded test.

```js
// ❌ WRONG — concurrent requests all read the same total and all pass
const spent = await db.get('SELECT n FROM ledger WHERE k = ?', period);
if (spent + text.length > DAILY_CHARS) return res.status(429).json(…);
await db.run('UPDATE ledger SET n = n + ? WHERE k = ?', text.length, period);
```

```js
// ✅ RIGHT — a conditional UPDATE reserves and checks in one atomic step
async function reserve(period, n, cap) {
  const r = await db.run(
    `UPDATE ledger SET n = n + ?1 WHERE k = ?2 AND n + ?1 <= ?3`,
    n, period, cap,
  );
  return r.changes > 0;    // zero rows changed == the cap would be exceeded
}

async function refund(period, n) {
  await db.run('UPDATE ledger SET n = MAX(0, n - ?) WHERE k = ?', n, period);
}
```

Reserve **before** calling the provider; refund if it fails. That ordering is
what makes the cap actually hold under concurrency while still not billing users
for failures.

If your datastore can't do a conditional update, serialize the counter behind a
single writer (a lock, an actor, a dedicated connection).

### Ledger storage

You almost certainly don't need a new table. Any key-value counter works, and a
generic `(key TEXT PRIMARY KEY, n INTEGER)` table can hold every kind of
accounting at once:

```
'storage:total'      → bytes currently stored
'tts:2026-08-07'     → characters synthesized today
```

One small row per day is cheaper than a cleanup job. Don't build one.

### Rate limiting

The period cap bounds cost but not *behaviour* — one user can exhaust the shared
budget in a minute. If that matters, add a per-user token bucket. It is a
separate concern from spend, and worth deferring until someone actually abuses
it.

---

## 7. The caption

**Store the text the audio was spoken from, alongside the message.**

This is not decoration:

- **Accessibility.** A voice-only message is unusable for deaf and
  hard-of-hearing users. The caption makes it a text message that also speaks.
- **Readable on mute.** Most messaging happens in places where audio isn't
  welcome.
- **Searchable.** Audio is invisible to every search index you have.
- **It is the permanent record** if you implement ephemerality (§10) — the audio
  goes away; the words don't.

### Schema

One nullable column on your existing message table:

```sql
ALTER TABLE messages ADD COLUMN caption TEXT;
```

If your message store has no migration framework, an idempotent
try/ignore at startup is a legitimate pattern:

```js
for (const col of ['caption TEXT']) {
  try { db.exec(`ALTER TABLE messages ADD COLUMN ${col}`); } catch {}
}
```

Then thread it through exactly four places: the insert, the broadcast payload,
the history query's `SELECT`, and the history row mapping. **Deletion needs no
change** — it keys off the body.

### Sanitize on write

A caption is only meaningful on a media message. On a plain text message it
would be a second, competing body — so drop it there:

```js
const MEDIA_PATH = /^\/media\/[a-f0-9]{32}\.[a-z0-9]+$/;
const MAX_CAPTION = 300;

function sanitizeCaption(raw, body) {
  if (!MEDIA_PATH.test(body)) return null;
  return String(raw ?? '').slice(0, MAX_CAPTION).trim() || null;
}
```

The presence of a caption is also a useful **discriminator in the renderer**:
media *with* a caption is a voice note; media *without* one is an ordinary
attachment someone uploaded. This lets the two coexist with no type field.

### Trust boundary

The server cannot verify that the caption matches what was actually synthesized
— a crafted client request can pair any media path with any text. Whether this
matters depends entirely on your threat model:

- **Closed / trusted group:** it's a prank surface, not a security issue. Accept
  it and document it.
- **Open / public app:** it's a misrepresentation vector. Have the generation
  endpoint return an HMAC over `{path, text}` and have the message endpoint
  verify it before accepting the caption.

---

## 8. The client: composer

### Arming a voice

The composer has two modes. Pressing the voice button reveals a picker; choosing
a voice **arms** the composer so the next send is spoken. Pressing the button
again disarms it.

Persist the selection (local storage is fine) so it survives reloads.

```js
const VOICES = [['alloy', 'Alloy'], ['ember', 'Ember'], /* … */];
const MAX_CHARS = 300;          // MUST equal the server's cap
let voice = loadStored('voice') || '';

function setVoice(name) {
  voice = name;
  storeValue('voice', name);
  toggleButton.classList.toggle('armed', !!name);
  picker.hidden = !name;

  // The composer states what it will do, and prevents walking into a 413.
  input.maxLength = name ? MAX_CHARS : NORMAL_MAX;
  input.placeholder = name ? `Say something as ${name}…` : 'Say something…';
  if (name && input.value.length > MAX_CHARS) {
    input.value = input.value.slice(0, MAX_CHARS);
  }
}
```

> Client and server caps must match. They live in two files in two languages;
> put a comment on each pointing at the other. A mismatch ships a `413` that
> users can walk into with no warning.

### Sending

The hook into your existing submit handler is one line:

```js
form.addEventListener('submit', (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  input.value = '';

  if (voice) { sendVoice(text); return; }    // ← the entire integration point

  sendMessage({ body: text });               // your existing path, untouched
});
```

```js
async function sendVoice(text) {
  // A local, non-persisted status line. Not a message — nothing is broadcast
  // and nothing enters history unless generation succeeds.
  const note = showLocalStatus(`generating…`);
  try {
    const r = await fetch('/api/say', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, voice }),
    });
    const d = await r.json();
    if (!d.path) throw new Error(d.error || 'synthesis failed');

    // The path is the body. Preserve whatever routing context the composer is
    // in — a DM stays a DM, a thread reply stays a reply.
    sendMessage({ body: d.path, caption: text });
    note.remove();
  } catch (err) {
    note.textContent = `couldn't send that — ${err.message}`;
  }
}
```

Two properties worth preserving:

- **The failure is local and ephemeral.** Only the sender sees it. Nothing
  persists, nothing needs cleaning up.
- **Routing context is inherited.** If your composer targets a DM, a thread, or
  a channel, the voice message goes to the same place. Reuse the same send
  function your file-upload path uses; don't write a parallel one.

---

## 9. The client: renderer

The renderer branches on the **body**, not on a type field:

```js
const MEDIA_PATH = /^\/media\/[a-f0-9]{32}\.[a-z0-9]+$/;
const MEDIA_TAG  = { mp3: 'audio', wav: 'audio', png: 'img', jpg: 'img' };

function mediaElement(path) {
  const ext = path.split('.').pop();
  // hasOwn — a bare lookup reaches Object.prototype (§12.6)
  const tag = Object.hasOwn(MEDIA_TAG, ext) ? MEDIA_TAG[ext] : 'video';
  const el = document.createElement(tag);
  el.src = path;
  if (tag !== 'img') { el.controls = true; el.playsInline = true; }
  return el;
}

function renderMessage(m, isLive) {
  const bubble = document.createElement('div');

  if (MEDIA_PATH.test(m.body)) {
    const player = mediaElement(m.body);
    bubble.appendChild(player);

    if (m.caption) {                         // caption present ⇒ voice note
      const cap = document.createElement('div');
      cap.className = 'caption';
      cap.textContent = m.caption;           // ← textContent, NEVER innerHTML
      bubble.appendChild(cap);
      wireVoiceNote(bubble, player, m, isLive);   // §10, optional
    }
  } else {
    bubble.textContent = m.body;             // ← textContent, NEVER innerHTML
  }
  return bubble;
}
```

### The regex is the security boundary

`MEDIA_PATH` is what stops arbitrary user text from becoming a media `src`. It
enforces three things simultaneously:

1. **Own-origin** — a leading `/media/`, so no `https://attacker.example/…` and
   no `javascript:`.
2. **Server-minted key shape** — 32 hex characters, which no user can type by
   accident and which nothing else in your system produces.
3. **Known extension** — checked against your tag map with `hasOwn`.

Anything failing it goes through `textContent`. **Anchor the regex** (`^…$`).
An unanchored version matches a substring and defeats the whole check.

### Make the render loop individually fault-tolerant

If rendering one message can throw, wrap **each** message, not the loop:

```js
for (const m of messages) {
  try { container.appendChild(renderMessage(m, false)); }
  catch { /* skip this row; the rest of history still renders */ }
}
```

Without this, a single malformed row aborts the entire history render and the
conversation appears permanently empty for every user who loads it. This is a
real failure mode, not a hypothetical (see §12.6).

### Replay

If audio is permanent, native `<audio controls>` gives you replay for free. To
make the whole bubble clickable, two details matter:

```js
bubble.addEventListener('click', (e) => {
  if (e.target === player) return;   // player's own controls are clicks too —
                                     // hijacking them breaks scrub and volume
  e.stopPropagation();               // don't also trigger the row's other
                                     // click behaviours (reply, select, etc.)
  player.currentTime = 0;
  player.play().catch(() => {});     // rejects when autoplay is blocked
});
```

---

## 10. Optional: ephemeral voice notes

A distinct product decision, layered on top. **Skip this section entirely if you
want permanent audio** — nothing else depends on it.

The premise: *speech is a moment; text is the record.* A voice note plays once,
then disappears, leaving the caption behind. Beyond the product argument, it
makes storage costs effectively zero.

### Lifecycle

| Event | Behaviour |
|---|---|
| Arrives while the user is present | Plays **immediately**, unprompted |
| Arrives while the user is away | Sits silent — loading history never triggers a backlog of audio |
| Autoplay blocked by the browser | Falls back to a tappable player |
| Playback finishes | Player is replaced by a download link + countdown |
| Already played (per device) | Skips straight to the download state |
| TTL elapses | Download link becomes a "gone" marker; audio is deleted server-side |
| Always | The caption remains in history permanently |

### Client

```js
const TTL_MS = 15 * 60 * 1000;   // must match the server's value
const PLAYED_KEY = 'voice_played';

function wireVoiceNote(bubble, player, m, isLive) {
  const remaining = m.ts + TTL_MS - Date.now();
  if (remaining <= 0) { player.remove(); bubble.appendChild(goneMarker()); return; }

  player.preload = 'auto';                  // no fetch delay when it plays

  const dissolve = () => {
    if (!player.parentNode) return;         // idempotent — multiple triggers
    player.remove();
    bubble.appendChild(downloadLink(m, m.ts + TTL_MS - Date.now()));
  };

  player.addEventListener('ended', dissolve);

  // Played-once, surviving reloads. Per-device; per-account needs a round trip.
  const played = loadJSON(PLAYED_KEY, []);
  if (played.includes(m.body)) { dissolve(); return; }
  player.addEventListener('play', () => {
    played.push(m.body);
    storeJSON(PLAYED_KEY, played.slice(-200));   // bounded — don't grow forever
  }, { once: true });

  // THE MOMENT: only live arrivals speak on their own.
  if (isLive && !appIsPlayingOtherAudio()) player.play().catch(() => {});

  // Even unplayed, it expires on schedule.
  setTimeout(dissolve, remaining);
}
```

Four details carry the entire behaviour:

1. **`isLive`** distinguishes a socket arrival from a history row. **Without it,
   reconnecting fires every recent voice note simultaneously** — the worst bug
   available in this design, and the easiest to ship.
2. **Check for competing audio** before autoplaying. If your app can already be
   making sound (a call, a video, a screen share), don't talk over it — leave the
   player tappable instead.
3. **`.play().catch(() => {})`** — browsers block audio not traceable to a user
   gesture. The rejection is expected; unhandled it is console noise on every
   message.
4. **Bound the played-set.** It grows forever otherwise. Keep the last N.

### Server: lazy, read-triggered expiry

No cron, no queue, no scheduler. Mark the object at write time and collect it on
the first read after it expires:

```js
// at write:
await mediaStore.put(key, audio, {
  contentType: 'audio/mpeg',
  metadata: { voice: '1' },        // "I am ephemeral"
});

// in the media route, after fetching the object:
if (obj.metadata?.voice === '1' && Date.now() - obj.uploadedAt > TTL_MS) {
  await mediaStore.delete(key);
  await refundStorage(obj.size);
  return res.sendStatus(404);
}
```

If your storage has no metadata facility, substitute a key prefix
(`voice-<hex>.mp3`), a database column, or the file's mtime.

> **The honest trade-off:** an expired object that is *never requested again* is
> never collected. It occupies storage indefinitely.
>
> For small audio this is negligible, and the ledger self-corrects whenever
> anyone loads old history. If your objects are large or rarely re-requested,
> pair lazy expiry with a periodic sweep — but start lazy; it's twenty lines and
> no infrastructure.

### Keep the two TTLs in sync

The value exists twice: the server's is the **rule**, the client's drives the
**countdown display**. If the client's is longer, users see a download link that
404s. Define it in one place if your build allows; otherwise, cross-reference
them in comments.

---

## 11. Testing

You do not need a framework, and you should not need the real provider.

### Fake the provider, assert the contract

```js
const fakeProvider = {
  calls: [],
  async run(model, opts) {
    fakeProvider.calls.push({ model, ...opts });
    return fixedAudioBytes(2048);
  },
};
```

Recording the calls is what lets you assert the **contract with the model**, not
just the HTTP status — this is what catches encoding drift (§3.4):

```js
assert.deepEqual(fakeProvider.calls.at(-1), {
  model: EXPECTED_MODEL,
  text: 'hello there',
  speaker: 'ember',
  encoding: 'mp3',          // ← the assertion that prevents a silent wav bug
});
```

### Use a real counter for the ledger

Mock the database, but let the ledger be an actual mutable map. Otherwise you
can only assert that the cap *was consulted*, never that it *holds* — and the
cap is the part protecting your money.

### The cases that matter

| Case | Expect |
|---|---|
| No authentication | `401` |
| Empty text | `400` |
| Voice not on the allowlist | `400` |
| Text over the per-message cap | `413` |
| Budget already exhausted | `429` |
| Provider throws | `502`, **and the budget is refunded** |
| Provider returns empty | `502`, **and the budget is refunded** |
| Happy path | `200`, path matches the key regex |
| Fetching that path back | `200`, correct `Content-Type`, `nosniff` |
| Fetching a fabricated key | `404`, never `500` |
| Path-traversal attempt in the key | `404` |
| Prototype-pollution extension (`x.constructor`) | `404` |

### Manual verification

1. Send a voice message; confirm the player appears with the caption.
2. Reload; confirm it comes back from history with the caption intact.
3. Sign in as a **second user** and confirm they hear the same audio file — this
   is what distinguishes real TTS from device-local `speechSynthesis`.
4. Send one to a private conversation; confirm it stays private.
5. Delete it; confirm the stored bytes are removed and the ledger decreases.
6. Test on a phone. Autoplay policy, range requests, and inline playback all
   differ from desktop.

> ⚠️ **Hosted providers usually bill in development too.** There is rarely a
> local simulator. Know this before writing a loop.

---

## 12. Security and correctness invariants

Each of these is a boundary, not a preference. Several were bought with real
production bugs.

1. **Authenticate the generation endpoint.** It costs money per call. An
   unauthenticated TTS endpoint is a billing DoS with a friendly API.

2. **Authenticate the media endpoint** if messages are private. An unguessable
   URL is obscurity, not access control — and URLs leak through referrers,
   logs, proxies, and screenshots.

3. **Allowlist voices server-side.** The client picker is convenience. A
   client-supplied voice string flowing into a model call, a URL, or a filename
   is an injection point.

4. **The server mints the storage key.** Random, fixed shape, validated on every
   read. A client-supplied filename is path traversal; a client-supplied
   extension is stored XSS on your own origin — an uploaded `.html` served from
   your domain executes with your users' cookies.

5. **Serve `Content-Type` from your own extension table**, never from the stored
   file or the client's claim. Always add `X-Content-Type-Options: nosniff`.

6. **Use `Object.hasOwn` (or a `Map`) for extension lookups.** A bare
   `TABLE[ext]` walks the prototype chain: `constructor`, `toString`, and
   `__proto__` all return truthy values and defeat the allowlist. The observed
   consequences of getting this wrong were a bypassed upload filter *and* — via
   the same trick in the client's tag map — `createElement(function)` throwing
   inside the history render loop, which permanently blanked the conversation
   for every user. Guard both sides, and make the render loop fault-tolerant
   per-row (§9).

7. **Cap characters per message *and* per period.** Either alone is
   insufficient.

8. **Reserve budget with an atomic conditional update**, never read-then-write.
   The naive version passes every single-threaded test and fails under any real
   concurrency.

9. **Refund on failure**, so a provider outage doesn't consume users' budget.

10. **Render captions with `textContent`, never `innerHTML`.** It is user-authored
    text that round-trips through your database to every participant — the
    canonical stored-XSS path.

11. **Anchor the media-path regex** (`^…$`). Unanchored, it matches substrings
    and grants arbitrary `src` values.

12. **A failed generation must create no message.** Fail locally; never broadcast
    a broken bubble that persists in history.

---

## 13. Failure modes that will bite you

**Encoding/extension drift.** The provider returns WAV, you named the key
`.mp3`, and you serve `audio/mpeg` from your own table. The player silently does
nothing and there is no error anywhere. Assert the encoding parameter in tests.

**`play()` rejects.** Browsers block audio without a user-gesture ancestor. The
returned promise rejects. Always `.catch()`.

**Autoplaying history.** Without a live/backlog distinction, every reconnect
fires the entire recent backlog at once.

**Autoplay over existing audio.** Check whether your app is already producing
sound before speaking.

**Click handlers fighting the player.** `<audio controls>` clicks are UI. A
bubble-level handler that doesn't exclude the player makes scrubbing and volume
unusable.

**Missing range support.** iOS Safari refuses media it cannot seek. Symptom: it
works everywhere except iPhones.

**Prototype pollution in lookup tables.** See §12.6.

**One bad row killing history.** Wrap per-message rendering, not the loop.

**Read-then-write budget checks.** Concurrent requests all read the same total
and all pass.

**Client/server cap divergence.** A `413` users can walk into with no warning.

**TTL divergence** (if using §10). A client TTL longer than the server's shows a
download link that 404s.

**Unbounded played-set.** Local storage grows forever and eventually throws on
write.

**Development billing.** Hosted providers charge for dev traffic.

---

## 14. Scope boundaries

Deliberately excluded from the minimal implementation. Each is real work with a
real cost — the trigger column is when it stops being premature.

| Deferred | Build it when |
|---|---|
| Per-user rate limiting | One user can exhaust the shared budget and does |
| Caching identical `(text, voice)` | Repeated phrases are common — key on a hash, look up before generating |
| Streaming playback | Messages grow long enough that generation latency is felt |
| Waveform / duration display | Requires decoding audio or provider metadata |
| Signed captions | The trust boundary in §7 stops being acceptable |
| Per-account played-once | Users complain a note replayed on another device |
| Scheduled sweep of expired media | Lazy expiry (§10) leaves meaningful storage behind |
| Per-voice audio previews | The picker outgrows names alone (~12+ voices) |
| Multi-language / pronunciation hints | Users need it — most providers expose SSML or a language parameter |
| Server-side transcription of *recorded* voice | You add microphone recording; this system is text-first |

---

## Appendix: minimum viable checklist

```
SERVER
  [ ] synthesize(text, voice) → bytes, isolated behind one function
  [ ] POST /api/say
        [ ] authenticate
        [ ] voice allowlist (server-side)
        [ ] per-message character cap
        [ ] atomic budget reservation + refund on failure
        [ ] server-minted random key, fixed shape
        [ ] explicit encoding, matching extension and content type
        [ ] 503 when the provider isn't configured
  [ ] GET /media/:key
        [ ] authenticate
        [ ] key shape regex + hasOwn extension lookup
        [ ] own content type + nosniff
        [ ] range support
  [ ] caption column: insert, broadcast, history select, history mapping
  [ ] sanitizeCaption — only on media bodies, length-capped
  [ ] delete cascade → storage + ledger refund

CLIENT
  [ ] voice picker, persisted selection
  [ ] arm/disarm, with input maxLength + placeholder following the mode
  [ ] sendVoice: local status line, POST, then send path as body + caption
  [ ] renderer branches on an ANCHORED body regex
  [ ] caption via textContent
  [ ] per-row try/catch in the history loop
  [ ] play().catch()

TESTS
  [ ] fake provider recording its calls
  [ ] real mutable ledger
  [ ] every row of the §11 table
```
