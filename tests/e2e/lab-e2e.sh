#!/usr/bin/env bash
# End-to-end test against the running lab (lab/up.sh): real Jenkins jobs run
# as real users, real git pushes over HTTP, real merge request merges.
# Rerunnable. Does NOT run against production - it changes lab data.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
LAB=$ROOT/lab
. "$LAB/lib.sh"
set -a; . "$LAB/.env"; . "$LAB/secrets/jenkins.env"; set +a
BOT=$(cat "$LAB/secrets/gitlab-bot-token")
DEV1_TOKEN=$(cat "$LAB/secrets/dev1-token"); DEV2_TOKEN=$(cat "$LAB/secrets/dev2-token")
GL=http://localhost:8940
RUN=$(date +%s)
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
export GIT_TERMINAL_PROMPT=0

pass=0 fail=0
ok()   { pass=$((pass+1)); echo "  PASS  $*"; }
bad()  { fail=$((fail+1)); echo "  FAIL  $*"; }
check() { local d=$1; shift; if "$@"; then ok "$d"; else bad "$d"; fi; }

# job <user> <pass> <job> [-F k=v ...] -> sets JOB_RESULT and JOB_LOG
job() {
    local u=$1 p=$2 j=$3; shift 3
    j_login "$u" "$p"
    local n; n=$(j_trigger "$j" "$@") || { JOB_RESULT=NOTRIGGER; JOB_LOG=""; return; }
    JOB_RESULT=$(j_wait "$j" "$n")
    JOB_LOG=$(j_console "$j" "$n")
}
api() { curl -sS -H "PRIVATE-TOKEN: $BOT" "$@"; }
as_dev1() { curl -sS -H "PRIVATE-TOKEN: $DEV1_TOKEN" "$@"; }
as_dev2() { curl -sS -H "PRIVATE-TOKEN: $DEV2_TOKEN" "$@"; }
pid() { python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1],safe=''))" "$1"; }
clone() {   # clone <user> <pass> <project> <dir>
    git clone -q "http://$1:$2@localhost:8940/$3.git" "$4" &&
    git -C "$4" config user.name "$1" && git -C "$4" config user.email "$1@gitpolicy.local"
}
binary() { head -c 4096 /dev/urandom > "$1"; printf '\x7fELF' | dd of="$1" conv=notrunc status=none; }

echo "== 0. installation"
check "doctor on GitLab reports OK" bash -c "GP_TARGET=docker:gpp-gitlab '$ROOT/deploy/push.sh' doctor | grep -q '=> OK'"

echo "== 1. Jenkins permissions"
j_login dev1 "$DEV1_PASSWORD"
check "dev1 sees policy/load-profile" test "$(j_status /job/policy/job/load-profile/api/json)" = 200
check "dev1 cannot see policy-admin/deploy" test "$(j_status /job/policy-admin/job/deploy/api/json)" != 200

echo "== 2. loading profiles"
job admin "$JENKINS_ADMIN_PASSWORD" policy-admin/unload-profile -F PROJECT=demo/app-b
check "admin unloads demo/app-b (reset)" test "$JOB_RESULT" = SUCCESS
job dev1 "$DEV1_PASSWORD" policy/load-profile -F PROJECT=demo/app-a -F PROFILE=no-binaries@1 -F REPLACE_EXISTING=true
check "dev1 (maintainer) loads no-binaries@1 for demo/app-a" test "$JOB_RESULT" = SUCCESS
job dev1 "$DEV1_PASSWORD" policy/load-profile -F PROJECT=demo/app-a -F PROFILE=strict@1 -F REPLACE_EXISTING=false
check "switching without REPLACE_EXISTING is refused" bash -c '[ "$0" = FAILURE ] && grep -q "already has profile no-binaries@1" <<<"$1"' "$JOB_RESULT" "$JOB_LOG"
job dev1 "$DEV1_PASSWORD" policy/load-profile -F PROJECT=demo/app-b -F PROFILE=no-binaries@1
check "dev1 (only developer of demo/app-b) is refused" bash -c '[ "$0" = FAILURE ] && grep -q "is not maintainer" <<<"$1"' "$JOB_RESULT" "$JOB_LOG"
job dev1 "$DEV1_PASSWORD" policy/load-profile -F PROJECT=demo/does-not-exist -F PROFILE=no-binaries@1
check "unknown project is refused" bash -c '[ "$0" = FAILURE ] && grep -q "not found" <<<"$1"' "$JOB_RESULT" "$JOB_LOG"
job dev2 "$DEV2_PASSWORD" policy/show -F PROJECT=demo/app-a
check "policy/show shows the loaded profile" bash -c '[ "$0" = SUCCESS ] && grep -q "profile no-binaries@1" <<<"$1"' "$JOB_RESULT" "$JOB_LOG"
check "assignment is a commit by dev1 in policy-config" bash -c \
    "curl -sS -H 'PRIVATE-TOKEN: $BOT' '$GL/api/v4/projects/platform%2Fpolicy-config/repository/commits?per_page=20' | grep -q 'dev1 (via Jenkins)'"

