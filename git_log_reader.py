"""Read a Git repository's history without the ``git`` binary.

The station runs in a container that has the repository bind-mounted at
/app but ships no ``git`` executable, so the changelog cannot ask ``git
log``.  This module reads the object store directly, standard library only:

* refs: ``HEAD`` -> symbolic ref -> loose ref file, ``packed-refs`` fallback,
  linked worktrees (``.git`` file + ``commondir``), detached heads.
* objects: loose (``objects/xx/...``, zlib) and packs (``*.idx`` v1/v2 +
  ``*.pack``) with OFS_DELTA and REF_DELTA chains resolved.
* history: :meth:`GitRepo.log` walks from HEAD in ``git log``'s default order
  (newest committer date first, ties in discovery order, every parent) and
  returns what ``--format=%H %P %ct %an %s %b`` prints.
* changes: :meth:`GitRepo.numstat` is ``git log --no-renames --numstat`` for
  one commit (nothing for a merge, everything added for a root).  Line
  counts replay git's own xdiff (Myers with git's discards and cost
  heuristics), so they are the numbers git prints; only a diff too costly
  for pure Python (none in the station's history) falls back to a minimal
  line diff.

Run ``python3 git_log_reader.py [repo] [-n 10] [--numstat]`` to print the
last commits the same way ``git log`` would, for comparison.
"""
from __future__ import annotations

import heapq
import os
import re
import struct
import sys
import time
import zlib
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any, Iterator

__all__ = ["GitReadError", "GitRepo", "line_counts", "quote_path", "split_message"]

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEXPREFIX = re.compile(r"^[0-9a-f]{4,40}$")
_TYPES = {1: "commit", 2: "tree", 3: "blob", 4: "tag"}
_OFS_DELTA, _REF_DELTA = 6, 7
# git's isspace(): tab, newline, carriage return and space - not \v or \f.
_GIT_SPACE = b" \t\n\r"
# FIRST_FEW_BYTES in git's xdiff-interface.c: a NUL in these is "binary".
_BINARY_PROBE = 8000
# Myers edit-distance budget before the line diff anchors on unique lines.
_MAX_EDIT_COST = 2500


class GitReadError(RuntimeError):
    """The repository could not be read the way git would read it."""


def _varint_size(buf: bytes, pos: int) -> tuple[int, int]:
    """The little-endian base-128 size used in delta headers."""
    value = shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            return value, pos


def apply_delta(base: bytes, delta: bytes) -> bytes:
    """Apply one pack delta (copy/insert opcodes) to ``base``."""
    src_size, pos = _varint_size(delta, 0)
    dst_size, pos = _varint_size(delta, pos)
    if src_size != len(base):
        raise GitReadError("delta base size mismatch")
    out = bytearray()
    view = memoryview(base)
    end = len(delta)
    while pos < end:
        op = delta[pos]
        pos += 1
        if op & 0x80:
            offset = size = 0
            if op & 0x01:
                offset = delta[pos]; pos += 1
            if op & 0x02:
                offset |= delta[pos] << 8; pos += 1
            if op & 0x04:
                offset |= delta[pos] << 16; pos += 1
            if op & 0x08:
                offset |= delta[pos] << 24; pos += 1
            if op & 0x10:
                size = delta[pos]; pos += 1
            if op & 0x20:
                size |= delta[pos] << 8; pos += 1
            if op & 0x40:
                size |= delta[pos] << 16; pos += 1
            if size == 0:
                size = 0x10000
            out += view[offset:offset + size]
        elif op:
            out += delta[pos:pos + op]
            pos += op
        else:
            raise GitReadError("delta opcode 0 is reserved")
    if len(out) != dst_size:
        raise GitReadError("delta result size mismatch")
    return bytes(out)


