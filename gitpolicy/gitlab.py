"""Minimal GitLab REST client used by the Jenkins jobs (standard library only).

Environment:
  GITLAB_URL     e.g. http://gpp-gitlab or https://gitlab.company.com
  GITLAB_TOKEN   personal/service access token with read_api (admin, or a
                 member of every group whose projects may load profiles)
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

LEVELS = {"guest": 10, "reporter": 20, "developer": 30, "maintainer": 40, "owner": 50}


class GitLabError(RuntimeError):
    pass


class GitLab:
    def __init__(self, url=None, token=None, timeout=20):
        self.url = (url or os.environ.get("GITLAB_URL", "")).rstrip("/")
        self.token = token or os.environ.get("GITLAB_TOKEN", "")
        self.timeout = timeout
        if not self.url or not self.token:
            raise GitLabError("GITLAB_URL and GITLAB_TOKEN must be set")

    def get(self, path: str, params=None):
        url = "%s/api/v4%s" % (self.url, path)
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"PRIVATE-TOKEN": self.token})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise GitLabError("GitLab API %s: HTTP %d" % (path, e.code))
        except urllib.error.URLError as e:
            raise GitLabError("GitLab API unreachable (%s): %s" % (self.url, e.reason))

    def project(self, path: str):
        return self.get("/projects/" + urllib.parse.quote(path, safe=""))

    def user_access_level(self, project_id: int, username: str) -> int:
        """Effective access level of `username` (inherited group membership included)."""
        users = self.get("/users", {"username": username}) or []
        if not users:
            return 0
        member = self.get("/projects/%d/members/all/%d" % (project_id, users[0]["id"]))
        level = member.get("access_level", 0) if member else 0
        if users[0].get("is_admin"):
            level = max(level, LEVELS["owner"])
        return level


def check_project(path: str, username: str = "", min_level: str = "") -> str:
    """Raise GitLabError unless the project exists (and the user has the role).
    Returns the canonical path_with_namespace."""
    gl = GitLab()
    p = gl.project(path)
    if not p:
        raise GitLabError("GitLab project %s not found" % path)
    if min_level:
        need = LEVELS[min_level]
        have = gl.user_access_level(p["id"], username)
        if have < need:
            raise GitLabError("%s is not %s (or higher) of %s in GitLab - ask a maintainer of the project"
                              % (username, min_level, p["path_with_namespace"]))
    return p["path_with_namespace"]
