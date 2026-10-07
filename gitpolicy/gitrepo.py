"""Thin, read-only wrapper around the git command line.

Inside a pre-receive hook git exports GIT_QUARANTINE_PATH /
GIT_OBJECT_DIRECTORY / GIT_ALTERNATE_OBJECT_DIRECTORIES so that the pushed
(not yet accepted) objects are visible. Every git call inherits the
environment, so the hook sees exactly what the push is about to add.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

ZERO = "0" * 40
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


class GitError(RuntimeError):
    pass


def find_git() -> str:
    """git binary: $GITPOLICY_GIT, then PATH, then GitLab's embedded git."""
    env = os.environ.get("GITPOLICY_GIT")
    if env:
        return env
    for cand in (shutil.which("git"), "/opt/gitlab/embedded/bin/git"):
        if cand and os.path.exists(cand):
            return cand
    raise GitError("git binary not found (set GITPOLICY_GIT)")


@dataclass
class Commit:
    sha: str
    parents: List[str]
    author_name: str
    author_email: str
    message: str

    @property
    def is_merge(self) -> bool:
        return len(self.parents) > 1

    @property
    def subject(self) -> str:
        return self.message.split("\n", 1)[0]


@dataclass
class Change:
    """One file changed by a commit (or by a tree diff)."""
    commit: str
    status: str          # A, M, D, T
    path: str
    old_mode: str
    new_mode: str
    old_blob: str
    new_blob: str

    @property
    def is_file(self) -> bool:
        """Regular or executable file on the new side (not a symlink/submodule)."""
        return self.new_mode in ("100644", "100755")


class Repo:
    def __init__(self, path: str = ".", git: Optional[str] = None):
        self.path = path
        self.git = git or find_git()
        self._check = None   # cat-file --batch-check process
        self._batch = None   # cat-file --batch process
        self._sizes: Dict[str, int] = {}

    # ------------------------------------------------------------ plumbing
    def run(self, *args: str, input: Optional[bytes] = None, ok_codes=(0,)) -> bytes:
        p = subprocess.run([self.git, *args], cwd=self.path, input=input,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode not in ok_codes:
            raise GitError("git %s failed (%d): %s" % (
                " ".join(args[:3]), p.returncode, p.stderr.decode(errors="replace").strip()))
        return p.stdout

    def close(self) -> None:
        for proc in (self._check, self._batch):
            if proc is not None:
                try:
                    proc.stdin.close()
                    proc.wait(timeout=5)
                except Exception:  # pragma: no cover - best effort
                    proc.kill()
        self._check = self._batch = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---------------------------------------------------------------- refs
    def resolve(self, rev: str) -> Optional[str]:
        out = self.run("rev-parse", "-q", "--verify", rev + "^{commit}", ok_codes=(0, 1))
        sha = out.decode().strip()
        return sha or None

    def default_branch_ref(self) -> Optional[str]:
        out = self.run("symbolic-ref", "-q", "HEAD", ok_codes=(0, 1)).decode().strip()
        return out or None

    def is_ancestor(self, a: str, b: str) -> bool:
        p = subprocess.run([self.git, "merge-base", "--is-ancestor", a, b], cwd=self.path,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if p.returncode in (0, 1):
            return p.returncode == 0
        raise GitError("merge-base failed: " + p.stderr.decode(errors="replace"))

    def rev_list(self, include: str, exclude: Iterable[str] = (), limit: int = 0) -> List[str]:
        args = ["rev-list", "--topo-order", "--reverse", include] + ["^" + e for e in exclude]
        shas = self.run(*args).decode().split()
        if limit and len(shas) > limit:
            raise TooManyCommits(len(shas))
        return shas

    # ------------------------------------------------------------- commits
    def commits(self, shas: List[str]) -> List[Commit]:
        if not shas:
            return []
        out = self.run("log", "--no-walk=unsorted", "--stdin", "-z",
                       "--format=%H%x1f%P%x1f%an%x1f%ae%x1f%B",
                       input=("\n".join(shas) + "\n").encode())
        res = []
        for rec in out.decode("utf-8", errors="replace").split("\0"):
            if not rec.strip():
                continue
            sha, parents, an, ae, body = rec.split("\x1f", 4)
            res.append(Commit(sha.strip(), parents.split(), an, ae, body.rstrip("\n")))
        return res

    def changes(self, commit: str) -> List[Change]:
        """Files changed by a commit. Merge commits are diffed against the
        first parent (what the merge brings into the target branch)."""
        out = self.run("diff-tree", "-r", "-z", "--no-commit-id", "--no-renames",
                       "--root", "--diff-merges=first-parent", commit)
        return _parse_raw(out, commit)

    def tree_changes(self, old: Optional[str], new: str) -> List[Change]:
        """Net difference between two commits (old=None: everything in new)."""
        out = self.run("diff-tree", "-r", "-z", "--no-renames", old or EMPTY_TREE, new)
        return _parse_raw(out, new)

    # --------------------------------------------------------------- blobs
    def blob_size(self, sha: str) -> int:
        if sha in self._sizes:
            return self._sizes[sha]
        if self._check is None:
            self._check = subprocess.Popen([self.git, "cat-file", "--batch-check"], cwd=self.path,
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self._check.stdin.write(sha.encode() + b"\n")
        self._check.stdin.flush()
        header = self._check.stdout.readline().decode().split()
        if len(header) != 3:
            raise GitError("cat-file: object %s not found" % sha)
        self._sizes[sha] = int(header[2])
        return self._sizes[sha]

    def blob_head(self, sha: str, limit: int) -> bytes:
        """First `limit` bytes of a blob, without loading huge blobs into memory."""
        size = self.blob_size(sha)
        if size > 4 * 1024 * 1024:
            proc = subprocess.Popen([self.git, "cat-file", "blob", sha], cwd=self.path,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            try:
                data = proc.stdout.read(limit)
            finally:
                proc.kill()
                proc.wait()
            return data
        if self._batch is None:
            self._batch = subprocess.Popen([self.git, "cat-file", "--batch"], cwd=self.path,
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self._batch.stdin.write(sha.encode() + b"\n")
        self._batch.stdin.flush()
        header = self._batch.stdout.readline().decode().split()
        if len(header) != 3:
            raise GitError("cat-file: object %s not found" % sha)
        n = int(header[2])
        data = self._batch.stdout.read(n)
        self._batch.stdout.read(1)  # trailing newline
        return data[:limit]


class TooManyCommits(GitError):
    def __init__(self, count: int):
        super().__init__("%d commits" % count)
        self.count = count


def _parse_raw(out: bytes, commit: str) -> List[Change]:
    """Parse `git diff-tree -r -z` raw output."""
    res: List[Change] = []
    parts = out.split(b"\0")
    i = 0
    while i < len(parts):
        meta = parts[i]
        if not meta.startswith(b":"):
            i += 1
            continue
        fields = meta[1:].decode().split()
        path = parts[i + 1].decode("utf-8", errors="surrogateescape")
        i += 2
        old_mode, new_mode, old_blob, new_blob, status = fields[:5]
        res.append(Change(commit, status[0], path, old_mode, new_mode, old_blob, new_blob))
    return res


def parse_ref_updates(text: str) -> List[Tuple[str, str, str]]:
    res = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 3:
            res.append((parts[0], parts[1], parts[2]))
    return res
