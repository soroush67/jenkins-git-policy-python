"""pre-receive hook entry point (runs inside GitLab / Gitaly).

GitLab passes the project and the user in the environment:
  GL_PROJECT_PATH  group/project   (the only trusted project identity)
  GL_USERNAME      who pushes, or who clicked "Merge" in the web UI
  GL_PROTOCOL      ssh | http | web
Ref updates arrive on stdin as "<old> <new> <ref>" lines.

Exit code 0 accepts the push, 1 rejects it. Lines prefixed with
"GL-HOOK-ERR: " are what GitLab shows in the web UI (e.g. when a merge
request merge is rejected); for command line pushes git prints everything as
"remote: ...".
"""
from __future__ import annotations

import datetime
import json
import os
import sys
import time

from . import __version__
from .engine import Bundle, BundleError, RefUpdate, evaluate
from .gitrepo import Repo, parse_ref_updates

DEFAULT_BUNDLE = "/etc/gitpolicy/bundle.json"
DEFAULT_AUDIT = "/var/log/gitlab/gitpolicy/audit.log"
MAX_LINES = 25


def _emit(lines, web: bool) -> None:
    for line in lines:
        sys.stderr.write(("GL-HOOK-ERR: " + line if web else line) + "\n")
    sys.stderr.flush()


def _audit(path: str, record: dict) -> None:
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        pass  # auditing must never break pushes


def main(stdin_text=None, env=None) -> int:
    env = os.environ if env is None else env
    started = time.time()
    project = env.get("GL_PROJECT_PATH", "")
    user = env.get("GL_USERNAME", "")
    web = env.get("GL_PROTOCOL") == "web"
    bundle_path = env.get("GITPOLICY_BUNDLE", DEFAULT_BUNDLE)
    audit_path = env.get("GITPOLICY_AUDIT_LOG", DEFAULT_AUDIT)
    text = sys.stdin.read() if stdin_text is None else stdin_text
    updates = [RefUpdate(*u) for u in parse_ref_updates(text)]
    record = {"ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "project": project,
              "user": user, "protocol": env.get("GL_PROTOCOL", ""),
              "refs": [[u.old[:12], u.new[:12], u.ref] for u in updates]}

    if not project:
        # Not a GitLab push (e.g. a wiki or a manual push on the server).
        return 0
    if not os.path.exists(bundle_path):
        return 0  # gitpolicy installed but no policy deployed yet

    settings = {}
    try:
        bundle = Bundle.load(bundle_path)
        settings = bundle.settings
        record["bundle"] = bundle.data.get("source_commit", "")[:12]
        if user and user in settings.get("break_glass_users", []):
            profile, _ = bundle.resolve(project)
            if profile:
                record.update(decision="bypass", profile=profile)
                _audit(audit_path, record)
                _emit(["gitpolicy: policy %s BYPASSED by break-glass user %s (audited)" % (profile, user)], False)
            return 0
        with Repo(env.get("GITPOLICY_REPO", ".")) as repo:
            result = evaluate(bundle, repo, project, updates)
    except Exception as e:  # noqa: BLE001 - the decision must be explicit
        fail_open = settings.get("fail_mode") == "open"
        record.update(decision="error-allow" if fail_open else "error-reject", error=str(e))
        _audit(audit_path, record)
        if fail_open:
            _emit(["gitpolicy: internal error, push allowed (fail_mode: open): %s" % e], False)
            return 0
        _emit(["gitpolicy: internal error, push rejected (fail_mode: closed): %s" % e,
               "gitpolicy: contact the platform team"], web)
        return 1

    if result.profile is None:
        return 0

    record.update(profile=result.profile, commits=result.checked_commits, files=result.checked_files,
                  ms=int((time.time() - started) * 1000),
                  violations=[v.as_dict() for v in result.violations])
    record["decision"] = "allow" if result.allowed else "reject"
    _audit(audit_path, record)

    for note in result.notes:
        _emit(["gitpolicy: note: " + note], False)
    if result.warnings:
        _emit(["gitpolicy: WARNING (profile %s) - push accepted, but please fix:" % result.profile]
              + ["  " + _fmt(v) for v in result.warnings[:MAX_LINES]], False)
    if result.allowed:
        return 0

    blocked = result.blocked
    lines = ["gitpolicy: push REJECTED by profile %s (%d violation%s)"
             % (result.profile, len(blocked), "" if len(blocked) == 1 else "s")]
    lines += ["  " + _fmt(v) for v in blocked[:MAX_LINES]]
    if len(blocked) > MAX_LINES:
        lines.append("  ... and %d more" % (len(blocked) - MAX_LINES))
    hints = sorted({"[%s] %s" % (v.rule_id, v.hint) for v in blocked if v.hint})
    lines += ["  hint: " + h for h in hints]
    lines.append("gitpolicy %s - remove the offending content from the history (e.g. git rebase -i) and push again" % __version__)
    _emit(lines, web)
    return 1


def _fmt(v) -> str:
    where = v.path or ""
    if v.commit:
        where = ("%s @ %s" % (where, v.commit[:10])) if where else "commit " + v.commit[:10]
    branch = v.ref[len("refs/heads/"):] if v.ref.startswith("refs/heads/") else v.ref
    return "[%s] %s: %s (branch %s)" % (v.rule_id, where or "-", v.text, branch)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
