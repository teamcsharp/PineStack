"""[qrelease] The file manager (the disk icon in the base bar) shows the SFX
quarantine and releases a clip or a folder.

  python3 tools/qrelease_filemgr_patch.py --check desktop/renderer/filemgr.js
  python3 tools/qrelease_filemgr_patch.py --apply desktop/renderer/filemgr.js
  python3 tools/qrelease_filemgr_patch.py --apply app/src/main/assets/pine-views/filemgr.js   (the kiosk mirror)

exit 0 ready, 2 applied, 1 anchors missing (named). Then `node --check` both.
The rows reuse the restore section's classes, so filemgr.css is untouched.
A release is a hold (like restore); the station re-checks the clip before it
may air again and a failed check stays in the list with its reason.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from msgid_lib import Edit, run  # noqa: E402

MARKER = "[qrelease]"

SECTION = r"""
    /* [qrelease] the SFX quarantine: clips no player could decode, and folders
       gone from the share. A release re-checks the file on the station (it is
       on the share and ffmpeg decodes it, one at a time) before it may air
       again; a failed check keeps it here with the reason. */
    var qs = make('div', 'fm-restore fm-quarantine');
    var qh = make('button', 'fm-restore-head');
    qh.type = 'button';
    qh.title = 'Clips kept off the air because they could not be decoded';
    qh.appendChild(ico('c:warning--alt', ''));
    qh.appendChild(make('span', '', 'Quarantined clips'));
    ui.qCount = make('span', 'fm-restore-n', '');
    qh.appendChild(ui.qCount);
    qh.addEventListener('click', function () {
      ui.qOpen = !ui.qOpen;
      paintQuarantine();
      if (ui.qOpen) loadQuarantine();
    });
    qs.appendChild(qh);
    ui.qList = make('div', 'fm-restore-list');
    ui.qList.hidden = true;
    qs.appendChild(ui.qList);
    foot.appendChild(qs);
"""

FUNCS = r"""  /* ================================================== [qrelease] quarantine */

  function loadQuarantine() {
    return get('/api/sfx/quarantine').then(function (q) {
      ui.quarantine = q || {};
      paintQuarantine();
      var job = ui.quarantine.job || {};
      if (job.running && ui.visible) root.setTimeout(loadQuarantine, 3000);
    }, function (e) {
      ui.quarantine = {error: e.message};
      paintQuarantine();
    });
  }
  function releaseHold(word, body, row) {
    var b = make('button', 'fm-exec fm-restore-btn');
    b.type = 'button';
    b.title = 'Check the file again and let it air if it passes';
    b.appendChild(make('span', 'fm-exec-fill'));
    b.appendChild(make('span', 'fm-exec-word', word));
    wireHold(b, function () {
      b.disabled = true;
      post('/api/sfx/quarantine/release', body).then(function (got) {
        var passed = got && got.ok;
        row.appendChild(make('div', passed ? 'fm-dim' : 'fm-sum-refuse',
          (got && got.say) || (passed ? 'Released' : 'It stays quarantined')));
        root.setTimeout(loadQuarantine, 1500);
      }, function (e) {
        row.appendChild(make('div', 'fm-sum-refuse', 'Refused: ' + e.message));
        b.disabled = false;
      });
    });
    return b;
  }
  function paintQuarantine() {
    if (!ui.qList) return;
    var q = ui.quarantine || {};
    var clips = q.clips || [];
    var folders = (q.folders || []).filter(function (f) { return f.gone || f.clips > 1; });
    ui.qCount.textContent = q.error ? '?' : (ui.quarantine ? (clips.length ? String(clips.length) : 'none') : '');
    ui.qList.hidden = !ui.qOpen;
    if (!ui.qOpen) return;
    ui.qList.textContent = '';
    if (q.error) {
      ui.qList.appendChild(make('div', 'fm-sum-refuse', 'Could not read the quarantine: ' + q.error));
      return;
    }
    if (q.job && (q.job.running || q.job.say)) {
      ui.qList.appendChild(make('div', 'fm-dim', q.job.running
        ? 'Checking ' + q.job.folder + ': ' + (q.job.done || 0) + ' of ' + (q.job.total || 0)
        : q.job.say));
    }
    if (!clips.length && !folders.length) {
      ui.qList.appendChild(make('div', 'fm-dim', 'Nothing is quarantined.'));
      return;
    }
    folders.forEach(function (f) {
      var row = make('div', 'fm-snap');
      var words = make('div', 'fm-snap-words');
      words.appendChild(make('b', '', f.folder));
      words.appendChild(make('span', 'fm-dim', count(f.clips, 'clip') +
        (f.back ? ' - the folder is back on the share' : (f.gone ? ' - the folder is gone from the share' : ''))));
      row.appendChild(words);
      row.appendChild(releaseHold('Hold to release folder', {folder: f.folder}, row));
      ui.qList.appendChild(row);
    });
    clips.slice(0, 80).forEach(function (c) {
      var row = make('div', 'fm-snap');
      var words = make('div', 'fm-snap-words');
      words.appendChild(make('b', '', c.name || c.sid));
      words.appendChild(make('span', 'fm-dim', (c.why || 'quarantined') + (c.at ? ' - ' + when(c.at) : '')));
      if (c.last_check) words.appendChild(make('span', 'fm-sum-refuse', 'Last check: ' + c.last_check));
      row.appendChild(words);
      row.appendChild(releaseHold('Hold to release', {sid: c.sid}, row));
      ui.qList.appendChild(row);
    });
    if (clips.length > 80) {
      ui.qList.appendChild(make('div', 'fm-dim', '... and ' + (clips.length - 80) + ' more - release their folder'));
    }
  }

"""

EDITS = [
    Edit("section", "    foot.appendChild(rs);\n", SECTION),
    Edit("open", "    loadGroups(false);\n    loadJobs();\n", "    loadQuarantine();     /* [qrelease] */\n"),
    Edit("funcs", "  /* ================================================== boot */\n", FUNCS, where="before"),
]

if __name__ == "__main__":
    raise SystemExit(run(EDITS, marker=MARKER))
