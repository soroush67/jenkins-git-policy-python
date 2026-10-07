"""Control plane: validation, compile, immutability, assign."""
import json
import os

import pytest
import yaml

from conftest import git
from gitpolicy import config as c
from gitpolicy.cli import main as cli
from gitpolicy.engine import Bundle


def test_sample_repository_compiles(config_repo):
    b = c.compile_bundle(config_repo, source_commit="abc")
    assert "no-binaries@1" in b["profiles"] and "strict@1" in b["profiles"]
    assert b["assignments"] == [{"project": "platform/policy-config", "profile": "policy-config-guard@1"}]
    assert Bundle(b).resolve("platform/policy-config")[0] == "policy-config-guard@1"
    # sizes are normalised to bytes in the bundle
    rules = {r["id"]: r for r in b["profiles"]["no-binaries@1"]["rules"]}
    assert rules["max-10mb"]["max_size"] == 10 * 1024 * 1024


def _write(root, rel, data):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(data if isinstance(data, str) else yaml.safe_dump(data))


@pytest.mark.parametrize("rel,data,needle", [
    ("profiles/x/1.yaml", {"name": "y", "version": 1, "rules": [{"id": "a", "type": "binary_files"}]}, "name must be 'x'"),
    ("profiles/x/1.yaml", {"name": "x", "version": 2, "rules": [{"id": "a", "type": "binary_files"}]}, "version must be 1"),
    ("profiles/x/v1.yaml", {"name": "x", "version": 1, "rules": []}, "<version>.yaml"),
    ("profiles/x/1.yaml", {"name": "x", "version": 1, "rules": []}, "non-empty list"),
    ("profiles/x/1.yaml", {"name": "x", "version": 1, "rules": [{"id": "a", "type": "nope"}]}, "unknown type"),
    ("profiles/x/1.yaml", {"name": "x", "version": 1, "rules": [{"id": "a", "type": "max_file_size"}]}, "missing required field 'max_size'"),
    ("profiles/x/1.yaml", {"name": "x", "version": 1, "rules": [{"id": "a", "type": "max_file_size", "max_size": "lots"}]}, "invalid size"),
    ("profiles/x/1.yaml", {"name": "x", "version": 1, "rules": [{"id": "a", "type": "commit_message", "pattern": "("}]}, "invalid regex"),
    ("profiles/x/1.yaml", {"name": "x", "version": 1, "rules": [{"id": "a", "type": "binary_files", "extensions": [".x"]}]}, "unknown field(s) extensions"),
    ("profiles/x/1.yaml", {"name": "x", "version": 1, "rules": [{"id": "a", "type": "binary_files", "action": "deny"}]}, "action must be"),
    ("profiles/x/1.yaml", {"name": "x", "version": 1, "rules": [{"id": "a", "type": "binary_files"}, {"id": "a", "type": "binary_files"}]}, "duplicate rule id"),
    ("profiles/Bad_Name/1.yaml", {"name": "Bad_Name", "version": 1, "rules": [{"id": "a", "type": "binary_files"}]}, "invalid profile name"),
    ("assignments.yaml", {"demo/app": "nope@1"}, "no such profile"),
    ("assignments.yaml", {"demo/app": "no-binaries"}, "not a profile reference"),
    ("assignments.yaml", {"justname": "no-binaries@1"}, "not a project path"),
    ("settings.yaml", {"fail_mode": "maybe"}, "fail_mode"),
    ("settings.yaml", {"colour": "blue"}, "unknown key"),
    ("settings.yaml", {"deprecated_profiles": ["ghost@9"]}, "deprecated_profiles: ghost@9"),
])
def test_validation_errors(config_repo, rel, data, needle):
    _write(config_repo, rel, data)
    with pytest.raises(c.ConfigError) as e:
        c.compile_bundle(config_repo)
    assert needle in str(e.value)


def test_invalid_yaml_reported(config_repo):
    _write(config_repo, "profiles/x/1.yaml", "name: x\nrules: [\n")
    with pytest.raises(c.ConfigError) as e:
        c.compile_bundle(config_repo)
    assert "invalid YAML" in str(e.value)


