"""git_log_reader reads history the way ``git log`` prints it, without git.

The fixture repository is built with the real git binary (plumbing only, so
odd paths, modes, dates and headers are exact on every platform), then the
reader is compared with ``git log`` for the walk and with
``git log --no-renames --numstat`` for the files: loose, packed with
OFS_DELTA, packed with REF_DELTA, a version-1 pack index, packed refs and a
detached HEAD.  The line counter is also checked against
``git diff --no-index --numstat`` on a few hundred random edits.
"""
from __future__ import annotations

import os
import random
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from git_log_reader import GitReadError, GitRepo, line_counts, quote_path, split_message  # noqa: E402

GIT = shutil.which("git")
FMT = "--format=%x1e%H%x1f%P%x1f%ct%x1f%an%x1f%s%x1f%b%x1d"
BASE_TIME = 1790000000


def _rmtree(path: str) -> None:
    def unlock(func, target, _exc):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass
    shutil.rmtree(path, onerror=unlock)


class Fixture:
    """A repository assembled from plumbing commands."""

    def __init__(self, root: Path):
        self.repo = root
        self.run("init", "-q")
        for key, value in (("user.name", "Pine Test"), ("user.email", "pine@example.test"),
                           ("core.autocrlf", "false"), ("gc.auto", "0"),
                           ("commit.gpgsign", "false"), ("core.quotepath", "true")):
            self.run("config", key, value)
        self.env = dict(os.environ, GIT_AUTHOR_NAME="Pine Test", GIT_AUTHOR_EMAIL="pine@example.test",
                        GIT_COMMITTER_NAME="Pine Test", GIT_COMMITTER_EMAIL="pine@example.test")

    def run(self, *args: str, data: bytes | None = None, env: dict | None = None) -> bytes:
        return subprocess.run([GIT, "-C", str(self.repo), *args], input=data, check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=env or getattr(self, "env", None)).stdout

    def blob(self, content: bytes) -> str:
        return self.run("hash-object", "-w", "--stdin", data=content).decode().strip()

    def tree(self, files: dict[bytes, tuple[str, str]]) -> str:
        """files: path -> (mode, sha); nested paths become subtrees."""
        direct: dict[bytes, tuple[str, str, str]] = {}
        nested: dict[bytes, dict[bytes, tuple[str, str]]] = {}
        for path, (mode, sha) in files.items():
            head, sep, rest = path.partition(b"/")
            if sep:
                nested.setdefault(head, {})[rest] = (mode, sha)
            else:
                kind = "commit" if mode == "160000" else "blob"
                direct[head] = (mode, kind, sha)
        for name, inner in nested.items():
            direct[name] = ("040000", "tree", self.tree(inner))
        listing = b"".join(b"%s %s %s\t%s\0" % (mode.encode(), kind.encode(), sha.encode(), name)
                           for name, (mode, kind, sha) in direct.items())
        return self.run("mktree", "-z", "--missing", data=listing).decode().strip()

    def commit(self, files: dict[bytes, tuple[str, str]], message: bytes, when: int,
               parents: tuple[str, ...] = (), author: str = "Pine Test",
               encoding: str = "") -> str:
        env = dict(self.env, GIT_AUTHOR_NAME=author,
                   GIT_AUTHOR_DATE="%d +0000" % when, GIT_COMMITTER_DATE="%d +0000" % when)
        args = []
        if encoding:
            args = ["-c", "i18n.commitEncoding=" + encoding]
        parent_args = []
        for parent in parents:
            parent_args += ["-p", parent]
        tree = self.tree(files)
        return subprocess.run([GIT, "-C", str(self.repo), *args, "commit-tree", tree, *parent_args],
                              input=message, check=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env=env).stdout.decode().strip()

    def raw_commit(self, body: bytes) -> str:
        return self.run("hash-object", "-t", "commit", "-w", "--literally", "--stdin",
                        data=body).decode().strip()

    def point_head(self, sha: str) -> None:
        self.run("update-ref", "refs/heads/master", sha)
        self.run("symbolic-ref", "HEAD", "refs/heads/master")