class _Pack:
    """One ``pack-*.idx`` / ``pack-*.pack`` pair."""

    def __init__(self, idx_path: Path, owner: "GitRepo"):
        self.idx_path = idx_path
        self.pack_path = idx_path.with_suffix(".pack")
        self.owner = owner
        data = idx_path.read_bytes()
        self._idx = data
        if data[:4] == b"\xfftOc":
            version = struct.unpack(">I", data[4:8])[0]
            if version != 2:
                raise GitReadError("pack index version %d is not supported" % version)
            self._fanout = struct.unpack(">256I", data[8:8 + 1024])
            count = self._fanout[255]
            self._sha_at, self._stride = 8 + 1024, 20
            self._crc_at = self._sha_at + 20 * count
            self._off_at = self._crc_at + 4 * count
            self._large_at = self._off_at + 4 * count
            self._v1 = False
        else:  # version 1: fanout, then (4-byte offset, 20-byte sha) records
            self._fanout = struct.unpack(">256I", data[:1024])
            self._sha_at, self._stride = 1024 + 4, 24
            self._v1 = True
        self.count = self._fanout[255]
        self._fh: Any = None

    def _sha(self, index: int) -> bytes:
        at = self._sha_at + self._stride * index
        return self._idx[at:at + 20]

    def _offset(self, index: int) -> int:
        if self._v1:
            at = 1024 + 24 * index
            return struct.unpack(">I", self._idx[at:at + 4])[0]
        at = self._off_at + 4 * index
        value = struct.unpack(">I", self._idx[at:at + 4])[0]
        if value & 0x80000000:
            at = self._large_at + 8 * (value & 0x7FFFFFFF)
            value = struct.unpack(">Q", self._idx[at:at + 8])[0]
        return value

    def find(self, binsha: bytes) -> int | None:
        first = binsha[0]
        lo = self._fanout[first - 1] if first else 0
        hi = self._fanout[first]
        while lo < hi:
            mid = (lo + hi) // 2
            probe = self._sha(mid)
            if probe < binsha:
                lo = mid + 1
            elif probe > binsha:
                hi = mid
            else:
                return self._offset(mid)
        return None

    def prefixed(self, prefix: str) -> list[str]:
        """Every object id in this pack that starts with a hex prefix."""
        padded = bytes.fromhex(prefix + "0" * (40 - len(prefix)))
        first = padded[0]
        lo = self._fanout[first - 1] if first else 0
        hi = self._fanout[first]
        while lo < hi:
            mid = (lo + hi) // 2
            if self._sha(mid) < padded:
                lo = mid + 1
            else:
                hi = mid
        found = []
        for index in range(lo, self._fanout[first]):
            full = self._sha(index).hex()
            if not full.startswith(prefix):
                break
            found.append(full)
        return found

    def _file(self) -> Any:
        if self._fh is None:
            self._fh = open(self.pack_path, "rb")
        return self._fh

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            finally:
                self._fh = None

    def _header(self, offset: int) -> tuple[int, int, int, Any]:
        """(type, inflated size, data offset, delta base) of one entry."""
        fh = self._file()
        fh.seek(offset)
        head = fh.read(32)
        pos = 0
        byte = head[pos]; pos += 1
        kind = (byte >> 4) & 7
        size = byte & 0x0F
        shift = 4
        while byte & 0x80:
            byte = head[pos]; pos += 1
            size |= (byte & 0x7F) << shift
            shift += 7
        base: Any = None
        if kind == _OFS_DELTA:
            byte = head[pos]; pos += 1
            distance = byte & 0x7F
            while byte & 0x80:
                byte = head[pos]; pos += 1
                distance = ((distance + 1) << 7) | (byte & 0x7F)
            base = offset - distance
        elif kind == _REF_DELTA:
            base = head[pos:pos + 20].hex()
            pos += 20
        return kind, size, offset + pos, base

    def _inflate(self, at: int, size: int) -> bytes:
        fh = self._file()
        fh.seek(at)
        stream = zlib.decompressobj()
        parts = []
        got = 0
        while not stream.eof:
            chunk = fh.read(max(4096, min(1 << 20, size + 64)))
            if not chunk:
                raise GitReadError("pack %s is truncated" % self.pack_path.name)
            piece = stream.decompress(chunk)
            parts.append(piece)
            got += len(piece)
        data = b"".join(parts)
        if len(data) != size:
            raise GitReadError("pack entry size mismatch in %s" % self.pack_path.name)
        return data

    def read_at(self, offset: int) -> tuple[str, bytes]:
        """Inflate one pack entry, resolving its delta chain iteratively."""
        cache = self.owner._delta_cache
        chain: list[tuple[int, int, int]] = []
        cursor = offset
        while True:
            hit = cache.get((self.pack_path, cursor))
            if hit is not None:
                cache.move_to_end((self.pack_path, cursor))
                kind_name, data = hit
                break
            kind, size, data_at, base = self._header(cursor)
            if kind in _TYPES:
                kind_name, data = _TYPES[kind], self._inflate(data_at, size)
                break
            if len(chain) > 10000:  # pragma: no cover - a corrupt cycle
                raise GitReadError("delta chain too deep")
            if kind == _OFS_DELTA:
                chain.append((cursor, data_at, size))
                cursor = base
                continue
            if kind == _REF_DELTA:
                chain.append((cursor, data_at, size))
                kind_name, data = self.owner.read(base)
                break
            raise GitReadError("unknown pack entry type %d" % kind)
        for entry_at, data_at, size in reversed(chain):
            data = apply_delta(data, self._inflate(data_at, size))
            self.owner._remember((self.pack_path, entry_at), kind_name, data)
        return kind_name, data


