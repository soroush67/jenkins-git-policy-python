"""Path and branch pattern matching.

Path patterns follow .gitignore conventions closely enough for policies:
  * ``*`` matches anything except ``/``; ``?`` one character except ``/``
  * ``**`` matches across directories (``**/x``, ``a/**``, ``a/**/b``)
  * a pattern without ``/`` matches the file name in any directory
    (``*.exe`` matches ``bin/tool.exe``)
  * a leading ``/`` anchors the pattern at the repository root

Branch patterns are plain shell globs on the full branch name where ``*``
also matches ``/`` (``release/*`` matches ``release/2024/q1``).
"""
from __future__ import annotations

import fnmatch
import functools
import re


@functools.lru_cache(maxsize=1024)
def _path_regex(pattern: str) -> "re.Pattern[str]":
    anchored = pattern.startswith("/")
    pat = pattern.lstrip("/")
    if pat.endswith("/"):  # "build/" means everything below build
        pat += "**"
    i, out = 0, []
    while i < len(pat):
        c = pat[i]
        if pat.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pat.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[":
            j = pat.find("]", i + 1)
            if j == -1:
                out.append(re.escape(c))
                i += 1
            else:
                body = pat[i + 1:j]
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append("[" + body.replace("\\", "\\\\") + "]")
                i = j + 1
        else:
            out.append(re.escape(c))
            i += 1
    body = "".join(out)
    if "/" not in pattern.strip("/") and not anchored:
        body = "(?:.*/)?" + body  # basename pattern: any directory
    return re.compile("^" + body + "$")


def path_matches(path: str, pattern: str) -> bool:
    return bool(_path_regex(pattern).match(path))


def any_path_matches(path: str, patterns) -> bool:
    return any(path_matches(path, p) for p in patterns)


def branch_matches(branch: str, patterns) -> bool:
    return any(fnmatch.fnmatchcase(branch, p) for p in patterns)


def project_matches(project: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(project.lower(), pattern.lower())