def _numbered(lines: list[str]) -> bytes:
    return ("\n".join(lines) + "\n").encode()


def build_history(fx: Fixture) -> dict[str, str]:
    rng = random.Random(1428)
    shas: dict[str, str] = {}
    blob = fx.blob

    def code(n: int, seed: int) -> list[str]:
        local = random.Random(seed)
        out = []
        for i in range(n):
            pick = local.random()
            out.append("" if pick < 0.12 else "}" if pick < 0.2 else
                       "    return None" if pick < 0.25 else "line %d value %d" % (i, local.randint(0, 9)))
        return out

    big = code(1800, 7)
    files = {
        b"README.md": ("100644", blob(b"# Pine\n\nfirst\n")),
        b"src/app/main.py": ("100644", blob(_numbered(big))),
        b"src/app/empty.txt": ("100644", blob(b"")),
        b"noeol.txt": ("100644", blob(b"one\ntwo")),
        b"bin.dat": ("100644", blob(b"\x00\x01\x02binary\n" * 20)),
        b"script.sh": ("100644", blob(b"#!/bin/sh\necho hi\n")),
        b"thing": ("100644", blob(b"a file that becomes a directory\n")),
        b"gone.txt": ("100644", blob(b"delete me\n" * 3)),
        b"dir with space/file.txt": ("100644", blob(b"spaced\n")),
    }
    c1 = fx.commit(files, b"Root commit\n\nThe first one.\n", BASE_TIME)
    shas["root"] = c1

    files = dict(files)
    files[b"README.md"] = ("100644", blob(b"# Pine\n\nfirst\nsecond\n"))
    files[b"noeol.txt"] = ("100644", blob(b"one\ntwo\n"))
    files[b"bin.dat"] = ("100644", blob(b"\x00\x09changed\n" * 25))
    files[b"script.sh"] = ("100755", files[b"script.sh"][1])  # mode only
    del files[b"gone.txt"]
    files["ü-non-ascii ☃.txt".encode()] = ("100644", blob(b"snow\n"))
    files[b'tab\tand "quote" and back\\slash.txt'] = ("100644", blob(b"odd\n"))
    files[b"crlf.txt"] = ("100644", blob(b"a\r\nb\r\nc\r\n"))
    message = (b"\n\n  Leading blank lines, then a two-line   \nsubject paragraph\t \n\n\n"
               b"Body line one   \r\nPine-Prompt: keep the history\n\nPine-Token-In: 12\n")
    c2 = fx.commit(files, message, BASE_TIME + 100, (c1,))
    shas["messy"] = c2

    files = dict(files)
    del files[b"thing"]
    files[b"thing/inner.txt"] = ("100644", blob(b"now a directory\n"))
    files[b"link"] = ("120000", blob(b"README.md"))
    files[b"module"] = ("160000", c1)  # a submodule pointer
    files[b"crlf.txt"] = ("100644", blob(b"a\r\nB\r\nc\r\n"))
    c3 = fx.commit(files, b"File becomes a directory; symlink; submodule\n", BASE_TIME + 200, (c2,))

    # Equal committer dates on both sides of a merge, and a merge commit.
    side_files = dict(files)
    side_files[b"side.txt"] = ("100644", blob(b"side branch\n"))
    side = fx.commit(side_files, b"Side branch work\n", BASE_TIME + 300, (c3,))
    main_files = dict(files)
    main_files[b"README.md"] = ("100644", blob(b"# Pine\n\nfirst\nsecond\nthird\n"))
    main = fx.commit(main_files, b"Main branch work\n", BASE_TIME + 300, (c3,))
    merged_files = dict(main_files)
    merged_files[b"side.txt"] = side_files[b"side.txt"]
    merge = fx.commit(merged_files, b"Merge side into main\n", BASE_TIME + 300, (main, side))
    shas["merge"] = merge

    # A commit dated before its parent (clock skew) and a Latin-1 message.
    skew = fx.commit(merged_files, "Café skewed clock\n\nDéjà vu.\n".encode("latin-1"),
                     BASE_TIME + 50, (merge,), encoding="ISO-8859-1")
    shas["latin1"] = skew

    # A raw commit with a multi-line signature-style header.
    tree = fx.tree(merged_files)
    raw = (b"tree %s\nparent %s\nauthor Sig Ned <sig@example.test> %d +0000\n"
           b"committer Sig Ned <sig@example.test> %d +0000\n"
           b"gpgsig -----BEGIN PGP SIGNATURE-----\n \n iQEzBAABCAAdFiEE\n -----END PGP SIGNATURE-----\n"
           b"\nSigned-looking commit\n\nWith a body.\n") % (tree.encode(), skew.encode(),
                                                          BASE_TIME + 400, BASE_TIME + 400)
    signed = fx.raw_commit(raw)
    shas["signed"] = signed

    # Many edits to a big file with repeated lines: exercises xdiff's
    # discards, its cost heuristics, and pack deltas.
    parent = signed
    current = list(big)
    for step in range(10):
        edited = list(current)
        for _ in range(rng.choice([3, 40, 400])):
            where = rng.randrange(len(edited) + 1)
            action = rng.random()
            if action < 0.4 and edited:
                del edited[min(where, len(edited) - 1)]
            elif action < 0.7:
                edited.insert(where, rng.choice(["", "}", "    return None", "new %d" % rng.randint(0, 99)]))
            elif edited:
                edited[min(where, len(edited) - 1)] = "changed %d" % rng.randint(0, 999)
        if step == 6:  # a large block move
            edited = edited[900:] + edited[:900]
        files = dict(merged_files)
        files[b"src/app/main.py"] = ("100644", blob(_numbered(edited)))
        parent = fx.commit(files, b"Edit round %d\n" % step, BASE_TIME + 500 + step, (parent,))
        current = edited
    shas["tip"] = parent
    fx.point_head(parent)
    return shas