class GitRepo:
    """A read-only view of one repository's refs and object store."""

    def __init__(self, path: str | os.PathLike[str]):
        self.git_dir = self._find_git_dir(Path(path))
        common = self.git_dir / "commondir"
        if common.is_file():
            target = Path(common.read_text(encoding="utf-8").strip())
            self.common_dir = target if target.is_absolute() else (self.git_dir / target)
        else:
            self.common_dir = self.git_dir
        self.objects_dir = self.common_dir / "objects"
        if not self.objects_dir.is_dir():
            raise GitReadError("no object store at %s" % self.objects_dir)
        self._check_format()
        self._packs: list[_Pack] = []
        self._pack_names: tuple[str, ...] = ()
        self._packs_loaded = False
        self._delta_cache: OrderedDict[Any, tuple[str, bytes]] = OrderedDict()
        self._delta_bytes = 0
        self._delta_limit = 48 << 20
        self._commits: dict[str, dict[str, Any]] = {}
        self._shallow: set[str] | None = None

    # -- setup -----------------------------------------------------------
    @staticmethod
    def _find_git_dir(path: Path) -> Path:
        if (path / "HEAD").is_file() and (path / "objects").is_dir():
            return path
        dotgit = path / ".git"
        if dotgit.is_dir():
            return dotgit
        if dotgit.is_file():
            text = dotgit.read_text(encoding="utf-8").strip()
            if text.startswith("gitdir:"):
                target = Path(text[len("gitdir:"):].strip())
                return target if target.is_absolute() else (path / target)
        raise GitReadError("%s is not a Git repository" % path)

    def _check_format(self) -> None:
        try:
            config = (self.common_dir / "config").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        lowered = config.lower()
        if re.search(r"objectformat\s*=\s*sha256", lowered):
            raise GitReadError("SHA-256 repositories are not supported by the reader")
        if re.search(r"refstorage\s*=\s*reftable", lowered):
            raise GitReadError("reftable refs are not supported by the reader")

    def close(self) -> None:
        for pack in self._packs:
            pack.close()
        self._delta_cache.clear()
        self._delta_bytes = 0

    def __enter__(self) -> "GitRepo":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- refs --------------------------------------------------------------
    def _packed_refs(self) -> dict[str, str]:
        refs: dict[str, str] = {}
        try:
            text = (self.common_dir / "packed-refs").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return refs
        for line in text.splitlines():
            if not line or line[0] in "#^":
                continue
            sha, _, name = line.partition(" ")
            if _HEX40.match(sha) and name:
                refs[name.strip()] = sha
        return refs

    def _ref_text(self, name: str) -> str | None:
        places = [self.git_dir] if name == "HEAD" else [self.git_dir, self.common_dir]
        for base in places:
            try:
                return (base / name).read_text(encoding="utf-8", errors="replace").strip()
            except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
                continue
            except OSError as exc:
                raise GitReadError("cannot read ref %s: %s" % (name, exc)) from exc
        return self._packed_refs().get(name)

    def symbolic_head(self) -> str:
        """The branch HEAD names (``refs/heads/master``), or '' if detached."""
        text = self._ref_text("HEAD") or ""
        return text[4:].strip() if text.startswith("ref:") else ""

    def resolve_ref(self, name: str = "HEAD") -> str | None:
        """A ref's commit id; None for an unborn branch."""
        for _ in range(10):
            text = self._ref_text(name)
            if text is None:
                return None
            if text.startswith("ref:"):
                name = text[4:].strip()
                continue
            value = text.split()[0] if text else ""
            if _HEX40.match(value):
                return value
            raise GitReadError("ref %s holds %r" % (name, text[:60]))
        raise GitReadError("symbolic ref loop at %s" % name)

    def head(self) -> str | None:
        return self.resolve_ref("HEAD")

    # -- objects -------------------------------------------------------------
    def _load_packs(self, force: bool = False) -> list[_Pack]:
        if self._packs_loaded and not force:
            return self._packs
        self._packs_loaded = True
        pack_dir = self.objects_dir / "pack"
        try:
            names = tuple(sorted(entry.name for entry in os.scandir(pack_dir)
                                 if entry.name.endswith(".idx")))
        except OSError:
            names = ()
        if force or names != self._pack_names:
            for pack in self._packs:
                pack.close()
            packs = []
            for name in names:
                idx = pack_dir / name
                if idx.with_suffix(".pack").is_file():
                    packs.append(_Pack(idx, self))
            self._packs, self._pack_names = packs, names
            self._delta_cache.clear()
            self._delta_bytes = 0
        return self._packs

    def _remember(self, key: Any, kind: str, data: bytes) -> None:
        if len(data) > self._delta_limit // 4:
            return
        self._delta_cache[key] = (kind, data)
        self._delta_bytes += len(data)
        while self._delta_bytes > self._delta_limit and self._delta_cache:
            _, (_, old) = self._delta_cache.popitem(last=False)
            self._delta_bytes -= len(old)

    def _read_loose(self, sha: str) -> tuple[str, bytes] | None:
        path = self.objects_dir / sha[:2] / sha[2:]
        try:
            raw = path.read_bytes()
        except (FileNotFoundError, NotADirectoryError):
            return None
        data = zlib.decompress(raw)
        nul = data.index(b"\0")
        kind, _, size = data[:nul].partition(b" ")
        body = data[nul + 1:]
        if int(size) != len(body):
            raise GitReadError("loose object %s is truncated" % sha)
        return kind.decode("ascii"), body

    def read(self, sha: str) -> tuple[str, bytes]:
        """(type, content) of one object by full hex id."""
        if not _HEX40.match(sha or ""):
            raise GitReadError("bad object id %r" % (sha,))
        binsha = bytes.fromhex(sha)
        for attempt in range(2):
            for pack in self._load_packs(force=attempt > 0):
                offset = pack.find(binsha)
                if offset is not None:
                    return pack.read_at(offset)
            try:
                loose = self._read_loose(sha)
            except (zlib.error, ValueError) as exc:
                raise GitReadError("loose object %s is unreadable: %s" % (sha, exc)) from exc
            if loose is not None:
                return loose
            # A concurrent gc may have moved it from loose into a new pack.
        raise GitReadError("object %s is missing" % sha)

    def exists(self, sha: str) -> bool:
        try:
            self.read(sha)
            return True
        except GitReadError:
            return False

    def resolve_prefix(self, prefix: str) -> str | None:
        """A unique commit id for a hex prefix (4-40 chars), or None."""
        prefix = (prefix or "").strip().lower()
        if not _HEXPREFIX.match(prefix):
            return None
        found: set[str] = set()
        try:
            for entry in os.scandir(self.objects_dir / prefix[:2]):
                name = prefix[:2] + entry.name
                if len(name) == 40 and name.startswith(prefix):
                    found.add(name)
        except OSError:
            pass
        for pack in self._load_packs():
            found.update(pack.prefixed(prefix))
        commits = []
        for sha in found:
            try:
                if self.read(sha)[0] == "commit":
                    commits.append(sha)
            except GitReadError:
                continue
        return commits[0] if len(commits) == 1 else None

    # -- commits ---------------------------------------------------------------
    def _shallow_set(self) -> set[str]:
        if self._shallow is None:
            try:
                text = (self.common_dir / "shallow").read_text(encoding="utf-8")
                self._shallow = {line.strip() for line in text.splitlines() if line.strip()}
            except OSError:
                self._shallow = set()
        return self._shallow

    def commit(self, sha: str) -> dict[str, Any]:
        """One commit, parsed the way ``git log``'s pretty formats see it."""
        cached = self._commits.get(sha)
        if cached is not None:
            return cached
        kind, data = self.read(sha)
        if kind != "commit":
            raise GitReadError("%s is a %s, not a commit" % (sha, kind))
        parsed = parse_commit(sha, data)
        if sha in self._shallow_set():
            parsed["parents"] = []
        self._commits[sha] = parsed
        return parsed

    def walk(self, start: list[str] | None = None, limit: int | None = None,
             known: dict[str, tuple[list[str], int]] | None = None) -> Iterator[str]:
        """Commit ids in ``git log``'s default order.

        ``git log`` pops the newest committer date from its queue; a commit
        is queued once, when first seen, and equal dates leave in the order
        they were queued. ``known`` supplies (parents, committer time) for
        commits already cached so they need no object read.
        """
        if start is None:
            head = self.head()
            start = [head] if head else []
        known = known or {}
        heap: list[tuple[int, int, str]] = []
        seen: set[str] = set()
        counter = 0

        def facts(sha: str) -> tuple[list[str], int]:
            hit = known.get(sha)
            if hit is not None:
                return hit
            row = self.commit(sha)
            return row["parents"], row["committer_time"]

        parents_of: dict[str, list[str]] = {}
        for sha in start:
            if sha in seen:
                continue
            seen.add(sha)
            parents, when = facts(sha)
            parents_of[sha] = parents
            heapq.heappush(heap, (-when, counter, sha))
            counter += 1
        emitted = 0
        while heap:
            _, _, sha = heapq.heappop(heap)
            yield sha
            emitted += 1
            if limit is not None and emitted >= limit:
                return
            parents = parents_of.pop(sha, None)
            for parent in facts(sha)[0] if parents is None else parents:
                if parent in seen:
                    continue
                seen.add(parent)
                grand, when = facts(parent)
                parents_of[parent] = grand
                heapq.heappush(heap, (-when, counter, parent))
                counter += 1

    def log(self, limit: int | None = None, start: list[str] | None = None) -> list[dict[str, Any]]:
        """``git log HEAD`` as dicts: commit, parents, committer_time, author, subject, body."""
        return [self.commit(sha) for sha in self.walk(start, limit)]

    # -- trees and changes -------------------------------------------------------
    def tree(self, sha: str) -> list[tuple[bytes, int, str]]:
        kind, data = self.read(sha)
        if kind != "tree":
            raise GitReadError("%s is a %s, not a tree" % (sha, kind))
        entries = []
        pos, end = 0, len(data)
        while pos < end:
            space = data.index(b" ", pos)
            nul = data.index(b"\0", space)
            mode = int(data[pos:space], 8)
            entries.append((data[space + 1:nul], mode, data[nul + 1:nul + 21].hex()))
            pos = nul + 21
        return entries

    def diff_trees(self, old: str | None, new: str | None, base: bytes = b"",
                   out: list | None = None) -> list[tuple[bytes, Any, Any]]:
        """Changed non-tree paths in git's tree order: (path, old, new),
        where old/new are (mode, sha) or None."""
        out = [] if out is None else out
        left = self.tree(old) if old else []
        right = self.tree(new) if new else []
        i = j = 0
        while i < len(left) or j < len(right):
            a = left[i] if i < len(left) else None
            b = right[j] if j < len(right) else None
            if a is not None and b is not None:
                ka = a[0] + b"/" if _is_tree(a[1]) else a[0]
                kb = b[0] + b"/" if _is_tree(b[1]) else b[0]
                if ka == kb:
                    i += 1
                    j += 1
                    if _is_tree(a[1]):
                        if a[2] != b[2]:
                            self.diff_trees(a[2], b[2], base + a[0] + b"/", out)
                    elif a[2] != b[2] or a[1] != b[1]:
                        out.append((base + a[0], (a[1], a[2]), (b[1], b[2])))
                    continue
                take_left = ka < kb
            else:
                take_left = b is None
            if take_left:
                i += 1
                if _is_tree(a[1]):
                    self.diff_trees(a[2], None, base + a[0] + b"/", out)
                else:
                    out.append((base + a[0], (a[1], a[2]), None))
            else:
                j += 1
                if _is_tree(b[1]):
                    self.diff_trees(None, b[2], base + b[0] + b"/", out)
                else:
                    out.append((base + b[0], None, (b[1], b[2])))
        return out

    def _content(self, side: tuple[int, str]) -> bytes:
        mode, sha = side
        if mode & 0o170000 == 0o160000:  # a submodule reads as one line
            return b"Subproject commit " + sha.encode("ascii") + b"\n"
        kind, data = self.read(sha)
        if kind != "blob":
            raise GitReadError("%s is a %s, not a blob" % (sha, kind))
        return data

    def numstat(self, sha: str) -> list[dict[str, Any]]:
        """``git log --no-renames --numstat`` rows for one commit."""
        row = self.commit(sha)
        parents = row["parents"]
        if len(parents) > 1:
            return []  # git log shows no diff for a merge without -m/--cc
        old_tree = self.commit(parents[0])["tree"] if parents else None
        files = []
        for path, old, new in self.diff_trees(old_tree, row["tree"]):
            before = self._content(old) if old else b""
            after = self._content(new) if new else b""
            binary = bool((old and b"\0" in before[:_BINARY_PROBE])
                          or (new and b"\0" in after[:_BINARY_PROBE]))
            added = deleted = 0
            if not binary and not (old and new and old[1] == new[1]):
                added, deleted = line_counts(before, after)
            files.append({"path": quote_path(path), "added": added,
                          "deleted": deleted, "binary": binary})
        return files


