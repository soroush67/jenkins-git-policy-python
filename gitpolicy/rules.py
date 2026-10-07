"""Policy rule types.

Every rule in a profile has these common fields:

    id:       unique name inside the profile (shown to the user on rejection)
    type:     one of RULE_TYPES below
    action:   block (default) | warn
    branches: target-branch globs the rule applies to (default ["*"])
    message:  optional extra text shown to the user when the rule fires

and type-specific parameters declared in each class's PARAMS:
    name -> (kind, required, default)
kind is one of: str, int, bool, size, list, regex, regex_list.

`normalize()` validates a rule dict and returns the canonical form that goes
into the compiled bundle; the hook builds rule objects from that form.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from .globs import any_path_matches, branch_matches
from .gitrepo import Change, Commit

ACTIONS = ("block", "warn")
_SIZE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([KMG]?i?B?)?\s*$", re.I)
_UNITS = {"": 1, "B": 1, "K": 1024, "KB": 1024, "KIB": 1024, "M": 1024 ** 2, "MB": 1024 ** 2,
          "MIB": 1024 ** 2, "G": 1024 ** 3, "GB": 1024 ** 3, "GIB": 1024 ** 3}


class RuleError(ValueError):
    pass


def parse_size(value) -> int:
    if isinstance(value, bool):
        raise RuleError("size must be a number or a string like 5MB")
    if isinstance(value, int):
        return value
    m = _SIZE.match(str(value))
    if not m or (m.group(2) or "").upper() not in _UNITS:
        raise RuleError("invalid size %r (use e.g. 500KB, 5MB, 1GB)" % value)
    return int(float(m.group(1)) * _UNITS[(m.group(2) or "").upper()])


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0
    return str(n)  # pragma: no cover


class Violation:
    __slots__ = ("rule_id", "rule_type", "action", "ref", "text", "commit", "path", "hint")

    def __init__(self, rule, ref: str, text: str, commit: Optional[str] = None,
                 path: Optional[str] = None):
        self.rule_id = rule.id
        self.rule_type = rule.TYPE
        self.action = rule.action
        self.ref = ref
        self.text = text
        self.commit = commit
        self.path = path
        self.hint = rule.message

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__ if getattr(self, k) is not None}

    def __repr__(self):  # pragma: no cover - debugging aid
        return "Violation(%s, %s, %s)" % (self.rule_id, self.path or self.commit, self.text)


# ---------------------------------------------------------------- base class
class Rule:
    TYPE = ""
    DESCRIPTION = ""
    PARAMS: Dict[str, tuple] = {}
    # Which engine passes the rule takes part in.
    REF = False       # check_ref(update)       - once per pushed ref
    COMMIT = False    # check_commit(commit)    - once per new commit
    CHANGE = False    # check_change(change)    - once per changed file
    NEEDS_CONTENT = False

    def __init__(self, spec: dict):
        self.id = spec["id"]
        self.action = spec.get("action", "block")
        self.branches = spec.get("branches", ["*"])
        self.message = spec.get("message")
        self.p = {k: spec[k] for k in self.PARAMS if k in spec}
        self._compile()

    def _compile(self) -> None:
        pass

    def applies_to(self, branch: str) -> bool:
        return branch_matches(branch, self.branches)

    def v(self, update, text, commit=None, path=None) -> Violation:
        return Violation(self, update.ref, text, commit, path)

    # engine callbacks; return a list of violations
    def check_ref(self, ctx, update) -> List[Violation]:
        return []

    def check_commit(self, ctx, update, commit: Commit) -> List[Violation]:
        return []

    def check_change(self, ctx, update, change: Change) -> List[Violation]:
        return []


# ------------------------------------------------------------------ content
class BinaryFiles(Rule):
    TYPE = "binary_files"
    DESCRIPTION = "Reject binary files (git's own heuristic: a NUL byte in the first bytes, plus known binary magic numbers)."
    PARAMS = {
        "allow_paths": ("list", False, []),
        "allow_extensions": ("list", False, []),
        "scan_bytes": ("int", False, 8000),
    }
    CHANGE = True
    NEEDS_CONTENT = True
    MAGIC = (b"\x7fELF", b"PK\x03\x04", b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"%PDF",
             b"\xca\xfe\xba\xbe", b"\xcf\xfa\xed\xfe", b"\x1f\x8b", b"7z\xbc\xaf", b"Rar!")

    def _compile(self):
        self.allow_ext = tuple(e.lower() if e.startswith(".") else "." + e.lower()
                               for e in self.p.get("allow_extensions", []))

    def check_change(self, ctx, update, ch):
        if ch.status == "D" or not ch.is_file:
            return []
        if any_path_matches(ch.path, self.p.get("allow_paths", [])):
            return []
        if self.allow_ext and ch.path.lower().endswith(self.allow_ext):
            return []
        head = ctx.repo.blob_head(ch.new_blob, self.p.get("scan_bytes", 8000))
        if b"\0" in head or head.startswith(self.MAGIC) or _is_pe(head):
            return [self.v(update, "binary file (%s)" % human_size(ctx.repo.blob_size(ch.new_blob)),
                           ch.commit, ch.path)]
        return []


def _is_pe(head: bytes) -> bool:
    # "MZ" alone is too common as the start of a text file; a real Windows
    # executable also has the PE header offset at 0x3c.
    if not head.startswith(b"MZ") or len(head) < 0x40:
        return False
    off = int.from_bytes(head[0x3c:0x40], "little")
    return head[off:off + 4] == b"PE\0\0"


class ForbiddenExtensions(Rule):
    TYPE = "forbidden_extensions"
    DESCRIPTION = "Reject files by extension (case-insensitive), e.g. .exe .dll .jar."
    PARAMS = {"extensions": ("list", True, None), "allow_paths": ("list", False, [])}
    CHANGE = True

    def _compile(self):
        self.ext = tuple(e.lower() if e.startswith(".") else "." + e.lower() for e in self.p["extensions"])

    def check_change(self, ctx, update, ch):
        if ch.status == "D" or ch.new_mode == "160000":
            return []
        if ch.path.lower().endswith(self.ext) and not any_path_matches(ch.path, self.p.get("allow_paths", [])):
            return [self.v(update, "forbidden file extension", ch.commit, ch.path)]
        return []


class ForbiddenPaths(Rule):
    TYPE = "forbidden_paths"
    DESCRIPTION = "Reject files whose path matches a pattern, e.g. .env, **/*.pem, secrets/."
    PARAMS = {"patterns": ("list", True, None), "allow_paths": ("list", False, [])}
    CHANGE = True

    def check_change(self, ctx, update, ch):
        if ch.status == "D":
            return []
        if any_path_matches(ch.path, self.p["patterns"]) and not any_path_matches(ch.path, self.p.get("allow_paths", [])):
            return [self.v(update, "forbidden path", ch.commit, ch.path)]
        return []


class MaxFileSize(Rule):
    TYPE = "max_file_size"
    DESCRIPTION = "Reject files larger than max_size (e.g. 5MB)."
    PARAMS = {"max_size": ("size", True, None), "allow_paths": ("list", False, [])}
    CHANGE = True

    def check_change(self, ctx, update, ch):
        if ch.status == "D" or not ch.is_file or any_path_matches(ch.path, self.p.get("allow_paths", [])):
            return []
        size = ctx.repo.blob_size(ch.new_blob)
        if size > self.p["max_size"]:
            return [self.v(update, "file is %s, limit is %s" % (human_size(size), human_size(self.p["max_size"])),
                           ch.commit, ch.path)]
        return []


BUILTIN_SECRETS = {
    "private-key": r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY",
    "aws-access-key-id": r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
    "gitlab-token": r"\bglpat-[0-9A-Za-z_\-]{20,}",
    "github-token": r"\bgh[pousr]_[0-9A-Za-z]{36,}",
    "slack-token": r"\bxox[abprs]-[0-9A-Za-z-]{10,}",
    "password-assignment": r"(?i)\b(?:password|passwd|pwd)\s*[:=]\s*['\"][^'\"\s]{6,}['\"]",
}


class SecretPatterns(Rule):
    TYPE = "secret_patterns"
    DESCRIPTION = "Reject text files containing secrets (built-in patterns and/or your own regexes)."
    PARAMS = {
        "builtin": ("bool", False, True),
        "patterns": ("regex_map", False, {}),
        "allow_paths": ("list", False, []),
        "max_scan_size": ("size", False, 1024 * 1024),
    }
    CHANGE = True
    NEEDS_CONTENT = True

    def _compile(self):
        pats = dict(BUILTIN_SECRETS) if self.p.get("builtin", True) else {}
        pats.update(self.p.get("patterns", {}))
        self.regexes = [(name, re.compile(rx.encode())) for name, rx in pats.items()]

    def check_change(self, ctx, update, ch):
        if ch.status == "D" or not ch.is_file or any_path_matches(ch.path, self.p.get("allow_paths", [])):
            return []
        limit = self.p.get("max_scan_size", 1024 * 1024)
        if ctx.repo.blob_size(ch.new_blob) > limit:
            return []
        data = ctx.repo.blob_head(ch.new_blob, limit)
        if b"\0" in data[:8000]:
            return []  # binary - other rules deal with it
        for name, rx in self.regexes:
            m = rx.search(data)
            if m:
                line = data.count(b"\n", 0, m.start()) + 1
                return [self.v(update, "looks like a secret (%s) on line %d" % (name, line), ch.commit, ch.path)]
        return []


class ImmutablePaths(Rule):
    TYPE = "immutable_paths"
    DESCRIPTION = "Files matching the patterns may be added but never modified, renamed or deleted afterwards."
    PARAMS = {"patterns": ("list", True, None)}
    CHANGE = True

    def check_change(self, ctx, update, ch):
        if ch.status in ("M", "D", "T") and any_path_matches(ch.path, self.p["patterns"]):
            what = {"M": "modified", "D": "deleted or renamed", "T": "type changed"}[ch.status]
            return [self.v(update, "immutable file %s" % what, ch.commit, ch.path)]
        return []


# ------------------------------------------------------------------ commits
class CommitMessage(Rule):
    TYPE = "commit_message"
    DESCRIPTION = "Every new commit's message must match a regex (first line by default)."
    PARAMS = {"pattern": ("regex", True, None), "subject_only": ("bool", False, True),
              "skip_merges": ("bool", False, True)}
    COMMIT = True

    def _compile(self):
        self.rx = re.compile(self.p["pattern"])

    def check_commit(self, ctx, update, c):
        if c.is_merge and self.p.get("skip_merges", True):
            return []
        text = c.subject if self.p.get("subject_only", True) else c.message
        if not self.rx.search(text):
            return [self.v(update, "commit message %r does not match %s" % (c.subject[:72], self.p["pattern"]), c.sha)]
        return []


class AuthorEmail(Rule):
    TYPE = "author_email"
    DESCRIPTION = "Commit author e-mail must match a regex, e.g. company domain only."
    PARAMS = {"pattern": ("regex", True, None), "skip_merges": ("bool", False, True)}
    COMMIT = True

    def _compile(self):
        self.rx = re.compile(self.p["pattern"])

    def check_commit(self, ctx, update, c):
        if c.is_merge and self.p.get("skip_merges", True):
            return []
        if not self.rx.search(c.author_email):
            return [self.v(update, "author e-mail %r not allowed" % c.author_email, c.sha)]
        return []


# --------------------------------------------------------------------- refs
class BranchName(Rule):
    TYPE = "branch_name"
    DESCRIPTION = "New branches must be named after a regex. (`branches` is ignored: it applies to every new branch.)"
    PARAMS = {"pattern": ("regex", True, None)}
    REF = True

    def _compile(self):
        self.rx = re.compile(self.p["pattern"])

    def applies_to(self, branch):
        return True

    def check_ref(self, ctx, update):
        if update.is_create and not self.rx.search(update.branch):
            return [self.v(update, "branch name %r does not match %s" % (update.branch, self.p["pattern"]))]
        return []


class NoForcePush(Rule):
    TYPE = "no_force_push"
    DESCRIPTION = "Reject non fast-forward updates (history rewrite) of the matching branches."
    REF = True

    def check_ref(self, ctx, update):
        if update.is_update and not ctx.repo.is_ancestor(update.old, update.new):
            return [self.v(update, "force push (history rewrite) is not allowed")]
        return []


class NoBranchDelete(Rule):
    TYPE = "no_branch_delete"
    DESCRIPTION = "Reject deletion of the matching branches."
    REF = True

    def check_ref(self, ctx, update):
        if update.is_delete:
            return [self.v(update, "deleting this branch is not allowed")]
        return []


RULE_TYPES = {cls.TYPE: cls for cls in (
    BinaryFiles, ForbiddenExtensions, ForbiddenPaths, MaxFileSize, SecretPatterns, ImmutablePaths,
    CommitMessage, AuthorEmail, BranchName, NoForcePush, NoBranchDelete)}

COMMON = {"id", "type", "action", "branches", "message"}
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def _check_kind(rule_id: str, name: str, kind: str, value):
    where = "rule %r: %s" % (rule_id, name)
    if kind == "str":
        if not isinstance(value, str):
            raise RuleError("%s must be a string" % where)
        return value
    if kind == "int":
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise RuleError("%s must be a positive integer" % where)
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            raise RuleError("%s must be true or false" % where)
        return value
    if kind == "size":
        try:
            n = parse_size(value)
        except RuleError as e:
            raise RuleError("%s: %s" % (where, e))
        if n <= 0:
            raise RuleError("%s must be > 0" % where)
        return n
    if kind == "list":
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list) or not all(isinstance(x, str) and x for x in value):
            raise RuleError("%s must be a list of strings" % where)
        return list(value)
    if kind == "regex":
        if not isinstance(value, str):
            raise RuleError("%s must be a regex string" % where)
        try:
            re.compile(value)
        except re.error as e:
            raise RuleError("%s: invalid regex: %s" % (where, e))
        return value
    if kind == "regex_map":
        if not isinstance(value, dict):
            raise RuleError("%s must be a mapping name: regex" % where)
        out = {}
        for k, rx in value.items():
            out[str(k)] = _check_kind(rule_id, "%s.%s" % (name, k), "regex", rx)
        return out
    raise AssertionError(kind)  # pragma: no cover


def normalize(spec) -> dict:
    """Validate one rule definition from a profile; return its canonical form."""
    if not isinstance(spec, dict):
        raise RuleError("each rule must be a mapping")
    rid = spec.get("id")
    if not isinstance(rid, str) or not _ID.match(rid):
        raise RuleError("rule id %r invalid (lowercase letters, digits, . _ -)" % (rid,))
    rtype = spec.get("type")
    cls = RULE_TYPES.get(rtype)
    if cls is None:
        raise RuleError("rule %r: unknown type %r (known: %s)" % (rid, rtype, ", ".join(sorted(RULE_TYPES))))
    unknown = set(spec) - COMMON - set(cls.PARAMS)
    if unknown:
        raise RuleError("rule %r: unknown field(s) %s for type %s" % (rid, ", ".join(sorted(unknown)), rtype))
    out = {"id": rid, "type": rtype}
    action = spec.get("action", "block")
    if action not in ACTIONS:
        raise RuleError("rule %r: action must be one of %s" % (rid, ACTIONS))
    out["action"] = action
    out["branches"] = _check_kind(rid, "branches", "list", spec.get("branches", ["*"]))
    if "message" in spec:
        out["message"] = _check_kind(rid, "message", "str", spec["message"])
    for name, (kind, required, default) in cls.PARAMS.items():
        if name in spec:
            out[name] = _check_kind(rid, name, kind, spec[name])
        elif required:
            raise RuleError("rule %r: missing required field %r" % (rid, name))
    cls(out)  # compile regexes etc. once more as a final check
    return out


def build(spec: dict) -> Rule:
    return RULE_TYPES[spec["type"]](spec)