def test_immutability_against_installed_bundle(config_repo):
    installed = c.compile_bundle(config_repo)
    # adding a new version is fine
    _write(config_repo, "profiles/no-binaries/3.yaml",
           {"name": "no-binaries", "version": 3, "rules": [{"id": "a", "type": "binary_files"}]})
    c.compile_bundle(config_repo, previous=installed)
    # editing a published version (even a comment) is not
    with open(os.path.join(config_repo, "profiles/no-binaries/1.yaml"), "a") as f:
        f.write("# small edit\n")
    with pytest.raises(c.ConfigError) as e:
        c.compile_bundle(config_repo, previous=installed)
    assert "no-binaries@1 was published and its file changed" in str(e.value)
    assert "create no-binaries@4 instead" in str(e.value)
    # deleting one is not
    os.remove(os.path.join(config_repo, "profiles/strict/1.yaml"))
    with pytest.raises(c.ConfigError) as e:
        c.compile_bundle(config_repo, previous=installed)
    assert "strict@1 was published and is now missing" in str(e.value)


def test_immutability_against_git_history(config_repo):
    base = git(config_repo, "rev-parse", "HEAD").stdout.strip()
    _write(config_repo, "profiles/standard/2.yaml",
           {"name": "standard", "version": 2, "rules": [{"id": "a", "type": "binary_files"}]})
    git(config_repo, "add", "-A")
    git(config_repo, "commit", "-q", "-m", "add v2")
    assert c.git_immutability_problems(config_repo, base) == []
    with open(os.path.join(config_repo, "profiles/standard/1.yaml"), "a") as f:
        f.write("# edit\n")
    os.remove(os.path.join(config_repo, "profiles/strict/1.yaml"))
    git(config_repo, "commit", "-q", "-am", "edit")
    problems = c.git_immutability_problems(config_repo, base)
    assert any("profiles/standard/1.yaml was modified" in p for p in problems)
    assert any("profiles/strict/1.yaml was deleted" in p for p in problems)


def test_assign_flow(config_repo):
    assert c.assign(config_repo, "demo/app-a", "no-binaries@1", by="dev1", now="T1") == ("assigned", None)
    assert c.assign(config_repo, "demo/app-a", "no-binaries@1", by="dev1") == ("unchanged", "no-binaries@1")
    with pytest.raises(c.ConfigError) as e:
        c.assign(config_repo, "demo/app-a", "strict@1", by="dev2")
    assert "already has profile no-binaries@1" in str(e.value)
    assert c.assign(config_repo, "demo/app-a", "strict@1", by="dev2", replace=True, now="T2") == \
        ("replaced", "no-binaries@1")
    entries = c.load_assignments(config_repo)
    assert entries["demo/app-a"] == {"profile": "strict@1", "by": "dev2", "at": "T2"}
    # the file stays valid and keeps its header
    text = open(os.path.join(config_repo, "assignments.yaml")).read()
    assert text.startswith("# GitLab project -> policy profile")
    c.compile_bundle(config_repo)
    assert c.unassign(config_repo, "demo/app-a") == "strict@1"
    assert "demo/app-a" not in c.load_assignments(config_repo)


@pytest.mark.parametrize("project,profile,needle", [
    ("demo/app", "ghost@1", "does not exist"),
    ("not a path", "no-binaries@1", "not a GitLab project path"),
    ("demo/*", "no-binaries@1", "not a GitLab project path"),
    ("platform/policy-config", "no-binaries@1", "is locked"),
    ("platform/anything", "no-binaries@1", "is locked"),
])
def test_assign_refused(config_repo, project, profile, needle):
    with pytest.raises(c.ConfigError) as e:
        c.assign(config_repo, project, profile)
    assert needle in str(e.value)


def test_deprecated_profile_cannot_be_loaded_but_keeps_working(config_repo):
    c.assign(config_repo, "demo/app", "no-binaries@1")
    _write(config_repo, "settings.yaml", {"deprecated_profiles": ["no-binaries@1"], "locked_projects": ["platform/*"]})
    with pytest.raises(c.ConfigError):
        c.assign(config_repo, "demo/other", "no-binaries@1")
    b = c.compile_bundle(config_repo)
    assert {"project": "demo/app", "profile": "no-binaries@1"} in b["assignments"]