@unittest.skipUnless(GIT, "the git binary builds the fixture repository")
class ReaderMatchesGit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="glr-")
        root = Path(cls.tmp) / "repo"
        root.mkdir()
        cls.fx = Fixture(root)
        cls.shas = build_history(cls.fx)

    @classmethod
    def tearDownClass(cls):
        _rmtree(cls.tmp)

    def git_log(self) -> list[tuple]:
        raw = self.fx.run("log", "HEAD", FMT).decode("utf-8", errors="replace")
        rows = []
        for record in raw.split("\x1e"):
            if "\x1d" not in record:
                continue
            f = record.split("\x1d", 1)[0].lstrip("\n").split("\x1f", 5)
            rows.append((f[0], f[1].split(), int(f[2]), f[3], f[4], f[5]))
        return rows

    def git_numstat(self, shas: list[str]) -> dict[str, list[tuple]]:
        raw = self.fx.run("log", "--no-walk=unsorted", "--stdin", "--no-renames", "--numstat",
                          "--format=%x1e%H%x1d", data=("\n".join(shas) + "\n").encode())
        out = {}
        for record in raw.decode("utf-8", errors="replace").split("\x1e"):
            if "\x1d" not in record:
                continue
            sha, changed = record.split("\x1d", 1)
            rows = []
            for line in changed.splitlines():
                parts = line.split("\t", 2)
                if len(parts) == 3:
                    rows.append((parts[2], parts[0], parts[1]))
            out[sha.strip()] = rows
        return out

    def reader_rows(self, repo: GitRepo) -> tuple[list[tuple], dict[str, list[tuple]]]:
        walk = [(r["commit"], r["parents"], r["committer_time"], r["author"], r["subject"], r["body"])
                for r in repo.log()]
        stats = {}
        for sha, *_ in walk:
            stats[sha] = [(f["path"], "-" if f["binary"] else str(f["added"]),
                           "-" if f["binary"] else str(f["deleted"])) for f in repo.numstat(sha)]
        return walk, stats

    def assert_same_as_git(self) -> None:
        expected_walk = self.git_log()
        expected_stats = self.git_numstat([row[0] for row in expected_walk])
        with GitRepo(self.fx.repo) as repo:
            walk, stats = self.reader_rows(repo)
        self.assertEqual(len(walk), len(expected_walk))
        for mine, theirs in zip(walk, expected_walk):
            self.assertEqual(mine, theirs)
        for sha, rows in expected_stats.items():
            self.assertEqual(stats[sha], rows, sha)

    def pack_kinds(self) -> set[int]:
        kinds = set()
        pack_dir = self.fx.repo / ".git" / "objects" / "pack"
        with GitRepo(self.fx.repo) as repo:
            for pack in repo._load_packs(force=True):
                for index in range(pack.count):
                    kinds.add(pack._header(pack._offset(index))[0])
        self.assertTrue(list(pack_dir.glob("*.pack")))
        return kinds

    def test_1_loose_objects_match_git_log(self):
        self.assertFalse(list((self.fx.repo / ".git" / "objects" / "pack").glob("*.pack")))
        self.assert_same_as_git()

    def test_2_fixture_covers_the_hard_cases(self):
        walk = self.git_log()
        subjects = {row[4] for row in walk}
        # git keeps a subject's leading spaces and joins its lines with one space
        self.assertIn("  Leading blank lines, then a two-line subject paragraph", subjects)
        self.assertIn("Café skewed clock", subjects)
        dates = [row[2] for row in walk]
        self.assertGreater(len(dates), len(set(dates)))  # ties exist
        stats = self.git_numstat([self.shas["messy"]])[self.shas["messy"]]
        paths = [row[0] for row in stats]
        self.assertTrue(any(path.startswith('"') for path in paths))  # quoted paths
        self.assertIn(("bin.dat", "-", "-"), stats)
        self.assertIn(("script.sh", "0", "0"), stats)
        self.assertEqual(self.git_numstat([self.shas["merge"]])[self.shas["merge"]], [])

    def test_3_ofs_delta_pack_matches_git_log(self):
        self.fx.run("repack", "-a", "-d", "-f", "-q", "--depth=50", "--window=50")
        self.fx.run("prune-packed")
        self.assertIn(6, self.pack_kinds())  # OFS_DELTA entries present
        self.assert_same_as_git()

    def test_4_ref_delta_pack_and_v1_index_match_git_log(self):
        self.fx.run("-c", "repack.useDeltaBaseOffset=false", "-c", "pack.indexVersion=1",
                    "repack", "-a", "-d", "-f", "-q", "--depth=50", "--window=50")
        self.fx.run("prune-packed")
        idx = next((self.fx.repo / ".git" / "objects" / "pack").glob("*.idx")).read_bytes()
        self.assertNotEqual(idx[:4], b"\xfftOc")  # version 1 index
        self.assertIn(7, self.pack_kinds())  # REF_DELTA entries present
        self.assert_same_as_git()

    def test_5_packed_refs_and_detached_head(self):
        self.fx.run("pack-refs", "--all")
        self.assertFalse((self.fx.repo / ".git" / "refs" / "heads" / "master").exists())
        with GitRepo(self.fx.repo) as repo:
            self.assertEqual(repo.head(), self.shas["tip"])
            self.assertEqual(repo.symbolic_head(), "refs/heads/master")
            self.assertEqual(repo.resolve_prefix(self.shas["signed"][:10]), self.shas["signed"])
            self.assertIsNone(repo.resolve_prefix("zz"))
        self.fx.run("update-ref", "--no-deref", "HEAD", self.shas["latin1"])
        try:
            with GitRepo(self.fx.repo) as repo:
                self.assertEqual(repo.head(), self.shas["latin1"])
                self.assertEqual(repo.symbolic_head(), "")
            self.assert_same_as_git()
        finally:
            self.fx.run("symbolic-ref", "HEAD", "refs/heads/master")

    def test_6_limit_stops_early(self):
        with GitRepo(self.fx.repo) as repo:
            self.assertEqual([r["commit"] for r in repo.log(limit=3)],
                             [row[0] for row in self.git_log()[:3]])


