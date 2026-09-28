"""[changelog-cache] The changelog always answers, with or without a git binary.

Operator, 2026-09-28, over a popup that read "Pine Box changelog - Changelog
unavailable: Git history is unavailable: [Errno 2] No such file or
directory: 'git'": "the change log must always work", and then "i want the
log caching so that never happens. It should be [not] directly dependant on
such a thing."

The road: GET /api/changelog -> ChangeLog.page() ran ``git rev-parse HEAD``
(and ``git log --all --numstat`` on a cold cache) on every open. The
spark-agent container bind-mounts the repo at /app, .git included, but has
no git binary, so the very first call raised RuntimeError and the endpoint
answered 503 - even with a 3.4 MB cache of the history sitting on disk.

So (the module files ship beside this tool: changelog.py, git_log_reader.py):
  - git_log_reader.py reads refs, loose objects and packs (OFS/REF deltas)
    and replays ``git log`` / ``--numstat`` in pure Python: identical to git
    on all 839 commits of this repository (walk, messages, 4,224 numstat rows).
  - changelog.py serves the popup from data/changelog_cache.json only; a
    background thread refreshes it at startup and when HEAD moves (git when
    present, the reader otherwise, in a child process), and a failed refresh
    keeps the last good history with its "as of" time.
  - tools/changelog_hooks.py installs host commit hooks that run the same
    refresh after every commit (hooks are not tracked: install once).

This tool edits the two callers:
  app.py          endpoint-*  /api/changelog never answers 503: page() reads
                              the cache; any fault serves what is in memory.
                              startup-*   the refresher starts with the station.
  changelog.js    the panel shows "N committed changes - as of <time>", keeps
                  the last history it received when the station does not
                  answer (and asks again), and says "files still being
                  counted" for a commit a long first build has not reached.
                  Apply to desktop/renderer/changelog.js; the tablet copy
                  app/src/main/assets/pine-views/changelog.js takes the same
                  edits (its CRLF line endings are kept).

Contract: ``--check <path>`` exits 0 ready, 2 already applied, 1 anchors
missing; ``--apply <path>`` is idempotent and atomic, LF (a file that was
CRLF throughout stays CRLF).
"""
import os
import sys
import tempfile
from pathlib import Path

APP_EDITS = [
    ("endpoint-cache-only",
     '''    """The committed station history plus task facts that were captured."""
    require_read_auth(authorization)
    try:
        # A fresh process can need a long Git walk to rebuild its durable
        # changelog cache. Serve that snapshot promptly instead of allowing
        # the panel transport to time out while the refresh completes.
        return await asyncio.wait_for(
            asyncio.to_thread(_CHANGELOG.page, limit, before), timeout=1.5)
    except TimeoutError:
        try:
            cached = await asyncio.to_thread(_CHANGELOG.cached_page, limit, before)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if cached is not None:
            return cached
        return {"entries": [], "total": 0, "head": "", "has_more": False,
                "next_before": "", "retroactive": True,
                "timezone": "America/Chicago", "stale": True, "warming": True}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/changelog/task")
''',
     '''    """The committed station history plus task facts that were captured.

    [changelog-cache] Served from data/changelog_cache.json only. Git - or
    the pure-Python reader, since this container has no git binary - is
    read by the background refresher and the host's commit hooks, never on
    this path. A cache behind HEAD is served with its "as of" time; this
    endpoint does not answer 503.
    """
    require_read_auth(authorization)
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_CHANGELOG.page, limit, before), timeout=1.5)
    except Exception:  # noqa: BLE001 - the changelog always answers
        return _CHANGELOG.memory_page(limit, before)


@app.on_event("startup")
async def _startup_changelog_cache() -> None:
    """[changelog-cache] Bring the changelog cache up to HEAD in the background
    (a daemon thread; the refresh itself runs in a child process)."""
    _CHANGELOG.start()


@app.post("/api/changelog/task")
''', 1),
]

