"""[changelog-cache] Install the Git hooks that keep the changelog cache current.

The Pine Box changelog popup is served from ``data/changelog_cache.json``
(see changelog.py).  The station refreshes that file itself when it sees
HEAD move (it polls every 20 s, and needs no git binary), but commits are
made from the host, where git exists: these hooks run the same refresh right
after a commit, merge, rebase/amend or checkout, so the popup shows a new
commit within seconds and with git's own numbers.

Git does not track hooks: ``.git/hooks`` is per clone, so this must be run
once on each clone that commits (the host's ~/pinevoice-stack/spark-agent;
a Windows session committing over SMB uses the same .git and so the same
hooks).  Existing hooks are kept: the block is inserted after their shebang
between markers, and ``uninstall`` removes only the block.

    python3 tools/changelog_hooks.py install   [--repo DIR]
    python3 tools/changelog_hooks.py check     [--repo DIR]   exit 0 all present, 1 not
    python3 tools/changelog_hooks.py uninstall [--repo DIR]

The hook never delays or fails a commit: it backgrounds the refresh with all
output discarded and ignores every error.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

HOOKS = ("post-commit", "post-merge", "post-rewrite", "post-checkout")
BEGIN = "# >>> [changelog-cache] Pine Box changelog (tools/changelog_hooks.py) >>>"
END = "# <<< [changelog-cache] <<<"
BLOCK = BEGIN + r"""
# Refresh data/changelog_cache.json in the background once Git is done, so
# the changelog popup shows this commit; silent, and never slows Git down.
(
  top=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
  [ -f "$top/changelog.py" ] || exit 0
  for py in python3 python; do
    if command -v "$py" >/dev/null 2>&1; then
      cd "$top" && exec "$py" changelog.py refresh --quiet --nice 10
    fi
  done
) </dev/null >/dev/null 2>&1 &
""" + END + "\n"


def hooks_dir(repo: Path) -> Path:
    if shutil.which("git"):
        try:
            out = subprocess.run(["git", "-C", str(repo), "rev-parse", "--git-path", "hooks"],
                                 check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True).stdout.strip()
            path = Path(out)
            return path if path.is_absolute() else repo / path
        except (OSError, subprocess.SubprocessError):
            pass
    return repo / ".git" / "hooks"


def _without_block(text: str) -> str:
    start = text.find(BEGIN)
    if start < 0:
        return text
    end = text.find(END, start)
    if end < 0:
        return text
    end += len(END)
    if text[end:end + 1] == "\n":
        end += 1
    return text[:start] + text[end:]


def install(repo: Path) -> list[str]:
    folder = hooks_dir(repo)
    folder.mkdir(parents=True, exist_ok=True)
    done = []
    for name in HOOKS:
        path = folder / name
        try:
            text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        except FileNotFoundError:
            text = ""
        text = _without_block(text)
        if not text.strip():
            text = "#!/bin/sh\n" + BLOCK
        elif text.startswith("#!"):
            first, _, rest = text.partition("\n")
            text = first + "\n" + BLOCK + rest
        else:
            text = "#!/bin/sh\n" + BLOCK + text
        tmp = path.with_name(path.name + ".changelog-tmp")
        tmp.write_bytes(text.encode("utf-8"))
        tmp.chmod(tmp.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        os.replace(tmp, path)
        done.append(str(path))
    return done


def check(repo: Path) -> list[str]:
    missing = []
    for name in HOOKS:
        path = hooks_dir(repo) / name
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            missing.append(name)
            continue
        if BEGIN not in text or END not in text:
            missing.append(name)
    return missing


def uninstall(repo: Path) -> list[str]:
    removed = []
    for name in HOOKS:
        path = hooks_dir(repo) / name
        try:
            text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        except OSError:
            continue
        if BEGIN not in text:
            continue
        rest = _without_block(text)
        if rest.strip() in ("", "#!/bin/sh"):
            path.unlink()
        else:
            path.write_bytes(rest.encode("utf-8"))
        removed.append(name)
    return removed


def main(argv: list[str]) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("install", "check", "uninstall"))
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    if args.action == "install":
        for path in install(repo):
            print("installed", path)
        return 0
    if args.action == "check":
        missing = check(repo)
        print("changelog hooks: %s" % ("all present" if not missing else "missing " + ", ".join(missing)))
        return 1 if missing else 0
    for name in uninstall(repo):
        print("removed from", name)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