echo "== 3. pushes (demo/app-a, no-binaries@1)"
clone dev1 "$DEV1_PASSWORD" demo/app-a "$TMP/a"
echo "run $RUN" >> "$TMP/a/README.md"; git -C "$TMP/a" commit -qam "docs: run $RUN"
check "text change is accepted" git -C "$TMP/a" push -q origin HEAD:main
binary "$TMP/a/tool.bin"; git -C "$TMP/a" add tool.bin; git -C "$TMP/a" commit -qm "add tool"
out=$(git -C "$TMP/a" push origin HEAD:main 2>&1)
check "binary push is rejected" bash -c 'grep -q "push REJECTED by profile no-binaries@1" <<<"$0" && grep -q "\[no-binary-files\] tool.bin" <<<"$0"' "$out"
echo "$out" | grep -E "remote: (gitpolicy|  )" | head -5 | sed 's/^/        /'
git -C "$TMP/a" rm -q tool.bin; git -C "$TMP/a" commit -qm "remove tool"
check "binary added then removed is still rejected" bash -c '! git -C "$0" push -q origin HEAD:main 2>/dev/null' "$TMP/a"
git -C "$TMP/a" reset -q --hard origin/main
mkdir -p "$TMP/a/lib"; echo "not really a dll" > "$TMP/a/lib/x.dll"; git -C "$TMP/a" add -A; git -C "$TMP/a" commit -qm "dll"
check "forbidden extension (.dll) is rejected" bash -c '! git -C "$0" push -q origin HEAD:main 2>/dev/null' "$TMP/a"
git -C "$TMP/a" reset -q --hard origin/main

echo "== 4. web commit (GitLab UI / API) is checked too"
code=$(as_dev1 -o "$TMP/web.json" -w '%{http_code}' -X POST "$GL/api/v4/projects/$(pid demo/app-a)/repository/commits" \
    -H 'Content-Type: application/json' \
    -d "{\"branch\":\"main\",\"commit_message\":\"web upload\",\"actions\":[{\"action\":\"create\",\"file_path\":\"web-$RUN.bin\",\"encoding\":\"base64\",\"content\":\"$(head -c 512 /dev/urandom | base64 -w0)\"}]}")
check "binary uploaded through the web/API is rejected (HTTP $code)" bash -c '[ "$0" != 201 ] && grep -q "REJECTED" "$1"' "$code" "$TMP/web.json"

echo "== 5. binary pushed BEFORE the profile cannot be merged (demo/app-b)"
clone dev2 "$DEV2_PASSWORD" demo/app-b "$TMP/b"
git -C "$TMP/b" checkout -qb "feature/blob-$RUN"
binary "$TMP/b/blob.bin"; git -C "$TMP/b" add blob.bin; git -C "$TMP/b" commit -qm "add blob"
check "no profile yet: binary on a feature branch is accepted" git -C "$TMP/b" push -q origin "HEAD:feature/blob-$RUN"
job dev2 "$DEV2_PASSWORD" policy/load-profile -F PROJECT=demo/app-b -F PROFILE=no-binaries@1
check "dev2 loads no-binaries@1 for demo/app-b" test "$JOB_RESULT" = SUCCESS
mr=$(as_dev2 -X POST "$GL/api/v4/projects/$(pid demo/app-b)/merge_requests" \
    --data-urlencode "source_branch=feature/blob-$RUN" --data-urlencode "target_branch=main" --data-urlencode "title=blob $RUN" \
    | python3 -c "import json,sys;print(json.load(sys.stdin)['iid'])")