def _is_tree(mode: int) -> bool:
    return mode & 0o170000 == 0o040000


def _ident_name(value: bytes) -> bytes:
    """git's split_ident_line: the name ends at the first '<', trimmed."""
    lt = value.find(b"<")
    name = value if lt < 0 else value[:lt]
    return name.rstrip(_GIT_SPACE)


def _ident_time(value: bytes) -> int:
    gt = value.rfind(b">")
    rest = value[gt + 1:].lstrip(b" \t") if gt >= 0 else b""
    digits = re.match(rb"-?\d+", rest)
    return int(digits.group(0)) if digits else 0


def _decode(value: bytes, encoding: str) -> str:
    if encoding and encoding.lower().replace("-", "").replace("_", "") not in ("utf8",):
        try:
            return value.decode(encoding, errors="replace")
        except LookupError:
            pass
    return value.decode("utf-8", errors="replace")


def _next_line(buf: bytes, pos: int) -> int:
    end = buf.find(b"\n", pos)
    return len(buf) if end < 0 else end + 1


def _skip_blank_lines(buf: bytes, pos: int) -> int:
    while pos < len(buf):
        end = _next_line(buf, pos)
        if buf[pos:end].rstrip(_GIT_SPACE):
            break
        pos = end
    return pos


def split_message(message: bytes) -> tuple[bytes, bytes]:
    """(%s, %b): pretty.c's format_subject / skip_blank_lines."""
    pos = _skip_blank_lines(message, 0)
    lines = []
    while pos < len(message):
        end = _next_line(message, pos)
        line = message[pos:end].rstrip(_GIT_SPACE)
        pos = end
        if not line:
            break
        lines.append(line)
    return b" ".join(lines), message[_skip_blank_lines(message, pos):]


