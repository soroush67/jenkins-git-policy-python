# Jenkins REST helpers for the lab scripts/tests (source this file).
# Every call runs as a given user with that user's own session + CSRF crumb,
# exactly as a browser would - so permission checks are the real ones.
JENKINS_HTTP=${JENKINS_HTTP:-http://localhost:8096}

_jpath() { local p=""; IFS=/ read -ra parts <<<"$1"; for x in "${parts[@]}"; do p="$p/job/$x"; done; echo "$p"; }
_json() { python3 -c "import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1]))" "$1"; }

# j_login <user> <pass> -> sets J_USER/J_PASS/J_JAR/J_CRUMB
j_login() {
    J_USER=$1; J_PASS=$2; J_JAR=$(mktemp)
    J_CRUMB=$(curl -fsS -c "$J_JAR" -b "$J_JAR" -u "$J_USER:$J_PASS" "$JENKINS_HTTP/crumbIssuer/api/json" | _json "d['crumb']")
}
_jcurl() { curl -sS -c "$J_JAR" -b "$J_JAR" -u "$J_USER:$J_PASS" -H "Jenkins-Crumb: $J_CRUMB" "$@"; }

# j_status <url-path> -> HTTP status code of a GET as the logged-in user
j_status() { _jcurl -o /dev/null -w '%{http_code}' "$JENKINS_HTTP$1"; }

# j_trigger <job> [curl -F name=value ...] -> echoes the build number
j_trigger() {
    local job=$1; shift
    local endpoint=build
    [ $# -gt 0 ] && endpoint=buildWithParameters
    local loc
    loc=$(_jcurl -o /dev/null -D - -X POST "$@" "$JENKINS_HTTP$(_jpath "$job")/$endpoint" | tr -d '\r' | awk 'tolower($1)=="location:"{print $2}')
    [ -n "$loc" ] || { echo "trigger of $job failed (no queue item - permission denied?)" >&2; return 1; }
    local n=""
    for _ in $(seq 1 120); do
        n=$(_jcurl "${loc}api/json" | _json "(d.get('executable') or {}).get('number','')" 2>/dev/null || true)
        [ -n "$n" ] && { echo "$n"; return 0; }
        sleep 1
    done
    echo "build of $job never left the queue" >&2; return 1
}

# j_wait_input <job> <n> -> echoes the pending input id once the build waits on one
j_wait_input() {
    local id=""
    for _ in $(seq 1 180); do
        id=$(_jcurl "$JENKINS_HTTP$(_jpath "$1")/$2/wfapi/pendingInputActions" | _json "d[0]['id'] if d else ''" 2>/dev/null || true)
        [ -n "$id" ] && { echo "$id"; return 0; }
        [ "$(j_result "$1" "$2")" != "" ] && { echo "build finished without asking for input" >&2; return 1; }
        sleep 2
    done
    return 1
}

# j_approve <job> <n> <input-id> -> HTTP status of the "Proceed" click
j_approve() { _jcurl -o /dev/null -w '%{http_code}' -X POST "$JENKINS_HTTP$(_jpath "$1")/$2/input/$3/proceedEmpty"; }
# j_reject <job> <n> <input-id>
j_reject() { _jcurl -o /dev/null -w '%{http_code}' -X POST "$JENKINS_HTTP$(_jpath "$1")/$2/input/$3/abort"; }

# j_result <job> <n> -> SUCCESS/FAILURE/ABORTED, or empty while running
j_result() { _jcurl "$JENKINS_HTTP$(_jpath "$1")/$2/api/json" | _json "d.get('result') or ''"; }

# j_wait <job> <n> -> echoes the final result
j_wait() {
    local r=""
    for _ in $(seq 1 300); do r=$(j_result "$1" "$2"); [ -n "$r" ] && { echo "$r"; return 0; }; sleep 2; done
    echo TIMEOUT
}

# j_console <job> <n> -> full console text
j_console() { _jcurl "$JENKINS_HTTP$(_jpath "$1")/$2/consoleText"; }