def test_assign_normalises_project_path(config_repo):
    c.assign(config_repo, "/demo/App.git/", "standard@1")
    assert "demo/App" in c.load_assignments(config_repo)
    assert c.assign(config_repo, "demo/app", "standard@1")[0] == "unchanged"  # case-insensitive


def test_diff_bundles(config_repo):
    old = c.compile_bundle(config_repo)
    c.assign(config_repo, "demo/a", "standard@1")
    _write(config_repo, "profiles/standard/2.yaml",
           {"name": "standard", "version": 2, "rules": [{"id": "a", "type": "binary_files"}]})
    new = c.compile_bundle(config_repo)
    lines = c.diff_bundles(old, new)
    assert "+ profile standard@2" in lines and "+ demo/a -> standard@1" in lines


# ------------------------------------------------------------------- CLI
def test_cli_compile_validate_and_list(config_repo, tmp_path, capsys):
    out = str(tmp_path / "bundle.json")
    assert cli(["compile", config_repo, "-o", out, "--source-commit", "c0ffee"]) == 0
    assert json.load(open(out))["source_commit"] == "c0ffee"
    assert cli(["validate", config_repo, "--previous", out]) == 0
    capsys.readouterr()
    assert cli(["list-profiles", config_repo, "--loadable"]) == 0
    lines = capsys.readouterr().out.split()
    assert lines.index("no-binaries@2") < lines.index("no-binaries@1")   # newest first
    with open(os.path.join(config_repo, "profiles/no-binaries/1.yaml"), "a") as f:
        f.write("# edit\n")
    assert cli(["validate", config_repo, "--previous", out]) == 1
    assert "immutable" in capsys.readouterr().err


def test_cli_assign_and_show(config_repo, capsys):
    assert cli(["assign", config_repo, "--project", "demo/app", "--profile", "standard@1", "--by", "dev1"]) == 0
    assert cli(["assign", config_repo, "--project", "demo/app", "--profile", "strict@1"]) == 1
    assert "REPLACE_EXISTING" in capsys.readouterr().err
    assert cli(["show", config_repo, "--project", "demo/app"]) == 0
    out = capsys.readouterr().out
    assert "profile standard@1" in out and "loaded by dev1" in out and "no-secrets" in out
    assert cli(["show", config_repo, "--project", "demo/none"]) == 0
    assert "no profile loaded" in capsys.readouterr().out


def test_cli_check_dry_run(lab, capsys):
    from conftest import BINARY
    lab.profile("no-binaries@1", [{"id": "no-bin", "type": "binary_files"}])
    lab.commit(**{"a.txt": "a"})
    lab.commit(**{"b.bin": BINARY})
    args = ["check", "--bundle", lab.bundle_path, "--project", "demo/app", "--repo", lab.work, "--ref", "main"]
    assert cli(args + ["--new", "HEAD~1"]) == 0
    assert cli(args + ["--new", "HEAD"]) == 1
    assert "REJECTED" in capsys.readouterr().out
    assert cli(args[:4] + ["demo/free"] + args[5:] + ["--new", "HEAD"]) == 0


def test_cli_describe_rules_and_doctor(tmp_path, capsys):
    assert cli(["describe-rules"]) == 0
    out = capsys.readouterr().out
    for t in ("binary_files", "secret_patterns", "immutable_paths", "branch_name"):
        assert t in out
    assert cli(["doctor", "--bundle", str(tmp_path / "none.json")]) == 0
    (tmp_path / "bad.json").write_text("{}")
    assert cli(["doctor", "--bundle", str(tmp_path / "bad.json")]) == 1


def test_samples_profiles_are_valid(config_repo):
    import glob
    import shutil
    from conftest import ROOT
    for path in glob.glob(os.path.join(ROOT, "samples", "profiles", "*.yaml")):
        data = yaml.safe_load(open(path))
        dst = os.path.join(config_repo, "profiles", data["name"])
        os.makedirs(dst)
        shutil.copy(path, os.path.join(dst, "%d.yaml" % data["version"]))
    b = c.compile_bundle(config_repo)
    assert "company-java@1" in b["profiles"] and "monorepo-paths@1" in b["profiles"]