def parse_commit(sha: str, data: bytes) -> dict[str, Any]:
    head_end = data.find(b"\n\n")
    header, message = (data, b"") if head_end < 0 else (data[:head_end], data[head_end + 2:])
    tree = ""
    parents: list[str] = []
    author = committer = b""
    encoding = ""
    for line in header.split(b"\n"):
        if not line or line[:1] == b" ":
            continue  # continuation of a multi-line header (gpgsig, mergetag)
        key, _, value = line.partition(b" ")
        if key == b"tree" and not tree:
            tree = value.decode("ascii").strip()
        elif key == b"parent":
            parents.append(value.decode("ascii").strip())
        elif key == b"author" and not author:
            author = value
        elif key == b"committer" and not committer:
            committer = value
        elif key == b"encoding":
            encoding = value.decode("ascii", errors="replace").strip()
    subject, body = split_message(message)
    return {
        "commit": sha,
        "tree": tree,
        "parents": parents,
        "author": _decode(_ident_name(author), encoding),
        "author_time": _ident_time(author),
        "committer_time": _ident_time(committer),
        "subject": _decode(subject, encoding),
        "body": _decode(body, encoding),
    }


# -- paths ---------------------------------------------------------------------
_ESCAPES = {7: "a", 8: "b", 9: "t", 10: "n", 11: "v", 12: "f", 13: "r", 34: '"', 92: "\\"}


def quote_path(path: bytes) -> str:
    """git's quote_c_style with core.quotePath=true (the default)."""
    if not any(byte < 0x20 or byte in (0x22, 0x5C) or byte >= 0x7F for byte in path):
        return path.decode("utf-8", errors="replace")
    out = ['"']
    for byte in path:
        if byte in _ESCAPES:
            out.append("\\" + _ESCAPES[byte])
        elif byte < 0x20 or byte >= 0x7F:
            out.append("\\%03o" % byte)
        else:
            out.append(chr(byte))
    out.append('"')
    return "".join(out)


# -- line diff -----------------------------------------------------------------
def _lines(data: bytes, table: dict[bytes, int]) -> list[int]:
    """Lines as small ints; a last line without a newline is its own value,
    as in xdiff where the record includes the newline."""
    if not data:
        return []
    parts = data.split(b"\n")
    last = parts.pop()
    if last:
        parts.append(last + b"\n")  # cannot collide: split lines hold no "\n"
    setdefault = table.setdefault
    return [setdefault(part, len(table)) for part in parts]


