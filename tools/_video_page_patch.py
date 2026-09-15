"""#1263: the DJ's video, on the tune page, landing on the sound.

The set sits in the SAME frame as the ComfyUI gallery and takes it over
while a picture is playing, which is what was asked for - the artwork is
what fills that frame between videos, not a thing to be shoved aside.

Two details that are easy to get wrong and both matter:

  * THE VIDEO IS MUTED, ALWAYS. Its audio is already in the broadcast -
    the mixer now resolves /sfx/ and mixes the sting like any other clip.
    An unmuted element here is the same fault #1008 chased round the
    house for a week: one show, heard twice, a few hundred ms apart.

  * THE PICTURE WAITS FOR THE SOUND. A stream listener is deliberately
    behind live, by roughly the burst they were handed. The page knows
    that number exactly - `buffered.end - currentTime` is audio received
    but not yet played, which IS the lag - so the set opens that much
    after the station's on-air instant. On the synchronised road the lag
    is zero and it opens immediately.
"""
import pathlib

p = pathlib.Path("app.py")
src = p.read_text()
orig = src


def sub(old, new, why):
    global src
    assert src.count(old) == 1, f"anchor {why}: {src.count(old)}"
    src = src.replace(old, new, 1)


# --- the set, over the gallery -------------------------------------------
sub(
    '''  .gallery-stage img { width:100%; height:100%; object-fit:contain; display:block; }''',
    '''  .gallery-stage img { width:100%; height:100%; object-fit:contain; display:block; }
  /* #1263: the set. Same frame as the artwork, on top of it while a
     picture is playing. */
  .gallery-stage video { width:100%; height:100%; object-fit:contain;
    display:none; background:#000; }
  .gallery-stage.tv video { display:block; }
  .gallery-stage.tv img { display:none; }''',
    "stage css")

sub(
    '''  <div class="gallery-stage" id="galleryStage">
    <img id="galleryImage" alt="Pine Box gallery artwork">
    <div class="gallery-caption" id="galleryCaption"></div>
  </div>''',
    '''  <div class="gallery-stage" id="galleryStage">
    <img id="galleryImage" alt="Pine Box gallery artwork">
    <!-- #1263: MUTED, and not a mistake. The sound of this clip is
         already in the broadcast the listener is hearing; an element
         here with its own audio is the show playing twice. -->
    <video id="galleryVideo" muted playsinline
           preload="auto" aria-label="What the DJ is playing"></video>
    <div class="gallery-caption" id="galleryCaption"></div>
  </div>''',
    "stage markup")

# --- the set's logic ------------------------------------------------------
sub(
    '''function patter(state) {''',
    '''/* #1263: THE SET.
 *
 * Polls a tiny audio-free feed - deliberately not /api/dj/voice, which
 * announces clips the page then downloads, and which the stream road does
 * not touch for exactly that reason. A couple of hundred bytes every few
 * seconds is affordable in a car; megabytes of audio are not.
 */
let tvNow = null;            /* the clip currently on the set */
let tvSkew = 0;              /* server clock - this clock, in ms */
let tvSeen = 0;

function tvLagSeconds() {
  /* How far behind live this listener is.
   *
   * On the stream road it is not a guess: `buffered.end - currentTime` is
   * audio that has ARRIVED and not yet been played, which is precisely
   * the distance between what the station is doing and what this car is
   * hearing. On the synchronised road there is no such gap. */
  if (!streamMode || !radio) return 0;
  try {
    const b = radio.buffered;
    if (!b || !b.length) return 0;
    const ahead = b.end(b.length - 1) - Number(radio.currentTime || 0);
    return (isFinite(ahead) && ahead > 0) ? Math.min(ahead, 120) : 0;
  } catch (e) { return 0; }
}

async function tvPoll() {
  if (!playing) { tvHide(); return; }
  let data;
  try {
    data = await api("/api/dj/video");
  } catch (e) { return; }
  tvSkew = Number(data.server_ms || Date.now()) - Date.now();
  const lagMs = tvLagSeconds() * 1000;
  const now = Date.now();
  let best = null;
  (data.videos || []).forEach((v) => {
    if (!v.url || !v.seconds) return;
    /* The station's on-air instant, moved into THIS page's clock, then
     * held back by this listener's own lag so the picture lands on the
     * sound rather than half a minute ahead of it. */
    const showAt = Number(v.broadcast_ms) - tvSkew + lagMs;
    const into = (now - showAt) / 1000;
    if (into >= -0.5 && into < Number(v.seconds) + 0.5) {
      if (!best || Number(v.broadcast_ms) > Number(best.v.broadcast_ms)) {
        best = {v: v, into: into};
      }
    }
  });
  if (!best) { tvHide(); return; }
  tvShow(best.v, best.into);
}

function tvShow(v, into) {
  const stage = document.getElementById("galleryStage");
  const el = document.getElementById("galleryVideo");
  const cap = document.getElementById("galleryCaption");
  if (!stage || !el) return;
  if (tvNow !== v.url) {
    tvNow = v.url;
    el.muted = true;                 /* belt and braces - see the markup */
    el.src = clipUrl ? v.url : v.url;
    el.currentTime = Math.max(0, into);
    el.play().catch(() => {});
    if (cap) cap.textContent = v.name || "";
    stage.classList.add("show");
    stage.classList.add("tv");
  } else {
    /* Already on: only correct the playhead if it has genuinely drifted,
     * because a seek restarts the decoder and that is visible. */
    try {
      if (Math.abs(Number(el.currentTime || 0) - into) > 1.5) {
        el.currentTime = Math.max(0, into);
      }
      if (el.paused) el.play().catch(() => {});
    } catch (e) {}
  }
}

function tvHide() {
  const stage = document.getElementById("galleryStage");
  const el = document.getElementById("galleryVideo");
  if (!stage || !el || tvNow === null) return;
  tvNow = null;
  try { el.pause(); el.removeAttribute("src"); el.load(); } catch (e) {}
  stage.classList.remove("tv");
  /* The artwork gets its frame back; renderGallery decides whether the
   * stage stays up at all. */
}

function patter(state) {''',
    "tv logic")

# --- the gallery must not fight the set ----------------------------------
sub(
    '''  if (!names.length) { stage.classList.remove("show"); return; }
  stage.classList.add("show");''',
    '''  /* #1263: while the set is on, the frame belongs to it - but the
   * artwork keeps rotating underneath so it is already right when the
   * picture ends. */
  if (!names.length) {
    if (tvNow === null) stage.classList.remove("show");
    return;
  }
  stage.classList.add("show");''',
    "gallery yields")

# --- boot -----------------------------------------------------------------
sub(
    '''initLevels();
initMode();                     // #1253: which road this page takes''',
    '''initLevels();
initMode();                     // #1253: which road this page takes
/* #1263: the set checks often enough to catch a short sting, and cheaply
 * enough that a car does not notice - a couple of hundred bytes. */
setInterval(() => { try { tvPoll(); } catch (e) {} }, 2500);''',
    "tv boot")

assert src != orig
p.write_text(src)
print("tune page: the set is in")
