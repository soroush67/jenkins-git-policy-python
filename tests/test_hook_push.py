"""End-to-end: real `git push` into a bare repository running the hook."""
import json

from conftest import BINARY, git

NO_BIN = [{"id": "no-bin", "type": "binary_files", "message": "use Nexus"}]


def test_project_without_profile_is_not_checked(lab):
    lab.profile("no-binaries@1", NO_BIN, assign=False)
    lab.commit(**{"tool.bin": BINARY})
    assert lab.push().ok


def test_no_bundle_installed_allows_everything(lab):
    lab.commit(**{"tool.bin": BINARY})
    assert lab.push().ok


def test_binary_push_rejected_text_allowed(lab):
    lab.profile("no-binaries@1", NO_BIN)
    lab.commit(**{"README.md": "hello\n"})
    assert lab.push().ok
    lab.commit(**{"bin__tool": BINARY})
    r = lab.push()
    assert not r.ok
    assert "REJECTED by profile no-binaries@1" in r.output
    assert "[no-bin] bin/tool" in r.output
    assert "hint: [no-bin] use Nexus" in r.output
    # the server branch did not move
    assert git(lab.server, "ls-tree", "-r", "--name-only", "main").stdout.split() == ["README.md"]


def test_binary_removed_in_later_commit_still_rejected(lab):
    """The binary must not reach the server's history at all."""
    lab.profile("no-binaries@1", NO_BIN)
    lab.commit(**{"a.txt": "a"})
    assert lab.push().ok
    lab.commit(**{"blob.dat": BINARY})
    lab.rm("blob.dat")
    r = lab.push()
    assert not r.ok and "blob.dat" in r.output


def test_binary_pushed_before_profile_cannot_be_merged_into_main(lab):
    """The core requirement: content that got into one branch cannot move to another."""
    lab.commit(**{"README.md": "x\n"})
    assert lab.push().ok
    git(lab.work, "checkout", "-q", "-b", "feature/x")
    lab.commit(**{"lib.dll": BINARY})
    assert lab.push("HEAD:feature/x").ok          # no profile yet -> accepted
    lab.profile("no-binaries@1", NO_BIN)          # profile loaded afterwards

    # 1) merge locally and push main
    git(lab.work, "checkout", "-q", "main")
    git(lab.work, "merge", "-q", "--no-ff", "-m", "Merge feature/x", "feature/x")
    r = lab.push("main:main")
    assert not r.ok and "lib.dll" in r.output
    # 2) fast-forward main onto the feature commit
    git(lab.work, "reset", "-q", "--hard", "origin/feature/x")
    assert not lab.push("HEAD:main").ok
    # 3) copy the dirty branch into a new branch
    r = lab.push("origin/feature/x:refs/heads/release/1.0")
    assert not r.ok and "lib.dll" in r.output
    # 4) a new branch from the clean main is fine
    assert lab.push("origin/main:refs/heads/feature/clean").ok