def _trim(a: list[int], b: list[int]) -> tuple[list[int], list[int], int]:
    n, m = len(a), len(b)
    lo = 0
    top = min(n, m)
    while lo < top and a[lo] == b[lo]:
        lo += 1
    hi = 0
    while hi < top - lo and a[n - 1 - hi] == b[m - 1 - hi]:
        hi += 1
    return a[lo:n - hi], b[lo:m - hi], lo + hi


def _myers_distance(a: list[int], b: list[int], budget: int) -> int | None:
    """Minimal insert+delete count (greedy Myers, forward), or None past budget."""
    n, m = len(a), len(b)
    if not n or not m:
        return n + m
    limit = min(n + m, budget)
    offset = limit + 1
    v = [0] * (2 * limit + 3)
    for d in range(limit + 1):
        for k in range(-d, d + 1, 2):
            if k == -d or (k != d and v[offset + k - 1] < v[offset + k + 1]):
                x = v[offset + k + 1]
            else:
                x = v[offset + k - 1] + 1
            y = x - k
            while x + 64 <= n and y + 64 <= m and a[x:x + 64] == b[y:y + 64]:
                x += 64
                y += 64
            while x < n and y < m and a[x] == b[y]:
                x += 1
                y += 1
            v[offset + k] = x
            if x >= n and y >= m:
                return d
    return None


