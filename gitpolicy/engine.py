"""Policy evaluation: compiled bundle + pushed ref updates -> violations.

Which commits are checked for a ref update old -> new on branch B:

  * update  (old != 0): every commit reachable from new but not from old.
    Commits that already exist on *other* branches are included on purpose:
    content that slipped into one branch (e.g. pushed before the profile was
    loaded) can never be merged or pushed into another branch without being
    checked again.
  * create  (old == 0): every commit not already on the default branch. A
    branch created from a clean main is cheap; a branch created from a dirty
    feature branch is checked in full.
  * delete  (new == 0): only ref rules (no_branch_delete).

Non-branch refs (tags, GitLab internal refs) are not checked.
"""
from __future__ import annotations

import json
from typing import List, Optional

from . import BUNDLE_FORMAT
from .globs import project_matches
from .gitrepo import ZERO, Change, Repo, TooManyCommits
from .rules import Violation, build


class BundleError(RuntimeError):
    pass


class RefUpdate:
    def __init__(self, old: str, new: str, ref: str):
        self.old, self.new, self.ref = old, new, ref

    @property
    def is_branch(self) -> bool:
        return self.ref.startswith("refs/heads/")

    @property
    def branch(self) -> str:
        return self.ref[len("refs/heads/"):] if self.is_branch else self.ref

    @property
    def is_create(self) -> bool:
        return self.old == ZERO and self.new != ZERO

    @property
    def is_delete(self) -> bool:
        return self.new == ZERO

    @property
    def is_update(self) -> bool:
        return self.old != ZERO and self.new != ZERO


class Bundle:
    """The compiled policy (bundle.json) produced by `gitpolicy compile`."""

    def __init__(self, data: dict):
        if not isinstance(data, dict) or data.get("format") != BUNDLE_FORMAT:
            raise BundleError("unsupported bundle format %r" % (data.get("format") if isinstance(data, dict) else data))
        self.data = data
        self.settings = data.get("settings", {})
        self.profiles = data.get("profiles", {})
        self.assignments = data.get("assignments", [])
        for a in self.assignments:
            if a["profile"] not in self.profiles:
                raise BundleError("assignment %s -> unknown profile %s" % (a["project"], a["profile"]))

    @classmethod
    def load(cls, path: str) -> "Bundle":
        try:
            with open(path, encoding="utf-8") as f:
                return cls(json.load(f))
        except (OSError, ValueError) as e:
            raise BundleError("cannot read bundle %s: %s" % (path, e))

    def resolve(self, project: str):
        """Return (profile_ref, match) for a project path, or (None, None).

        An exact project path wins over patterns; among patterns the longest
        (most specific) wins, ties go to the one listed first."""
        best = None
        for a in self.assignments:
            pat = a["project"]
            if pat.lower() == project.lower():
                return a["profile"], pat
            if any(ch in pat for ch in "*?[") and project_matches(project, pat):
                if best is None or len(pat) > len(best["project"]):
                    best = a
        return (best["profile"], best["project"]) if best else (None, None)


class Context:
    def __init__(self, repo: Repo, settings: dict):
        self.repo = repo
        self.settings = settings
        self.notes: List[str] = []


class Result:
    def __init__(self, project: str, profile: Optional[str]):
        self.project = project
        self.profile = profile
        self.violations: List[Violation] = []
        self.notes: List[str] = []
        self.checked_commits = 0
        self.checked_files = 0

    @property
    def blocked(self) -> List[Violation]:
        return [v for v in self.violations if v.action == "block"]

    @property
    def warnings(self) -> List[Violation]:
        return [v for v in self.violations if v.action == "warn"]

    @property
    def allowed(self) -> bool:
        return not self.blocked


def evaluate(bundle: Bundle, repo: Repo, project: str, updates: List[RefUpdate]) -> Result:
    profile_ref, _ = bundle.resolve(project)
    result = Result(project, profile_ref)
    if profile_ref is None:
        return result
    rules = [build(r) for r in bundle.profiles[profile_ref]["rules"]]
    ctx = Context(repo, bundle.settings)
    max_commits = int(bundle.settings.get("max_commits", 10000))

    for up in updates:
        if not up.is_branch:
            continue
        active = [r for r in rules if r.applies_to(up.branch)]
        if not active:
            continue
        for r in active:
            if r.REF:
                result.violations += r.check_ref(ctx, up)
        if up.is_delete:
            continue

        commit_rules = [r for r in active if r.COMMIT]
        change_rules = [r for r in active if r.CHANGE]
        if not (commit_rules or change_rules):
            continue

        exclude = _base_for(repo, up)
        try:
            shas = repo.rev_list(up.new, exclude, limit=max_commits)
        except TooManyCommits as e:
            # Very large range (e.g. importing an old repository): check the
            # net tree difference instead of every commit.
            result.notes.append("%s: %d commits pushed (> %d) - checked the resulting files only, "
                                "commit rules skipped" % (up.branch, e.count, max_commits))
            base = exclude[0] if exclude else None
            changes = repo.tree_changes(base, up.new)
            result.checked_files += len(changes)
            _check_changes(ctx, up, change_rules, changes, result)
            continue

        result.checked_commits += len(shas)
        if commit_rules:
            for c in repo.commits(shas):
                for r in commit_rules:
                    result.violations += r.check_commit(ctx, up, c)
        if change_rules:
            seen = set()
            changes = []
            for sha in shas:
                for ch in repo.changes(sha):
                    key = (ch.status, ch.path, ch.new_blob)
                    if key not in seen:
                        seen.add(key)
                        changes.append(ch)
            result.checked_files += len(changes)
            _check_changes(ctx, up, change_rules, changes, result)
    return result


def _base_for(repo: Repo, up: RefUpdate) -> List[str]:
    if up.is_update:
        return [up.old]
    head = repo.default_branch_ref()
    if head and head != up.ref:
        sha = repo.resolve(head)
        if sha:
            return [sha]
    return []


def _check_changes(ctx, up, rules, changes: List[Change], result: Result) -> None:
    for ch in changes:
        for r in rules:
            result.violations += r.check_change(ctx, up, ch)
