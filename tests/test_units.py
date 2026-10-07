"""Small units: globs, sizes, rule normalisation, bundle resolution."""
import pytest

from gitpolicy import BUNDLE_FORMAT
from gitpolicy.engine import Bundle, BundleError
from gitpolicy.globs import branch_matches, path_matches
from gitpolicy.rules import RuleError, _is_pe, normalize, parse_size


@pytest.mark.parametrize("path,pattern,expected", [
    ("a.exe", "*.exe", True),
    ("bin/deep/a.exe", "*.exe", True),
    ("a.exe.txt", "*.exe", False),
    ("docs/img/a.png", "docs/**/*.png", True),
    ("docs/a.png", "docs/**/*.png", True),
    ("src/docs/a.png", "docs/**/*.png", False),
    ("secrets/x/y", "secrets/", True),
    ("app/secrets/x", "secrets/", True),   # like .gitignore: any level
    ("app/secrets/x", "/secrets/", False),
    (".env", ".env", True),
    ("svc/.env", ".env", True),
    ("svc/.env.example", ".env", False),
    ("x/y/id_rsa.pub", "id_rsa*", True),
    ("README.md", "/README.md", True),
    ("docs/README.md", "/README.md", False),
    ("a/b/c.txt", "a/*/c.txt", True),
    ("a/b/x/c.txt", "a/*/c.txt", False),
    ("assets/anything/deep", "assets/**", True),
    ("f1.txt", "f[0-9].txt", True),
    ("fx.txt", "f[!0-9].txt", True),
])
def test_path_matches(path, pattern, expected):
    assert path_matches(path, pattern) is expected


def test_branch_matches():
    assert branch_matches("release/2024/q1", ["release/*"])
    assert branch_matches("main", ["*"])
    assert not branch_matches("main2", ["main"])


@pytest.mark.parametrize("value,expected", [
    (100, 100), ("100", 100), ("1KB", 1024), ("1.5 MB", 1572864), ("2GiB", 2 * 1024 ** 3), ("10mb", 10485760),
])
def test_parse_size(value, expected):
    assert parse_size(value) == expected


@pytest.mark.parametrize("value", ["", "ten", "5TB", True, "-1"])
def test_parse_size_invalid(value):
    with pytest.raises(RuleError):
        parse_size(value)


def test_normalize_defaults_and_errors():
    n = normalize({"id": "a", "type": "forbidden_extensions", "extensions": ".exe"})
    assert n == {"id": "a", "type": "forbidden_extensions", "action": "block", "branches": ["*"],
                 "extensions": [".exe"]}
    for bad in ({"type": "binary_files"}, {"id": "A B", "type": "binary_files"}, "string",
                {"id": "a", "type": "binary_files", "branches": [1]},
                {"id": "a", "type": "binary_files", "scan_bytes": 0},
                {"id": "a", "type": "secret_patterns", "patterns": ["x"]},
                {"id": "a", "type": "secret_patterns", "patterns": {"x": "("}}):
        with pytest.raises(RuleError):
            normalize(bad)


def test_pe_detection():
    head = bytearray(b"MZ" + b"\x90" * 200)
    head[0x3c:0x40] = (0x80).to_bytes(4, "little")
    head[0x80:0x84] = b"PE\0\0"
    assert _is_pe(bytes(head))
    assert not _is_pe(b"MZ is a nice text that starts like a DOS header but is not one at all, really")


def _bundle(assignments, profiles=("a@1", "b@1")):
    return Bundle({"format": BUNDLE_FORMAT, "settings": {},
                   "profiles": {p: {"rules": []} for p in profiles}, "assignments": assignments})


def test_bundle_resolution_order():
    b = _bundle([{"project": "demo/*", "profile": "a@1"}, {"project": "demo/team/*", "profile": "b@1"},
                 {"project": "demo/x", "profile": "b@1"}])
    assert b.resolve("demo/x") == ("b@1", "demo/x")
    assert b.resolve("DEMO/X")[0] == "b@1"
    assert b.resolve("demo/y") == ("a@1", "demo/*")
    assert b.resolve("demo/team/z") == ("b@1", "demo/team/*")   # longer pattern wins
    assert b.resolve("other/y") == (None, None)


def test_bundle_rejects_bad_input():
    with pytest.raises(BundleError):
        Bundle({"format": 99})
    with pytest.raises(BundleError):
        _bundle([{"project": "x/y", "profile": "missing@1"}])