def _lis(pairs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Longest chain increasing in both coordinates (pairs sorted by i)."""
    import bisect
    tails: list[int] = []
    tail_index: list[int] = []
    back = [-1] * len(pairs)
    for index, (_, j) in enumerate(pairs):
        at = bisect.bisect_left(tails, j)
        if at == len(tails):
            tails.append(j)
            tail_index.append(index)
        else:
            tails[at] = j
            tail_index[at] = index
        back[index] = tail_index[at - 1] if at else -1
    chain = []
    index = tail_index[-1] if tail_index else -1
    while index >= 0:
        chain.append(pairs[index])
        index = back[index]
    return chain[::-1]


def _common(a: list[int], b: list[int], budget: int, depth: int = 0) -> int:
    """Length of a longest common subsequence (exact within budget)."""
    a, b, kept = _trim(a, b)
    if not a or not b:
        return kept
    # A line absent from the other side can never be matched; dropping it
    # keeps the LCS exact and shrinks the search (xdiff does the same).
    in_b, in_a = set(b), set(a)
    a = [x for x in a if x in in_b]
    b = [x for x in b if x in in_a]
    a, b, more = _trim(a, b)
    kept += more
    if not a or not b:
        return kept
    distance = _myers_distance(a, b, budget)
    if distance is not None:
        return kept + (len(a) + len(b) - distance) // 2
    # Too costly for an exact walk: anchor on lines unique to both sides
    # (patience diff) and solve the gaps between anchors.
    if depth < 4:
        count_a, count_b = Counter(a), Counter(b)
        where_b = {x: j for j, x in enumerate(b) if count_b[x] == 1}
        pairs = [(i, where_b[x]) for i, x in enumerate(a) if count_a[x] == 1 and x in where_b]
        chain = _lis(pairs)
        if chain:
            total = kept + len(chain)
            prev_i = prev_j = -1
            for i, j in chain + [(len(a), len(b))]:
                total += _common(a[prev_i + 1:i], b[prev_j + 1:j], budget, depth + 1)
                prev_i, prev_j = i, j
            return total
    shared = Counter(a) & Counter(b)
    return kept + sum(shared.values())  # an upper bound; only for huge rewrites


# git's xdiff (xprepare.c + xdiffi.c, default Myers, no flags), ported so a
# numstat from the reader is the numstat git prints - including git's own
# shortcuts: multi-match lines inside unmatched runs are discarded as
# changes, and past a cost of sqrt(lines) the top box is cut heuristically.
_XDL_MAX_EQLIMIT = 1024
_XDL_SIMSCAN_WINDOW = 100
_XDL_KPDIS_RUN = 4
_XDL_MAX_COST_MIN = 256
_XDL_HEUR_MIN_COST = 256
_XDL_SNAKE_CNT = 20
_XDL_K_HEUR = 4
_XDL_LINE_MAX = (1 << 63) - 1
# What one file may spend in the port before the reader falls back to an
# exact-LCS / patience count.  The costliest diff in the station's history
# (22,796 -> 51,120 lines of app.py) needs 17.7 M diagonal steps, 1.2 s.
_XDIFF_WORK_LIMIT = 400_000_000
_XDIFF_SECONDS = 90.0


class _TooCostly(Exception):
    pass


def _bogosqrt(n: int) -> int:
    i = 1
    while n > 0:
        i <<= 1
        n >>= 2
    return i


def _clean_mmatch(dis: list[int], i: int, s: int, e: int) -> bool:
    if i - s > _XDL_SIMSCAN_WINDOW:
        s = i - _XDL_SIMSCAN_WINDOW
    if e - i > _XDL_SIMSCAN_WINDOW:
        e = i + _XDL_SIMSCAN_WINDOW
    r, rdis0, rpdis0 = 1, 0, 1
    while i - r >= s:
        if not dis[i - r]:
            rdis0 += 1
        elif dis[i - r] == 2:
            rpdis0 += 1
        else:
            break
        r += 1
    if rdis0 == 0:
        return False
    r, rdis1, rpdis1 = 1, 0, 1
    while i + r <= e:
        if not dis[i + r]:
            rdis1 += 1
        elif dis[i + r] == 2:
            rpdis1 += 1
        else:
            break
        r += 1
    if rdis1 == 0:
        return False
    rdis1 += rdis0
    rpdis1 += rpdis0
    return rpdis1 * _XDL_KPDIS_RUN < rpdis1 + rdis1


def _xdl_keep(seq: list[int], start: int, end: int, other: Counter, nrec: int) -> tuple[list[int], int]:
    """xdl_cleanup_records for one side: (kept records, discarded count)."""
    mlim = min(_bogosqrt(nrec), _XDL_MAX_EQLIMIT)
    dis = []
    for index in range(start, end + 1):
        nm = other.get(seq[index], 0)
        dis.append(0 if nm == 0 else 2 if nm >= mlim else 1)
    kept: list[int] = []
    dropped = 0
    last = end - start
    for rel, flag in enumerate(dis):
        if flag == 1 or (flag == 2 and not _clean_mmatch(dis, rel, 0, last)):
            kept.append(seq[start + rel])
        else:
            dropped += 1
    return kept, dropped


def _xdl_split(ha1: list[int], off1: int, lim1: int, ha2: list[int], off2: int, lim2: int,
               kvdf: list[int], kvdb: list[int], base: int, need_min: bool,
               mxcost: int, work: list[int]) -> tuple[int, int, bool, bool]:
    dmin, dmax = off1 - lim2, lim1 - off2
    fmid, bmid = off1 - off2, lim1 - lim2
    odd = (fmid - bmid) & 1
    fmin = fmax = fmid
    bmin = bmax = bmid
    kvdf[base + fmid] = off1
    kvdb[base + bmid] = lim1
    ec = 0
    while True:
        ec += 1
        got_snake = False
        if fmin > dmin:
            fmin -= 1
            kvdf[base + fmin - 1] = -1
        else:
            fmin += 1
        if fmax < dmax:
            fmax += 1
            kvdf[base + fmax + 1] = -1
        else:
            fmax -= 1
        work[0] += fmax - fmin + 2
        for d in range(fmax, fmin - 1, -2):
            left, right = kvdf[base + d - 1], kvdf[base + d + 1]
            i1 = left + 1 if left >= right else right
            prev1 = i1
            i2 = i1 - d
            if i1 < lim1 and i2 < lim2 and ha1[i1] == ha2[i2]:
                i1 += 1
                i2 += 1
                while i1 + 64 <= lim1 and i2 + 64 <= lim2 and ha1[i1:i1 + 64] == ha2[i2:i2 + 64]:
                    i1 += 64
                    i2 += 64
                while i1 < lim1 and i2 < lim2 and ha1[i1] == ha2[i2]:
                    i1 += 1
                    i2 += 1
            if i1 - prev1 > _XDL_SNAKE_CNT:
                got_snake = True
            kvdf[base + d] = i1
            if odd and bmin <= d <= bmax and kvdb[base + d] <= i1:
                return i1, i2, True, True
        if bmin > dmin:
            bmin -= 1
            kvdb[base + bmin - 1] = _XDL_LINE_MAX
        else:
            bmin += 1
        if bmax < dmax:
            bmax += 1
            kvdb[base + bmax + 1] = _XDL_LINE_MAX
        else:
            bmax -= 1
        work[0] += bmax - bmin + 2
        if work[0] > _XDIFF_WORK_LIMIT or time.monotonic() > work[1]:
            raise _TooCostly()
        for d in range(bmax, bmin - 1, -2):
            left, right = kvdb[base + d - 1], kvdb[base + d + 1]
            i1 = left if left < right else right - 1
            prev1 = i1
            i2 = i1 - d
            if i1 > off1 and i2 > off2 and ha1[i1 - 1] == ha2[i2 - 1]:
                i1 -= 1
                i2 -= 1
                while i1 - 64 >= off1 and i2 - 64 >= off2 and ha1[i1 - 64:i1] == ha2[i2 - 64:i2]:
                    i1 -= 64
                    i2 -= 64
                while i1 > off1 and i2 > off2 and ha1[i1 - 1] == ha2[i2 - 1]:
                    i1 -= 1
                    i2 -= 1
            if prev1 - i1 > _XDL_SNAKE_CNT:
                got_snake = True
            kvdb[base + d] = i1
            if not odd and fmin <= d <= fmax and i1 <= kvdf[base + d]:
                return i1, i2, True, True
        if need_min:
            continue
        if got_snake and ec > _XDL_HEUR_MIN_COST:
            best = 0
            split = (0, 0)
            for d in range(fmax, fmin - 1, -2):
                dd = d - fmid if d > fmid else fmid - d
                i1 = kvdf[base + d]
                i2 = i1 - d
                v = (i1 - off1) + (i2 - off2) - dd
                if (v > _XDL_K_HEUR * ec and v > best
                        and off1 + _XDL_SNAKE_CNT <= i1 < lim1
                        and off2 + _XDL_SNAKE_CNT <= i2 < lim2):
                    k = 1
                    while ha1[i1 - k] == ha2[i2 - k]:
                        if k == _XDL_SNAKE_CNT:
                            best = v
                            split = (i1, i2)
                            break
                        k += 1
            if best > 0:
                return split[0], split[1], True, False
            best = 0
            for d in range(bmax, bmin - 1, -2):
                dd = d - bmid if d > bmid else bmid - d
                i1 = kvdb[base + d]
                i2 = i1 - d
                v = (lim1 - i1) + (lim2 - i2) - dd
                if (v > _XDL_K_HEUR * ec and v > best
                        and off1 < i1 <= lim1 - _XDL_SNAKE_CNT
                        and off2 < i2 <= lim2 - _XDL_SNAKE_CNT):
                    k = 0
                    while ha1[i1 + k] == ha2[i2 + k]:
                        if k == _XDL_SNAKE_CNT - 1:
                            best = v
                            split = (i1, i2)
                            break
                        k += 1
            if best > 0:
                return split[0], split[1], False, True
        if ec >= mxcost:
            fbest = fbest1 = -1
            for d in range(fmax, fmin - 1, -2):
                i1 = min(kvdf[base + d], lim1)
                i2 = i1 - d
                if lim2 < i2:
                    i1 = lim2 + d
                    i2 = lim2
                if fbest < i1 + i2:
                    fbest = i1 + i2
                    fbest1 = i1
            bbest = bbest1 = _XDL_LINE_MAX
            for d in range(bmax, bmin - 1, -2):
                i1 = max(off1, kvdb[base + d])
                i2 = i1 - d
                if i2 < off2:
                    i1 = off2 + d
                    i2 = off2
                if i1 + i2 < bbest:
                    bbest = i1 + i2
                    bbest1 = i1
            if (lim1 + lim2) - bbest < fbest - (off1 + off2):
                return fbest1, fbest - fbest1, True, False
            return bbest1, bbest - bbest1, False, True


def _xdiff_counts(a: list[int], b: list[int]) -> tuple[int, int]:
    """(added, deleted) exactly as git's xdiff marks them, or _TooCostly."""
    n1, n2 = len(a), len(b)
    len1, len2 = Counter(a), Counter(b)
    lo, lim = 0, min(n1, n2)
    while lo < lim and a[lo] == b[lo]:
        lo += 1
    hi, lim = 0, lim - lo
    while hi < lim and a[n1 - 1 - hi] == b[n2 - 1 - hi]:
        hi += 1
    ha1, deleted = _xdl_keep(a, lo, n1 - hi - 1, len2, n1)
    ha2, added = _xdl_keep(b, lo, n2 - hi - 1, len1, n2)
    nreff1, nreff2 = len(ha1), len(ha2)
    ndiags = nreff1 + nreff2 + 3
    kvdf = [0] * (ndiags + 2)
    kvdb = [0] * (ndiags + 2)
    base = nreff2 + 1
    mxcost = max(_bogosqrt(ndiags), _XDL_MAX_COST_MIN)
    work = [0, time.monotonic() + _XDIFF_SECONDS]
    boxes = [(0, nreff1, 0, nreff2, False)]
    while boxes:
        off1, lim1, off2, lim2, need_min = boxes.pop()
        while off1 < lim1 and off2 < lim2 and ha1[off1] == ha2[off2]:
            off1 += 1
            off2 += 1
        while off1 < lim1 and off2 < lim2 and ha1[lim1 - 1] == ha2[lim2 - 1]:
            lim1 -= 1
            lim2 -= 1
        if off1 == lim1:
            added += lim2 - off2
        elif off2 == lim2:
            deleted += lim1 - off1
        else:
            i1, i2, min_lo, min_hi = _xdl_split(ha1, off1, lim1, ha2, off2, lim2, kvdf, kvdb,
                                                base, need_min, mxcost, work)
            boxes.append((i1, lim1, i2, lim2, min_hi))
            boxes.append((off1, i1, off2, i2, min_lo))
    return added, deleted


def line_counts(before: bytes, after: bytes, budget: int = _MAX_EDIT_COST) -> tuple[int, int]:
    """(added, deleted) lines, as ``git diff --numstat`` counts them.

    git's own xdiff is replayed first (identical counts). A pathological
    file that would take the pure-Python port too long falls back to a
    minimal line diff (exact LCS, patience-anchored past ``budget``).
    """
    if before == after:
        return 0, 0
    table: dict[bytes, int] = {}
    a, b = _lines(before, table), _lines(after, table)
    try:
        return _xdiff_counts(a, b)
    except _TooCostly:
        common = _common(a, b, budget)
        return len(b) - common, len(a) - common


# -- command line -------------------------------------------------------------
def _main(argv: list[str]) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("-n", type=int, default=10)
    parser.add_argument("--numstat", action="store_true")
    args = parser.parse_args(argv)
    with GitRepo(args.repo) as repo:
        for row in repo.log(limit=args.n):
            print("%s %s %s %s | %s" % (row["commit"][:12], row["committer_time"],
                                        " ".join(p[:7] for p in row["parents"]),
                                        row["author"], row["subject"]))
            if args.numstat:
                for item in repo.numstat(row["commit"]):
                    if item["binary"]:
                        print("-\t-\t%s" % item["path"])
                    else:
                        print("%d\t%d\t%s" % (item["added"], item["deleted"], item["path"]))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