def test_squash_merge_rejected(lab):
    lab.commit(**{"README.md": "x\n"})
    assert lab.push().ok
    lab.profile("no-binaries@1", NO_BIN)
    git(lab.work, "checkout", "-q", "-b", "feature/y")
    lab.commit(**{"img.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 64})
    git(lab.work, "checkout", "-q", "main")
    git(lab.work, "merge", "-q", "--squash", "feature/y")
    git(lab.work, "commit", "-q", "-m", "squashed")
    assert not lab.push("main:main").ok


def test_branch_scoped_rule(lab):
    lab.profile("p@1", [{"id": "no-bin-main", "type": "binary_files", "branches": ["main", "release/*"]}])
    lab.commit(**{"README.md": "x\n"})
    assert lab.push().ok
    git(lab.work, "checkout", "-q", "-b", "sandbox")
    lab.commit(**{"x.bin": BINARY})
    assert lab.push("HEAD:sandbox").ok            # rule does not cover sandbox
    assert not lab.push("HEAD:main").ok           # ...but it can't reach main
    assert not lab.push("HEAD:release/2.0").ok


def test_warn_action_accepts_with_warning(lab):
    lab.profile("p@1", [{"id": "big", "type": "max_file_size", "max_size": "1KB", "action": "warn"}])
    lab.commit(**{"big.txt": "a" * 5000})
    r = lab.push()
    assert r.ok
    assert "WARNING" in r.output and "[big] big.txt" in r.output


def test_extension_path_size_rules(lab):
    lab.profile("p@1", [
        {"id": "ext", "type": "forbidden_extensions", "extensions": ["exe", ".DLL"]},
        {"id": "paths", "type": "forbidden_paths", "patterns": [".env", "secrets/"], "allow_paths": [".env.example"]},
        {"id": "size", "type": "max_file_size", "max_size": "2KB"},
    ])
    lab.commit(**{".env.example": "A=1\n", "src__ok.py": "print(1)\n"})
    assert lab.push().ok
    for files, needle in (({"tools__Setup.EXE": "text pretending"}, "[ext] tools/Setup.EXE"),
                          ({"x.dll": "z"}, "[ext] x.dll"),
                          ({"app__.env": "A=1"}, "[paths] app/.env"),
                          ({"secrets__k.txt": "k"}, "[paths] secrets/k.txt"),
                          ({"huge.txt": "x" * 3000}, "[size] huge.txt")):
        git(lab.work, "reset", "-q", "--hard", "origin/main")
        lab.commit(**files)
        r = lab.push()
        assert not r.ok, files
        assert needle in r.output, r


def test_allow_paths_for_binaries(lab):
    lab.profile("p@1", [{"id": "bin", "type": "binary_files", "allow_paths": ["docs/**/*.png"],
                         "allow_extensions": ["ico"]}])
    lab.commit(**{"docs__img__a.png": b"\x89PNG\r\n\x1a\n\x00\x00", "favicon.ICO": b"\x00\x00\x01"})
    assert lab.push().ok
    lab.commit(**{"src__a.png": b"\x89PNG\r\n\x1a\n\x00\x00"})
    assert not lab.push().ok


def test_secret_patterns(lab):
    lab.profile("p@1", [{"id": "secrets", "type": "secret_patterns",
                         "patterns": {"internal-token": "INT-[0-9]{8}"}}])
    lab.commit(**{"ok.py": "x = 1\n"})
    assert lab.push().ok
    for content, name in (("key = 'AKIAABCDEFGHIJKLMNOP'\n", "aws-access-key-id"),
                          ("-----BEGIN RSA PRIVATE KEY-----\nabc\n", "private-key"),
                          ("a\nb\ntoken: INT-12345678\n", "internal-token")):
        git(lab.work, "reset", "-q", "--hard", "origin/main")
        lab.commit(**{"conf.txt": content})
        r = lab.push()
        assert not r.ok and name in r.output, r
    assert "line 3" in r.output


def test_commit_message_and_author(lab):
    lab.profile("p@1", [
        {"id": "cc", "type": "commit_message", "pattern": r"^(feat|fix|chore): "},
        {"id": "mail", "type": "author_email", "pattern": r"@example\.com$"},
    ])
    lab.commit("feat: good one", **{"a": "1"})
    assert lab.push().ok
    lab.commit("bad message", **{"a": "2"})
    r = lab.push()
    assert not r.ok and "[cc]" in r.output
    git(lab.work, "reset", "-q", "--hard", "origin/main")
    git(lab.work, "-c", "user.email=x@evil.org", "commit", "-q", "--allow-empty", "-m", "fix: x",
        env={"GIT_AUTHOR_EMAIL": "x@evil.org"})
    r = lab.push()
    assert not r.ok and "x@evil.org" in r.output


def test_merge_commit_message_skipped_by_default(lab):
    lab.profile("p@1", [{"id": "cc", "type": "commit_message", "pattern": r"^feat: "}])
    lab.commit("feat: base", **{"a": "1"})
    assert lab.push().ok
    git(lab.work, "checkout", "-q", "-b", "f")
    lab.commit("feat: f", **{"b": "1"})
    git(lab.work, "checkout", "-q", "main")
    lab.commit("feat: m", **{"c": "1"})
    git(lab.work, "merge", "-q", "--no-ff", "-m", "Merge branch f", "f")
    assert lab.push("main:main").ok


def test_branch_naming_force_push_and_delete(lab):
    lab.profile("p@1", [
        {"id": "names", "type": "branch_name", "pattern": r"^(main|feature/.+)$"},
        {"id": "nff", "type": "no_force_push", "branches": ["main"]},
        {"id": "nodel", "type": "no_branch_delete", "branches": ["main"]},
    ])
    lab.commit(**{"a": "1"})
    assert lab.push().ok
    assert lab.push("HEAD:feature/ok").ok
    r = lab.push("HEAD:wip")
    assert not r.ok and "[names]" in r.output
    lab.commit(**{"a": "2"})
    assert lab.push().ok
    git(lab.work, "reset", "-q", "--hard", "HEAD~1")
    lab.commit(**{"a": "3"})
    r = lab.push(force=True)
    assert not r.ok and "force push" in r.output
    assert lab.push(":feature/ok").ok              # deleting a feature branch is fine
    r = lab.push(":main")
    assert not r.ok and "[nodel]" in r.output


def test_immutable_paths(lab):
    lab.profile("guard@1", [{"id": "imm", "type": "immutable_paths", "patterns": ["profiles/**"]}])
    lab.commit(**{"profiles__a__1.yaml": "v1\n", "assignments.yaml": "x\n"})
    assert lab.push().ok
    lab.commit(**{"profiles__a__2.yaml": "v2\n", "assignments.yaml": "y\n"})
    assert lab.push().ok                            # adding a version + editing others is fine
    lab.commit(**{"profiles__a__1.yaml": "changed\n"})
    r = lab.push()
    assert not r.ok and "immutable file modified" in r.output
    git(lab.work, "reset", "-q", "--hard", "origin/main")
    git(lab.work, "mv", "profiles/a/1.yaml", "profiles/a/old.yaml")
    git(lab.work, "commit", "-q", "-m", "rename")
    r = lab.push()
    assert not r.ok and "deleted or renamed" in r.output


def test_glob_assignment_and_exact_wins(lab):
    lab.profile("strict@1", [{"id": "no-bin", "type": "binary_files"}], assign=False)
    lab.profile("lax@1", [{"id": "size", "type": "max_file_size", "max_size": "1MB"}], assign=False)
    lab.assign("demo/*", "strict@1")
    lab.commit(**{"x.bin": BINARY})
    assert not lab.push().ok                        # demo/app matched by demo/*
    lab.assign("demo/app", "lax@1")
    assert lab.push().ok                            # exact match wins


def test_web_merge_uses_gitlab_ui_prefix(lab):
    lab.profile("no-binaries@1", NO_BIN)
    lab.commit(**{"x.bin": BINARY})
    r = lab.push(protocol="web")
    assert not r.ok
    assert "GL-HOOK-ERR: gitpolicy: push REJECTED" in r.output


def test_break_glass_user_bypasses_and_is_audited(lab):
    lab.settings["break_glass_users"] = ["root"]
    lab.profile("no-binaries@1", NO_BIN)
    lab.commit(**{"x.bin": BINARY})
    assert not lab.push(user="dev1").ok
    r = lab.push(user="root")
    assert r.ok and "BYPASSED" in r.output
    decisions = [rec["decision"] for rec in lab.audit_records()]
    assert decisions == ["reject", "bypass"]


def test_audit_log_record(lab):
    lab.profile("no-binaries@1", NO_BIN)
    lab.commit(**{"x.bin": BINARY})
    lab.push()
    rec = lab.audit_records()[-1]
    assert rec["project"] == "demo/app" and rec["user"] == "dev1" and rec["decision"] == "reject"
    assert rec["violations"][0]["rule_id"] == "no-bin" and rec["violations"][0]["path"] == "x.bin"


def test_broken_bundle_fails_closed_or_open(lab):
    lab.profile("no-binaries@1", NO_BIN)
    with open(lab.bundle_path, "w") as f:
        f.write("{not json")
    lab.commit(**{"a": "1"})
    r = lab.push()
    assert not r.ok and "fail_mode: closed" in r.output
    lab.settings["fail_mode"] = "open"
    lab.write_bundle()
    data = json.load(open(lab.bundle_path))
    data["profiles"]["no-binaries@1"]["rules"][0]["type"] = "does-not-exist"
    json.dump(data, open(lab.bundle_path, "w"))
    r = lab.push()
    assert r.ok and "fail_mode: open" in r.output


def test_too_many_commits_falls_back_to_tree_check(lab):
    lab.settings["max_commits"] = 3
    lab.profile("p@1", [{"id": "no-bin", "type": "binary_files"},
                        {"id": "cc", "type": "commit_message", "pattern": "^feat"}])
    for i in range(5):
        lab.commit("whatever %d" % i, **{"f%d.txt" % i: "x"})
    r = lab.push()
    assert r.ok and "commit rules skipped" in r.output
    for i in range(5):
        lab.commit("whatever %d" % i, **{"g%d.txt" % i: "x"})
    lab.commit("x", **{"z.bin": BINARY})
    r = lab.push()
    assert not r.ok and "z.bin" in r.output


def test_tags_are_not_checked(lab):
    lab.commit(**{"README": "x"})
    assert lab.push().ok
    lab.profile("no-binaries@1", NO_BIN)
    lab.commit(**{"x.bin": BINARY})
    git(lab.work, "tag", "v1")
    assert lab.push("refs/tags/v1:refs/tags/v1").ok