JS_EDITS = [
    ("js-last-good",
     '''  var refreshTimer = 0;

  function make(tag, cls, text) {
''',
     '''  var refreshTimer = 0;
  var lastGood = null;  // [changelog-cache] the last history this panel received

  function make(tag, cls, text) {
''', 1),
    ("js-files-pending",
     '''    heading.appendChild(make('span', '', entry.file_count + ' file' + (Number(entry.file_count) === 1 ? '' : 's')
      + ' / ' + value(entry.short_commit)));
''',
     '''    heading.appendChild(make('span', '', (entry.files_pending ? 'files still being counted'
      : entry.file_count + ' file' + (Number(entry.file_count) === 1 ? '' : 's'))
      + ' / ' + value(entry.short_commit)));
''', 1),
    ("js-as-of",
     '''  function render() {
    if (!panel) return;
    var body = panel.querySelector('.cl-body');
    var count = panel.querySelector('.cl-count');
    body.replaceChildren();
    if (count) count.textContent = pageState.total ? pageState.total + ' committed changes' : '';
    if (pageState.stale) body.appendChild(make('p', 'cl-refreshing', pageState.entries.length
      ? 'Showing the saved station history while Git refreshes.'
      : 'Building the station history from Git...'));
    if (!pageState.entries.length && !loading && !pageState.stale) {
''',
     '''  // [changelog-cache] The history is a saved cache, so the header always
  // says how current it is: "839 committed changes \\u00b7 as of <time>".
  function countLine(state) {
    var parts = [];
    if (state && state.total) parts.push(state.total + ' committed changes');
    if (state && state.as_of_label) parts.push('as of ' + state.as_of_label);
    return parts.join(' \\u00b7 ');
  }

  function render() {
    if (!panel) return;
    var body = panel.querySelector('.cl-body');
    var count = panel.querySelector('.cl-count');
    body.replaceChildren();
    if (count) {
      count.textContent = countLine(pageState);
      count.title = pageState.refresh_error ? 'Last refresh: ' + pageState.refresh_error : '';
    }
    if (pageState.stale) body.appendChild(make('p', 'cl-refreshing', pageState.entries.length
      ? 'Showing the saved station history while it refreshes.'
      : 'Building the station history...'));
    if (pageState.offline) {
      var away = make('p', 'cl-refreshing', pageState.entries.length
        ? 'Showing the last history this panel received; the station has not answered yet.'
        : 'The history will appear when the station answers.');
      away.title = pageState.offline_reason || '';
      body.appendChild(away);
    }
    if (!pageState.entries.length && !loading && !pageState.stale && !pageState.offline) {
''', 1),
    ("js-load-keeps-history",
     '''      pageState.stale = !!(result && result.stale);
      pageState.warming = !!(result && result.warming);
      cursor = String(result && result.next_before || '');
      loading = false;
      render();
''',
     '''      pageState.stale = !!(result && result.stale);
      pageState.warming = !!(result && result.warming);
      pageState.as_of_label = String(result && result.as_of_label || '');
      pageState.refresh_error = String(result && result.refresh_error || '');
      pageState.offline = false;
      cursor = String(result && result.next_before || '');
      loading = false;
      lastGood = Object.assign({}, pageState, {entries: pageState.entries.slice()});
      render();
''', 1),
    ("js-error-is-not-empty",
     '''    }, function (error) {
      loading = false;
      pageState.has_more = false;
      if (panel) {
        var body = panel.querySelector('.cl-body');
        body.replaceChildren(make('p', 'cl-error', 'Changelog unavailable: ' + String(error && error.message || error)));
      }
      return null;
    });
''',
     '''    }, function (error) {
      // [changelog-cache] A missed answer is not an empty history: keep what
      // this panel last received on screen and ask again shortly.
      loading = false;
      if (!pageState.entries.length && lastGood) {
        pageState = Object.assign({}, lastGood, {entries: lastGood.entries.slice()});
      }
      pageState.stale = false;
      pageState.offline = true;
      pageState.offline_reason = String(error && error.message || error);
      render();
      if (!refreshTimer) {
        refreshTimer = root.setTimeout(function () {
          refreshTimer = 0;
          if (panel && !panel.hidden) load('');
        }, 5000);
      }
      return null;
    });
''', 1),
    ("js-open-shows-last-good",
     '''    pageState = {entries: [], total: 0, has_more: false, stale: false, warming: false};
''',
     '''    pageState = lastGood
      ? Object.assign({}, lastGood, {entries: lastGood.entries.slice(), stale: true})
      : {entries: [], total: 0, has_more: false, stale: false, warming: false};
''', 1),
    ("js-export",
     '''  root.PineChangeLog = {open: open, close: close, isMajor: isMajor, elapsed: elapsed};
''',
     '''  root.PineChangeLog = {open: open, close: close, isMajor: isMajor, elapsed: elapsed,
    countLine: countLine};
''', 1),
]

EDITS = APP_EDITS  # the integrate.py contract reads EDITS for app.py


def plan(text):
    if "root.PineChangeLog = {open" in text or "var lastGood = null;  // [changelog-cache]" in text:
        return list(JS_EDITS)
    return list(APP_EDITS)


def state_of(text, old, new, count):
    n_new = text.count(new)
    n_old = text.count(old)
    if n_new >= 1 and n_old == new.count(old) * n_new:
        return "applied"
    if n_new == 0 and n_old == count:
        return "ready"
    return "anchor found %d times, wanted %d; replacement found %d times" % (n_old, count, n_new)


def check(text):
    applied, missing = 0, []
    for name, old, new, count in plan(text):
        state = state_of(text, old, new, count)
        if state == "applied":
            applied += 1
        elif state != "ready":
            missing.append("%s (%s)" % (name, state))
    return applied, missing


def _read(path):
    raw = Path(path).read_bytes()
    crlf = raw.count(b"\r\n") > 0 and raw.count(b"\r\n") == raw.count(b"\n")
    return raw.decode("utf-8").replace("\r\n", "\n"), crlf


def apply(path):
    path = Path(path)
    text, crlf = _read(path)
    applied, missing = check(text)
    edits = plan(text)
    if applied == len(edits):
        return 2
    if missing:
        for m in missing:
            print("missing:", m)
        return 1
    for name, old, new, count in edits:
        if state_of(text, old, new, count) == "applied":
            continue
        assert text.count(old) == count, "%s: anchor found %d times" % (name, text.count(old))
        text = text.replace(old, new)
    assert "\r" not in text
    if crlf:
        text = text.replace("\n", "\r\n")
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    with os.fdopen(fd, "wb") as fh:
        fh.write(text.encode("utf-8"))
    os.replace(tmp, path)
    return 0


def main(argv):
    do_apply = "--apply" in argv
    target = next((a for a in argv if not a.startswith("--")), "app.py")
    if do_apply:
        code = apply(target)
        print({0: "APPLIED", 1: "ANCHORS MISSING - nothing written", 2: "already applied"}[code])
        return code
    text, _ = _read(target)
    applied, missing = check(text)
    total = len(plan(text))
    if missing:
        for m in missing:
            print("missing:", m)
        print("%d of %d applied" % (applied, total))
        return 1
    if applied == total:
        print("already applied (%d edits)" % total)
        return 2
    print("ready: %d edits, %d already in" % (total, applied))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
