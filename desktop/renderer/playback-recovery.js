/* Shared by the desktop shell and the station webview. repair() closes
 * over nothing so the shell can inject its source into the playback page. */
(function (root) {
  'use strict';

  function repair(target, options) {
    var w = target || (typeof window !== 'undefined' ? window : globalThis);
    if (w.__pinePlaybackRecoveryPending) return w.__pinePlaybackRecoveryPending;
    var doc = w.document, settings = options || {};
    var timeout = Math.min(20000, Math.max(100, Number(settings.timeoutMs) || 5000));
    var result = {ok: true, stoppedPreviews: 0, restartedVideos: 0, walls: 0, sfx: 0, errors: []};
    var previews = 'video.pav-media,#lightboxVid,#lightboxRefVid,.film video,#galleryGrid video,.sfx-tv-parody-shade video,.sfx-tv-delete-stage video';
    var tasks = [];
    function error(step, reason) {
      result.ok = false;
      result.errors.push({step: step, error: String(reason && reason.message || reason)});
    }
    function safely(step, action) {
      try { return action(); } catch (reason) { error(step, reason); }
    }
    function bounded(step, action, done) {
      return new Promise(function (resolve) {
        var settled = false;
        var timer = w.setTimeout(function () {
          if (settled) return;
          settled = true; error(step, step + ': playback has not been verified within ' + timeout / 1000 + ' seconds.'); resolve();
        }, timeout);
        Promise.resolve().then(action).then(function (answer) {
          if (settled) return;
          settled = true; w.clearTimeout(timer);
          if (done) safely(step, function () { done(answer); });
          resolve();
        }, function (reason) {
          if (settled) return;
          settled = true; w.clearTimeout(timer); error(step, reason); resolve();
        });
      });
    }
    function stop(video) {
      safely('disable preview', function () { video.autoplay = false; video.loop = false; video.muted = true; });
      safely('pause preview', function () { video.pause(); });
      safely('release preview source', function () {
        video.removeAttribute('src');
        if (video.querySelectorAll) video.querySelectorAll('source').forEach(function (source) { source.removeAttribute('src'); });
      });
      safely('release preview decoder', function () { video.load(); });
    }
    function repairSfx(clip) {
      var operation = w.PineSfxTv.repair(clip);
      var pip = doc.body && doc.body.classList && doc.body.classList.contains('pine-pip');
      if (!pip) return operation;
      // The existing SFX proof requires its DOM host to have height. PiP
      // hides that host and displays its decoded video in canvas tiles.
      // Verify frames on that exact player's source instead of waiting
      // for a host that intentionally remains hidden.
      return new Promise(function (resolve, reject) {
        var settled = false, timer, before = new Map();
        var rounds = Math.max(1, Math.floor((timeout - 100) / 200));
        function finish(answer, reason) {
          if (settled) return;
          settled = true; w.clearTimeout(timer);
          if (reason) reject(reason); else resolve(answer);
        }
        Promise.resolve(operation).then(function (answer) { finish(answer); }, function (reason) { finish(null, reason); });
        function sample() {
          if (settled) return;
          var current = w.PineSfxTv.playing && w.PineSfxTv.playing();
          if (current && (current === clip || current.url === clip.url)) {
            var videos = Array.from(doc.querySelectorAll('#sfxTv .sfx-tv-tube video'));
            for (var i = 0; i < videos.length; i += 1) {
              var media = videos[i], data = media.dataset || {};
              if (data.pineWarm === '1' || media.paused || media.error || media.readyState < 2 || !(media.videoWidth > 0)) continue;
              var source = String(media.currentSrc || media.src || ''), time = Number(media.currentTime);
              var previous = before.get(media), frames = null;
              try { if (media.getVideoPlaybackQuality) frames = Number(media.getVideoPlaybackQuality().totalVideoFrames); } catch (_) { /* older decoder */ }
              if (source && previous && previous.source === source && time - previous.time >= .08
                  && (frames === null || previous.frames === null || frames > previous.frames)) {
                finish({ok: true, detail: 'SFX video frames advancing into Pine PiP.'}); return;
              }
              before.set(media, {source: source, time: time, frames: frames});
            }
          }
          rounds -= 1;
          if (rounds <= 0) { finish({ok: false, detail: 'SFX video has not produced advancing frames in Pine PiP; waiting for playback.'}); return; }
          timer = w.setTimeout(sample, 200);
        }
        sample();
      });
    }
    if (!doc || !doc.querySelectorAll) {
      error('document', 'The playback document is unavailable.');
      return Promise.resolve(result);
    }
    // Snapshot first: close hooks may detach their media before the scan.
    var previewNodes = Array.from(doc.querySelectorAll(previews));
    safely('close H3 viewer', function () {
      if (w.PineAdViewer && typeof w.PineAdViewer.recover === 'function') w.PineAdViewer.recover();
      else if (w.PineAdViewer && typeof w.PineAdViewer.close === 'function') w.PineAdViewer.close();
    });
    safely('close H3 lightbox', function () { if (typeof w.closeLightbox === 'function') w.closeLightbox(); });
    safely('release H3 audio hold', function () { if (typeof w.lightboxDuckReset === 'function') w.lightboxDuckReset(); });
    safely('release gallery audio hold', function () {
      if (w.PineDuck && typeof w.PineDuck.release === 'function') w.PineDuck.release('pine-box-gallery');
    });
    previewNodes.forEach(function (video) { stop(video); result.stoppedPreviews += 1; });

    // Catch late decoder events from hidden H3 previews after repair. A
    // visible popup remains playable after the user deliberately opens it.
    if (!w.__pinePlaybackRecoveryGuard && doc.addEventListener) {
      w.__pinePlaybackRecoveryGuard = function (event) {
        var video = event.target;
        if (!video || !video.matches || !video.matches(previews)) return;
        var pip = doc.body && doc.body.classList && doc.body.classList.contains('pine-pip') && !w.PINE_NATIVE_TOOLS;
        var hidden = video.closest && video.closest('[hidden]');
        if (!hidden && w.getComputedStyle) {
          for (var parent = video.parentElement; parent && parent !== doc.body; parent = parent.parentElement) {
            var style = w.getComputedStyle(parent);
            if (style.display === 'none' || style.visibility === 'hidden') { hidden = true; break; }
          }
        }
        if (pip || hidden || video.isConnected === false) stop(video);
      };
      doc.addEventListener('play', w.__pinePlaybackRecoveryGuard, true);
      doc.addEventListener('playing', w.__pinePlaybackRecoveryGuard, true);
    }
    if (w.PineVideoWall && typeof w.PineVideoWall.recoverAll === 'function') {
      tasks.push(bounded('restart video wall', function () { return w.PineVideoWall.recoverAll(); }, function (states) {
        result.walls = Array.isArray(states) ? states.length : 0;
        (states || []).forEach(function (state) { if (state && (state.error || state.note)) error('restart video wall', state.error || state.note); });
      }));
    }
    var sfxManaged = false;
    if (w.PineSfxTv) {
      safely('release video playback hold', function () {
        if (typeof w.PineSfxTv.releaseHold === 'function') w.PineSfxTv.releaseHold();
      });
      var nativeActive = safely('inspect endless video', function () {
        return typeof w.PineSfxTv.nativeWallActive === 'function' && w.PineSfxTv.nativeWallActive();
      });
      var clip = safely('inspect SFX playback', function () {
        return typeof w.PineSfxTv.playing === 'function' ? w.PineSfxTv.playing() : null;
      });
      if (nativeActive && typeof w.PineSfxTv.repairEndless === 'function') {
        sfxManaged = true;
        tasks.push(bounded('restart endless video', function () { return w.PineSfxTv.repairEndless(); }, function () { result.sfx += 1; }));
      } else if (clip && clip.url && typeof w.PineSfxTv.repair === 'function') {
        sfxManaged = true;
        tasks.push(bounded('restart SFX video', function () { return repairSfx(clip); }, function (state) {
          if (state && state.ok === false) error('restart SFX video', state.detail || 'The SFX video did not start.');
          else result.sfx += 1;
        }));
      }
    }
    Array.from(doc.querySelectorAll('video')).forEach(function (video) {
      if (previewNodes.indexOf(video) >= 0 || (video.matches && video.matches(previews))) return;
      // These controllers revoke and replace their own media. Reloading
      // the old element concurrently would race that replacement.
      if (video.id === 'pvWall' && w.PineVideoWall && typeof w.PineVideoWall.recoverAll === 'function') return;
      if (sfxManaged && video.closest && video.closest('#sfxTv')) return;
      // Camera streams have their own recovery path. Preserve deliberately
      // paused players and the existing mixer/solo mute decisions.
      if (video.srcObject || video.isConnected === false || (video.paused && !video.autoplay)) return;
      if (!(video.currentSrc || video.src || (video.getAttribute && video.getAttribute('src')))) return;
      var position = Number(video.currentTime) || 0;
      var ended = video.ended;
      safely('reset video decoder', function () { video.pause(); video.load(); });
      safely('restore video position', function () { video.currentTime = ended ? 0 : position; });
      tasks.push(bounded('resume video', function () { return video.play(); }, function () { result.restartedVideos += 1; }));
    });
    var pending = Promise.all(tasks).then(function () { return result; }).finally(function () {
      if (w.__pinePlaybackRecoveryPending === pending) w.__pinePlaybackRecoveryPending = null;
    });
    w.__pinePlaybackRecoveryPending = pending;
    return pending;
  }

  var api = {repair: repair};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.PinePlaybackRecovery = api;
}(typeof window !== 'undefined' ? window : globalThis));