@unittest.skipUnless(GIT, "git diff --no-index is the reference")
class LineCountsMatchXdiff(unittest.TestCase):
    def test_random_edits_match_git_diff_numstat(self):
        rng = random.Random(9)
        tmp = tempfile.mkdtemp(prefix="glr-diff-")
        try:
            vocabulary = ["", "}", "{", "    pass", "return x", "a", "b", "c"] + ["u%d" % i for i in range(40)]
            for case in range(160):
                size = rng.choice([0, 1, 5, 30, 120, 400, 1500])
                before = [rng.choice(vocabulary) for _ in range(size)]
                after = list(before)
                for _ in range(rng.choice([1, 3, 10, 60, 300])):
                    where = rng.randrange(len(after) + 1)
                    if rng.random() < 0.5 and after:
                        del after[min(where, len(after) - 1)]
                    else:
                        after.insert(where, rng.choice(vocabulary))
                a_bytes = ("\n".join(before) + ("\n" if rng.random() < 0.8 else "")).encode()
                b_bytes = ("\n".join(after) + ("\n" if rng.random() < 0.8 else "")).encode()
                if not before:
                    a_bytes = b""
                pa, pb = Path(tmp) / ("a%d" % case), Path(tmp) / ("b%d" % case)
                pa.write_bytes(a_bytes)
                pb.write_bytes(b_bytes)
                out = subprocess.run([GIT, "-c", "core.autocrlf=false", "diff", "--no-index",
                                      "--numstat", str(pa), str(pb)],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode()
                expected = (0, 0)
                if out.strip():
                    added, deleted = out.split("\t")[:2]
                    expected = (int(added), int(deleted))
                self.assertEqual(line_counts(a_bytes, b_bytes), expected,
                                 "case %d: %d -> %d lines" % (case, len(before), len(after)))
        finally:
            _rmtree(tmp)


class PureHelpers(unittest.TestCase):
    def test_split_message_follows_pretty_c(self):
        self.assertEqual(split_message(b"\n\nOne  \ntwo\t\n\n\nBody\n"), (b"One two", b"Body\n"))
        self.assertEqual(split_message(b"Only subject"), (b"Only subject", b""))
        self.assertEqual(split_message(b""), (b"", b""))

    def test_quote_path_follows_core_quotepath(self):
        self.assertEqual(quote_path(b"plain name.txt"), "plain name.txt")
        self.assertEqual(quote_path("ü.txt".encode()), '"\\303\\274.txt"')
        self.assertEqual(quote_path(b'a\t"b"\\c'), '"a\\t\\"b\\"\\\\c"')

    def test_line_counts_basics(self):
        self.assertEqual(line_counts(b"", b"a\nb\n"), (2, 0))
        self.assertEqual(line_counts(b"a\nb\n", b""), (0, 2))
        self.assertEqual(line_counts(b"a\nb", b"a\nb\n"), (1, 1))  # the missing newline counts
        self.assertEqual(line_counts(b"x\n", b"x\n"), (0, 0))

    def test_a_diff_too_costly_for_the_port_still_counts(self):
        import git_log_reader
        before = b"".join(b"line %d\n" % i for i in range(400))
        after = b"".join(b"line %d\n" % i for i in range(0, 400, 2)) + b"tail\n"
        exact = line_counts(before, after)
        original = git_log_reader._XDIFF_WORK_LIMIT
        git_log_reader._XDIFF_WORK_LIMIT = 0  # force the minimal-LCS fallback
        try:
            self.assertEqual(line_counts(before, after), (1, 200))
        finally:
            git_log_reader._XDIFF_WORK_LIMIT = original
        self.assertEqual(exact, (1, 200))

    def test_missing_repository_is_a_clear_error(self):
        tmp = tempfile.mkdtemp(prefix="glr-none-")
        try:
            with self.assertRaises(GitReadError):
                GitRepo(tmp)
        finally:
            _rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