sleep 5   # let GitLab compute mergeability
code=$(as_dev2 -o "$TMP/merge.json" -w '%{http_code}' -X PUT "$GL/api/v4/projects/$(pid demo/app-b)/merge_requests/$mr/merge")
state=$(api "$GL/api/v4/projects/$(pid demo/app-b)/merge_requests/$mr" | python3 -c "import json,sys;print(json.load(sys.stdin)['state'])")
check "merge request merge is rejected (HTTP $code, MR state $state)" test "$state" = opened -a "$code" != 200
echo "        GitLab answered: $(cat "$TMP/merge.json")"
# The UI "Merge" button goes through MergeService (async); GitLab stores the
# hook output in merge_error and shows it on the merge request page.
ui=$(docker exec -i gpp-gitlab gitlab-rails runner - <<RUBY 2>/dev/null
p = Project.find_by_full_path('demo/app-b'); mr = p.merge_requests.find_by(iid: $mr)
MergeRequests::MergeService.new(project: p, current_user: User.find_by_username('dev2'), params: { sha: mr.diff_head_sha }).execute(mr)
puts mr.reload.merge_error
RUBY
)
check "UI merge shows the gitpolicy reason on the MR page" bash -c 'grep -q "gitpolicy: push REJECTED by profile no-binaries@1" <<<"$0" && grep -q "blob.bin" <<<"$0"' "$ui"
echo "        MR page: $(cut -c1-160 <<<"$ui")..."
check "main of demo/app-b has no blob.bin" bash -c "! curl -sS -H 'PRIVATE-TOKEN: $BOT' '$GL/api/v4/projects/$(pid demo/app-b)/repository/tree?ref=main' | grep -q blob.bin"
git -C "$TMP/b" fetch -q origin
check "copying the dirty branch to a new branch is rejected" bash -c \
    "! git -C '$TMP/b' push -q origin 'origin/feature/blob-$RUN:refs/heads/copy-$RUN' 2>/dev/null"
check "a new branch from clean main is accepted" git -C "$TMP/b" push -q origin "origin/main:refs/heads/clean-$RUN"

echo "== 6. the policy repository protects itself (policy-config-guard@1)"
git clone -q "http://jenkins-bot:$BOT@localhost:8940/platform/policy-config.git" "$TMP/cfg"
git -C "$TMP/cfg" config user.name e2e; git -C "$TMP/cfg" config user.email e2e@gitpolicy.local
echo "# sneaky edit" >> "$TMP/cfg/profiles/no-binaries/1.yaml"; git -C "$TMP/cfg" commit -qam "edit published profile"
out=$(git -C "$TMP/cfg" push origin HEAD:main 2>&1)
check "editing a published profile is rejected by the hook" grep -q "immutable file modified" <<<"$out"
git -C "$TMP/cfg" reset -q --hard origin/main
if [ ! -f "$TMP/cfg/profiles/e2e-sample/1.yaml" ]; then
    mkdir -p "$TMP/cfg/profiles/e2e-sample"
    printf 'name: e2e-sample\nversion: 1\ndescription: created by the e2e test\nrules:\n  - id: max-1mb\n    type: max_file_size\n    max_size: 1MB\n' \
        > "$TMP/cfg/profiles/e2e-sample/1.yaml"
    git -C "$TMP/cfg" add -A; git -C "$TMP/cfg" commit -qm "add profile e2e-sample@1"
    check "adding a new profile version is accepted" git -C "$TMP/cfg" push -q origin HEAD:main
else
    ok "profile e2e-sample@1 already published (rerun)"
fi
job admin "$JENKINS_ADMIN_PASSWORD" policy-admin/deploy
check "deploy job succeeds" test "$JOB_RESULT" = SUCCESS
j_login dev1 "$DEV1_PASSWORD"
check "new profile appears in the load-profile dropdown" bash -c \
    "curl -gsS -u 'dev1:$DEV1_PASSWORD' 'http://localhost:8096/job/policy/job/load-profile/api/json?tree=property[parameterDefinitions[name,choices]]' | grep -q 'e2e-sample@1'"

echo "== 7. audit log on the GitLab server"
check "rejections are in the audit log" bash -c \
    "docker exec gpp-gitlab tail -n 50 /var/log/gitlab/gitpolicy/audit.log | grep -q '\"decision\": \"reject\"'"

echo
echo "e2e: $pass passed, $fail failed"
[ "$fail" = 0 ]
