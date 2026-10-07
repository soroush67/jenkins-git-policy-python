"""Test helpers: real git repositories with the real hook installed.

`server` is a bare repository whose hooks/pre-receive runs
`python -m gitpolicy hook` - the same code path as inside GitLab. Pushes from
the `work` clone carry GL_PROJECT_PATH / GL_USERNAME in the environment like
Gitaly does, and git itself provides the quarantine environment.
"""
import json
import os
import shutil
import subprocess
import sys
import textwrap

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_CONFIG = os.path.join(ROOT, "policy-config")
sys.path.insert(0, ROOT)

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test User", "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test User", "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_CONFIG_NOSYSTEM": "1", "HOME": "/nonexistent",
}


def git(cwd, *args, env=None, check=True, input=None):
    e = dict(os.environ)
    e.update(GIT_ENV)
    e.pop("GL_PROJECT_PATH", None)
    if env:
        e.update(env)
    p = subprocess.run(["git", *args], cwd=cwd, env=e, input=input,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if check and p.returncode != 0:
        raise AssertionError("git %s failed:\n%s\n%s" % (" ".join(args), p.stdout, p.stderr))
    return p


class Lab:
    """A bare 'server' repo + a working clone + a bundle to edit."""

    def __init__(self, tmp):
        self.tmp = str(tmp)
        self.server = os.path.join(self.tmp, "server.git")
        self.work = os.path.join(self.tmp, "work")
        self.bundle_path = os.path.join(self.tmp, "bundle.json")
        self.audit = os.path.join(self.tmp, "audit.log")
        self.project = "demo/app"
        self.user = "dev1"
        git(self.tmp, "init", "-q", "--bare", "-b", "main", self.server)
        hook = os.path.join(self.server, "hooks", "pre-receive")
        with open(hook, "w") as f:
            f.write("#!/bin/sh\nexec %s -m gitpolicy hook\n" % sys.executable)
        os.chmod(hook, 0o755)
        git(self.tmp, "clone", "-q", self.server, self.work)
        git(self.work, "symbolic-ref", "HEAD", "refs/heads/main")
        self.profiles = {}
        self.assignments = []
        self.settings = {"fail_mode": "closed", "break_glass_users": [], "max_commits": 10000}

    # ------------------------------------------------------------- policy
    def profile(self, ref, rules, assign=True):
        from gitpolicy.rules import normalize
        self.profiles[ref] = {"sha256": "x", "description": "", "rules": [normalize(r) for r in rules]}
        if assign:
            self.assign(self.project, ref)
        self.write_bundle()

    def assign(self, project, ref):
        self.assignments = [a for a in self.assignments if a["project"] != project]
        self.assignments.append({"project": project, "profile": ref})
        self.write_bundle()

    def write_bundle(self):
        with open(self.bundle_path, "w") as f:
            json.dump({"format": 1, "source_commit": "test", "settings": self.settings,
                       "profiles": self.profiles, "assignments": self.assignments}, f)

    # ---------------------------------------------------------------- git
    def write(self, path, content):
        full = os.path.join(self.work, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        mode = "wb" if isinstance(content, bytes) else "w"
        with open(full, mode) as f:
            f.write(content)

    def commit(self, msg="chore: update", **files):
        for path, content in files.items():
            self.write(path.replace("__", "/"), content)
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "--allow-empty", "-m", msg)
        return git(self.work, "rev-parse", "HEAD").stdout.strip()

    def rm(self, path, msg="chore: remove"):
        git(self.work, "rm", "-q", path)
        git(self.work, "commit", "-q", "-m", msg)

    def push(self, *refspecs, user=None, protocol="ssh", project=None, force=False):
        env = {"GL_PROJECT_PATH": self.project if project is None else project,
               "GL_USERNAME": user or self.user, "GL_PROTOCOL": protocol,
               "GITPOLICY_BUNDLE": self.bundle_path, "GITPOLICY_AUDIT_LOG": self.audit,
               "PYTHONPATH": ROOT}
        args = ["push", "--porcelain"] + (["--force"] if force else []) + ["origin"] + list(refspecs or ["HEAD:main"])
        p = git(self.work, *args, env=env, check=False)
        return Push(p)

    def audit_records(self):
        with open(self.audit) as f:
            return [json.loads(line) for line in f]


class Push:
    def __init__(self, p):
        self.ok = p.returncode == 0
        self.output = p.stdout + p.stderr

    def __repr__(self):
        return "Push(ok=%s)\n%s" % (self.ok, textwrap.indent(self.output, "  "))


@pytest.fixture
def lab(tmp_path):
    return Lab(tmp_path)


@pytest.fixture
def config_repo(tmp_path):
    """A copy of the sample policy-config repository, as a git repo."""
    dst = tmp_path / "policy-config"
    shutil.copytree(SAMPLE_CONFIG, str(dst))
    git(str(dst), "init", "-q", "-b", "main")
    git(str(dst), "add", "-A")
    git(str(dst), "commit", "-q", "-m", "initial")
    return str(dst)


BINARY = b"\x7fELF\x02\x01\x01\x00" + bytes(range(256)) * 4
