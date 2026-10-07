"""Control plane: the GitOps policy repository -> compiled bundle.

Repository layout (see policy-config/ for a complete sample):

    settings.yaml                    global settings
    assignments.yaml                 GitLab project -> profile (managed by Jenkins)
    profiles/<name>/<version>.yaml   one immutable profile version per file

A profile is referenced as name@version (e.g. no-binaries@1). Published
versions are immutable: changing a rule means adding <version+1>.yaml and
loading the new version. Profiles never inherit from or merge with each other
- the rules a project gets are exactly the rules of its one profile.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import subprocess
from typing import Dict, List, Optional, Tuple

import yaml

from . import BUNDLE_FORMAT, __version__
from .globs import project_matches
from .rules import RuleError, normalize

NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,48}[a-z0-9])?$")
PROJECT = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_.-]*(/[A-Za-z0-9_.][A-Za-z0-9_.-]*)+$")
PROJECT_PATTERN = re.compile(r"^[A-Za-z0-9_.*?\[\]/-]+$")
REF = re.compile(r"^([a-z0-9](?:[a-z0-9-]*[a-z0-9])?)@([1-9][0-9]*)$")

SETTINGS_DEFAULTS = {
    "fail_mode": "closed",
    "break_glass_users": [],
    "locked_projects": [],
    "deprecated_profiles": [],
    "max_commits": 10000,
}

ASSIGNMENTS_HEADER = """\
# GitLab project -> policy profile (name@version).
# Managed by the Jenkins job policy/load-profile: every change is a commit by
# the Jenkins user who loaded the profile. Admins may also edit this file by
# hand (via merge request); project patterns such as "demo/*" are allowed.
"""


class ConfigError(ValueError):
    """Raised with a list of human readable problems."""

    def __init__(self, problems):
        if isinstance(problems, str):
            problems = [problems]
        super().__init__("\n".join(problems))
        self.problems = list(problems)


def _read_yaml(path: str):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


# ------------------------------------------------------------------ loading
def load_settings(root: str) -> dict:
    path = os.path.join(root, "settings.yaml")
    data = _read_yaml(path) if os.path.exists(path) else {}
    data = data or {}
    if not isinstance(data, dict):
        raise ConfigError("settings.yaml: must be a mapping")
    problems = []
    unknown = set(data) - set(SETTINGS_DEFAULTS)
    if unknown:
        problems.append("settings.yaml: unknown key(s) %s" % ", ".join(sorted(unknown)))
    out = dict(SETTINGS_DEFAULTS)
    out.update(data)
    if out["fail_mode"] not in ("closed", "open"):
        problems.append("settings.yaml: fail_mode must be closed or open")
    for key in ("break_glass_users", "locked_projects", "deprecated_profiles"):
        if not isinstance(out[key], list) or not all(isinstance(x, str) for x in out[key]):
            problems.append("settings.yaml: %s must be a list of strings" % key)
    if not isinstance(out["max_commits"], int) or isinstance(out["max_commits"], bool) or out["max_commits"] < 1:
        problems.append("settings.yaml: max_commits must be a positive integer")
    if problems:
        raise ConfigError(problems)
    return out


def load_profiles(root: str) -> Dict[str, dict]:
    """Return {name@version: {"path", "sha256", "name", "version", "description", "rules"}}."""
    base = os.path.join(root, "profiles")
    profiles, problems = {}, []
    if not os.path.isdir(base):
        raise ConfigError("profiles/ directory missing in %s" % root)
    for name in sorted(os.listdir(base)):
        pdir = os.path.join(base, name)
        if not os.path.isdir(pdir):
            problems.append("profiles/%s: expected a directory profiles/<name>/<version>.yaml" % name)
            continue
        if not NAME.match(name):
            problems.append("profiles/%s: invalid profile name (lowercase letters, digits, -)" % name)
            continue
        for fname in sorted(os.listdir(pdir)):
            rel = "profiles/%s/%s" % (name, fname)
            m = re.match(r"^([1-9][0-9]*)\.ya?ml$", fname)
            if not m:
                problems.append("%s: file name must be <version>.yaml, version = 1, 2, 3 ..." % rel)
                continue
            version = int(m.group(1))
            try:
                profiles["%s@%d" % (name, version)] = _load_profile(os.path.join(pdir, fname), rel, name, version)
            except ConfigError as e:
                problems += e.problems
            except yaml.YAMLError as e:
                problems.append("%s: invalid YAML: %s" % (rel, e))
    if problems:
        raise ConfigError(problems)
    return profiles


def _load_profile(path: str, rel: str, name: str, version: int) -> dict:
    data = _read_yaml(path)
    if not isinstance(data, dict):
        raise ConfigError("%s: must be a mapping" % rel)
    problems = []
    unknown = set(data) - {"name", "version", "description", "owner", "rules"}
    if unknown:
        problems.append("%s: unknown key(s) %s" % (rel, ", ".join(sorted(unknown))))
    if data.get("name") != name:
        problems.append("%s: name must be %r (same as its directory)" % (rel, name))
    if data.get("version") != version:
        problems.append("%s: version must be %d (same as its file name)" % (rel, version))
    rules = data.get("rules")
    out_rules = []
    if not isinstance(rules, list) or not rules:
        problems.append("%s: rules must be a non-empty list" % rel)
    else:
        ids = set()
        for i, r in enumerate(rules):
            try:
                n = normalize(r)
            except RuleError as e:
                problems.append("%s: rules[%d]: %s" % (rel, i, e))
                continue
            if n["id"] in ids:
                problems.append("%s: duplicate rule id %r" % (rel, n["id"]))
            ids.add(n["id"])
            out_rules.append(n)
    if problems:
        raise ConfigError(problems)
    return {"path": rel, "sha256": sha256_file(path), "name": name, "version": version,
            "description": str(data.get("description", "")).strip(), "owner": str(data.get("owner", "")),
            "rules": out_rules}


def load_assignments(root: str) -> Dict[str, dict]:
    """Return {project_or_pattern: {"profile": ref, ...metadata}} in file order."""
    path = os.path.join(root, "assignments.yaml")
    data = _read_yaml(path) if os.path.exists(path) else {}
    data = data or {}
    if not isinstance(data, dict):
        raise ConfigError("assignments.yaml: must be a mapping project: profile")
    out, problems = {}, []
    for project, val in data.items():
        project = str(project)
        entry = {"profile": val} if isinstance(val, str) else val
        if not isinstance(entry, dict) or not isinstance(entry.get("profile"), str):
            problems.append("assignments.yaml: %s: value must be name@version or {profile: name@version}" % project)
            continue
        if not PROJECT_PATTERN.match(project) or "/" not in project:
            problems.append("assignments.yaml: %r is not a project path (group/project) or pattern (group/*)" % project)
            continue
        if not REF.match(entry["profile"]):
            problems.append("assignments.yaml: %s: %r is not a profile reference name@version" % (project, entry["profile"]))
            continue
        out[project] = entry
    if problems:
        raise ConfigError(problems)
    return out


# ----------------------------------------------------------------- compile
def compile_bundle(root: str, source_commit: str = "", previous: Optional[dict] = None) -> dict:
    """Validate the whole repository and build the bundle the hook reads.

    previous: the bundle currently installed on GitLab. Every profile version
    it contains must still exist with identical content (immutability)."""
    problems = []
    settings = profiles = assignments = None
    for loader, label in ((load_settings, "settings"), (load_profiles, "profiles"), (load_assignments, "assignments")):
        try:
            value = loader(root)
        except ConfigError as e:
            problems += e.problems
            continue
        except yaml.YAMLError as e:
            problems.append("%s: invalid YAML: %s" % (label, e))
            continue
        if label == "settings":
            settings = value
        elif label == "profiles":
            profiles = value
        else:
            assignments = value
    if profiles is not None and assignments is not None:
        for project, entry in assignments.items():
            if entry["profile"] not in profiles:
                problems.append("assignments.yaml: %s -> %s: no such profile (profiles/%s.yaml)"
                                % (project, entry["profile"], entry["profile"].replace("@", "/")))
    if settings is not None and profiles is not None:
        for ref in settings["deprecated_profiles"]:
            if ref not in profiles:
                problems.append("settings.yaml: deprecated_profiles: %s: no such profile" % ref)
    if profiles is not None and previous:
        problems += immutability_problems(previous, profiles)
    if problems:
        raise ConfigError(problems)
    return {
        "format": BUNDLE_FORMAT,
        "generator": "gitpolicy %s" % __version__,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_commit": source_commit,
        "settings": settings,
        "profiles": {ref: {k: p[k] for k in ("sha256", "description", "owner", "rules")}
                     for ref, p in sorted(profiles.items())},
        "assignments": [{"project": project, "profile": entry["profile"]}
                        for project, entry in assignments.items()],
    }


def immutability_problems(previous: dict, profiles: Dict[str, dict]) -> List[str]:
    out = []
    for ref, old in sorted(previous.get("profiles", {}).items()):
        new = profiles.get(ref)
        if new is None:
            out.append("%s was published and is now missing - published profile versions can never be removed"
                       % ref)
        elif new["sha256"] != old.get("sha256"):
            out.append("%s was published and its file changed (%s) - published versions are immutable, "
                       "create %s@%d instead" % (ref, new["path"], new["name"], _next_version(profiles, new["name"])))
    return out


def _next_version(profiles, name) -> int:
    return max(p["version"] for p in profiles.values() if p["name"] == name) + 1


def git_immutability_problems(root: str, base: str) -> List[str]:
    """Same rule, checked against git history: compared to commit `base`,
    no existing file under profiles/ may be modified, renamed or deleted."""
    out = subprocess.run(["git", "diff", "--name-status", "--no-renames", base, "HEAD", "--", "profiles/"],
                         cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout.decode()
    problems = []
    for line in out.splitlines():
        status, path = line.split("\t", 1)
        if status[0] in "MDT":
            what = {"M": "modified", "D": "deleted", "T": "changed type"}[status[0]]
            problems.append("%s was %s since %s - published profile versions are immutable" % (path, what, base[:12]))
    return problems


def diff_bundles(old: Optional[dict], new: dict) -> List[str]:
    """Human readable summary of what a deploy changes."""
    old = old or {"profiles": {}, "assignments": []}
    lines = []
    for ref in sorted(set(new["profiles"]) - set(old["profiles"])):
        lines.append("+ profile %s" % ref)
    oa = {a["project"]: a["profile"] for a in old["assignments"]}
    na = {a["project"]: a["profile"] for a in new["assignments"]}
    for p in sorted(set(oa) | set(na)):
        if oa.get(p) != na.get(p):
            if p not in oa:
                lines.append("+ %s -> %s" % (p, na[p]))
            elif p not in na:
                lines.append("- %s (was %s)" % (p, oa[p]))
            else:
                lines.append("~ %s: %s -> %s" % (p, oa[p], na[p]))
    if old.get("settings") != new.get("settings") and old.get("settings") is not None:
        lines.append("~ settings changed")
    return lines


# ------------------------------------------------------------------ assign
def assign(root: str, project: str, profile: str, by: str = "", replace: bool = False,
           now: Optional[str] = None) -> Tuple[str, Optional[str]]:
    """Load `profile` for `project` in assignments.yaml.

    Returns (status, previous_profile) with status one of
    "assigned", "replaced", "unchanged". Raises ConfigError if not allowed."""
    project = project.strip().strip("/")
    if project.endswith(".git"):
        project = project[:-4]
    if not PROJECT.match(project):
        raise ConfigError("%r is not a GitLab project path like group/project" % project)
    settings = load_settings(root)
    profiles = load_profiles(root)
    if profile not in profiles:
        raise ConfigError("profile %s does not exist (available: %s)" % (profile, ", ".join(sorted(profiles)) or "none"))
    if profile in settings["deprecated_profiles"]:
        raise ConfigError("profile %s is deprecated and can no longer be loaded" % profile)
    for pat in settings["locked_projects"]:
        if project_matches(project, pat):
            raise ConfigError("project %s is locked (settings.yaml locked_projects: %s) - "
                              "only platform admins can change its profile" % (project, pat))
    entries = load_assignments(root)
    key = next((k for k in entries if k.lower() == project.lower()), None)
    previous = entries[key]["profile"] if key else None
    if previous == profile:
        return "unchanged", previous
    if previous and not replace:
        raise ConfigError("project %s already has profile %s - set REPLACE_EXISTING to switch it to %s"
                          % (project, previous, profile))
    entry = {"profile": profile}
    if by:
        entry["by"] = by
    entry["at"] = now or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if key:
        entries[key] = entry
    else:
        entries[project] = entry
    write_assignments(root, entries)
    return ("replaced" if previous else "assigned"), previous


def unassign(root: str, project: str) -> Optional[str]:
    entries = load_assignments(root)
    key = next((k for k in entries if k.lower() == project.lower()), None)
    if key is None:
        return None
    previous = entries.pop(key)["profile"]
    write_assignments(root, entries)
    return previous


def write_assignments(root: str, entries: Dict[str, dict]) -> None:
    body = yaml.safe_dump({k: entries[k] for k in sorted(entries)}, sort_keys=False,
                          default_flow_style=False, allow_unicode=True) if entries else "{}\n"
    with open(os.path.join(root, "assignments.yaml"), "w", encoding="utf-8") as f:
        f.write(ASSIGNMENTS_HEADER + "\n" + body)


def dump_bundle(bundle: dict) -> str:
    return json.dumps(bundle, indent=2, sort_keys=False, ensure_ascii=False) + "\n"
