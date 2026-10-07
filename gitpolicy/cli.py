"""Command line: `python3 -m gitpolicy <command>`.

Commands used by Jenkins (need PyYAML):
  validate, compile, diff, assign, unassign, list-profiles, show, describe-rules
Commands used on the GitLab server (standard library only):
  hook, check, doctor
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__


def _config():
    from . import config  # imported lazily: needs PyYAML
    return config


def _fail(problems) -> int:
    for p in problems:
        print("ERROR: " + p, file=sys.stderr)
    return 1


def _load_json(path):
    if not path or not os.path.exists(path) or os.path.getsize(path) == 0:
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------ control plane
def cmd_validate(a) -> int:
    c = _config()
    problems = []
    try:
        bundle = c.compile_bundle(a.root, previous=_load_json(a.previous))
    except c.ConfigError as e:
        problems += e.problems
        bundle = None
    if a.git_base:
        problems += c.git_immutability_problems(a.root, a.git_base)
    if problems:
        return _fail(problems)
    print("OK: %d profile version(s), %d assignment(s)" % (len(bundle["profiles"]), len(bundle["assignments"])))
    return 0


def cmd_compile(a) -> int:
    c = _config()
    previous = _load_json(a.previous)
    try:
        bundle = c.compile_bundle(a.root, source_commit=a.source_commit, previous=previous)
    except c.ConfigError as e:
        return _fail(e.problems)
    with open(a.output, "w", encoding="utf-8") as f:
        f.write(c.dump_bundle(bundle))
    print("compiled %s: %d profile version(s), %d assignment(s)" % (a.output, len(bundle["profiles"]),
                                                                   len(bundle["assignments"])))
    for line in c.diff_bundles(previous, bundle) or ["(no changes compared to the installed bundle)"]:
        print("  " + line)
    return 0


def cmd_diff(a) -> int:
    c = _config()
    for line in c.diff_bundles(_load_json(a.old), _load_json(a.new)) or ["(no changes)"]:
        print(line)
    return 0


def cmd_assign(a) -> int:
    c = _config()
    try:
        status, previous = c.assign(a.root, a.project, a.profile, by=a.by, replace=a.replace)
    except c.ConfigError as e:
        return _fail(e.problems)
    msg = {"assigned": "project %s: profile %s loaded" % (a.project, a.profile),
           "replaced": "project %s: profile %s replaced by %s" % (a.project, previous, a.profile),
           "unchanged": "project %s already has profile %s - nothing to do" % (a.project, a.profile)}[status]
    print(msg)
    if a.status_file:
        with open(a.status_file, "w") as f:
            f.write(status + "\n")
    return 0


def cmd_unassign(a) -> int:
    c = _config()
    previous = c.unassign(a.root, a.project)
    print("project %s: profile %s removed" % (a.project, previous) if previous
          else "project %s had no profile" % a.project)
    return 0


def cmd_list_profiles(a) -> int:
    c = _config()
    profiles = c.load_profiles(a.root)
    deprecated = set(c.load_settings(a.root)["deprecated_profiles"]) if a.loadable else set()
    for ref in sorted(profiles, key=lambda r: (r.split("@")[0], -int(r.split("@")[1]))):
        if ref in deprecated:
            continue
        print(ref + ("\t" + profiles[ref]["description"].splitlines()[0] if a.long and profiles[ref]["description"] else ""))
    return 0


def cmd_show(a) -> int:
    c = _config()
    profiles = c.load_profiles(a.root)
    assignments = c.load_assignments(a.root)
    settings = c.load_settings(a.root)
    if a.project:
        from .engine import Bundle
        bundle = Bundle(c.compile_bundle(a.root))
        ref, match = bundle.resolve(a.project)
        if not ref:
            print("project %s: no profile loaded - pushes are not checked" % a.project)
            return 0
        meta = assignments.get(match, {})
        print("project %s: profile %s%s" % (a.project, ref, " (via pattern %s)" % match if match != a.project else ""))
        if meta.get("by"):
            print("  loaded by %s at %s" % (meta["by"], meta.get("at", "?")))
        _print_profile(ref, profiles[ref])
        return 0
    print("Profiles:")
    for ref in sorted(profiles):
        flag = "  (deprecated)" if ref in settings["deprecated_profiles"] else ""
        print("  %-28s %s%s" % (ref, (profiles[ref]["description"].splitlines() or [""])[0], flag))
    print("\nAssignments:")
    for project, e in assignments.items():
        print("  %-28s %s%s" % (project, e["profile"], ("   by %s" % e["by"]) if e.get("by") else ""))
    if not assignments:
        print("  (none)")
    return 0


def _print_profile(ref, p):
    print("  %s" % " ".join(p["description"].split()))
    for r in p["rules"]:
        params = {k: v for k, v in r.items() if k not in ("id", "type", "action", "branches", "message")}
        print("  - %-22s %-21s %-5s branches=%s %s" % (r["id"], r["type"], r["action"], ",".join(r["branches"]),
                                                      json.dumps(params, ensure_ascii=False) if params else ""))


def cmd_describe_rules(a) -> int:
    from .rules import RULE_TYPES
    for name, cls in sorted(RULE_TYPES.items()):
        print("%s\n    %s" % (name, cls.DESCRIPTION))
        for p, (kind, req, default) in cls.PARAMS.items():
            print("    %-18s %-10s %s" % (p, kind, "required" if req else "default: %s" % json.dumps(default)))
    return 0


def cmd_gitlab_check(a) -> int:
    from .gitlab import GitLabError, check_project
    try:
        path = check_project(a.project, a.user, a.min_level)
    except GitLabError as e:
        return _fail([str(e)])
    print(path)
    return 0


# ------------------------------------------------------------- GitLab side
def cmd_hook(a) -> int:
    from .hook import main
    return main()


def cmd_check(a) -> int:
    """Dry run the engine on a local repository (no push needed)."""
    from .engine import Bundle, RefUpdate, evaluate
    from .gitrepo import ZERO, Repo
    from .hook import _fmt
    bundle = Bundle.load(a.bundle)
    with Repo(a.repo) as repo:
        new = repo.resolve(a.new)
        old = repo.resolve(a.old) if a.old else ZERO
        if not new:
            return _fail(["cannot resolve %s" % a.new])
        ref = a.ref if a.ref.startswith("refs/") else "refs/heads/" + a.ref
        res = evaluate(bundle, repo, a.project, [RefUpdate(old, new, ref)])
    if res.profile is None:
        print("project %s has no profile - would be ALLOWED" % a.project)
        return 0
    print("profile %s: %d commit(s), %d file change(s) checked" % (res.profile, res.checked_commits, res.checked_files))
    for n in res.notes:
        print("note: " + n)
    for v in res.violations:
        print("%s %s" % (v.action.upper(), _fmt(v)))
    print("=> %s" % ("ALLOWED" if res.allowed else "REJECTED"))
    return 0 if res.allowed else 1


def cmd_doctor(a) -> int:
    from .engine import Bundle, BundleError
    from .gitrepo import GitError, find_git
    ok = True
    print("gitpolicy %s, python %s" % (__version__, sys.version.split()[0]))
    try:
        print("git: %s" % find_git())
    except GitError as e:
        ok = False
        print("git: MISSING (%s)" % e)
    if os.path.exists(a.bundle):
        try:
            b = Bundle.load(a.bundle)
            from .rules import build
            for ref, prof in b.profiles.items():
                for r in prof["rules"]:
                    try:
                        build(r)
                    except Exception as e:  # noqa: BLE001
                        raise BundleError("%s rule %s: %s" % (ref, r.get("id"), e))
            print("bundle: %s (source %s, %d profiles, %d assignments, generated %s)" % (
                a.bundle, b.data.get("source_commit", "")[:12] or "-", len(b.profiles), len(b.assignments),
                b.data.get("generated_at")))
        except BundleError as e:
            ok = False
            print("bundle: BROKEN: %s" % e)
    else:
        print("bundle: none at %s (hook allows everything)" % a.bundle)
    if a.hook:
        if os.access(a.hook, os.X_OK):
            print("hook: %s" % a.hook)
        else:
            ok = False
            print("hook: MISSING or not executable: %s" % a.hook)
    print("=> %s" % ("OK" if ok else "PROBLEMS FOUND"))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="gitpolicy", description="GitLab policy profiles (gitpolicy %s)" % __version__)
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("validate", help="validate a policy repository")
    p.add_argument("root")
    p.add_argument("--previous", help="installed bundle.json: its profile versions must be unchanged")
    p.add_argument("--git-base", help="commit to compare profiles/ against (immutability via git history)")
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("compile", help="validate and compile a policy repository into bundle.json")
    p.add_argument("root")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--previous")
    p.add_argument("--source-commit", default="")
    p.set_defaults(fn=cmd_compile)

    p = sub.add_parser("diff", help="what changes between two bundles")
    p.add_argument("--old")
    p.add_argument("--new", required=True)
    p.set_defaults(fn=cmd_diff)

    p = sub.add_parser("assign", help="load a profile for a project (edits assignments.yaml)")
    p.add_argument("root")
    p.add_argument("--project", required=True)
    p.add_argument("--profile", required=True)
    p.add_argument("--by", default="")
    p.add_argument("--replace", action="store_true", help="allow switching an existing assignment")
    p.add_argument("--status-file")
    p.set_defaults(fn=cmd_assign)

    p = sub.add_parser("unassign", help="remove a project's profile (admin)")
    p.add_argument("root")
    p.add_argument("--project", required=True)
    p.set_defaults(fn=cmd_unassign)

    p = sub.add_parser("list-profiles", help="list profile references, newest version first")
    p.add_argument("root")
    p.add_argument("--loadable", action="store_true", help="hide deprecated versions")
    p.add_argument("--long", action="store_true")
    p.set_defaults(fn=cmd_list_profiles)

    p = sub.add_parser("show", help="show profiles and assignments, or one project's policy")
    p.add_argument("root")
    p.add_argument("--project")
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("describe-rules", help="list the rule types and their parameters")
    p.set_defaults(fn=cmd_describe_rules)

    p = sub.add_parser("gitlab-check", help="project exists in GitLab (and user has a role in it)")
    p.add_argument("--project", required=True)
    p.add_argument("--user", default="")
    p.add_argument("--min-level", choices=["", "guest", "reporter", "developer", "maintainer", "owner"], default="")
    p.set_defaults(fn=cmd_gitlab_check)

    p = sub.add_parser("hook", help="pre-receive hook entry point (reads stdin)")
    p.set_defaults(fn=cmd_hook)

    p = sub.add_parser("check", help="dry-run a policy against a local repository")
    p.add_argument("--bundle", required=True)
    p.add_argument("--project", required=True)
    p.add_argument("--repo", default=".")
    p.add_argument("--ref", required=True, help="target branch, e.g. main")
    p.add_argument("--old", help="current tip of the target branch (omit for a new branch)")
    p.add_argument("--new", required=True, help="commit to push/merge, e.g. feature/x")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("doctor", help="check the installation on the GitLab server")
    p.add_argument("--bundle", default="/etc/gitpolicy/bundle.json")
    p.add_argument("--hook")
    p.set_defaults(fn=cmd_doctor)

    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except Exception as e:  # ConfigError from loaders, YAML errors ...
        if type(e).__name__ in ("ConfigError", "YAMLError", "ScannerError", "ParserError") or hasattr(e, "problems"):
            return _fail(getattr(e, "problems", [str(e)]))
        raise


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
