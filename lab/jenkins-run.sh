#!/usr/bin/env bash
# Run a Jenkins job as a user and wait for it (no approval handling):
#   ./jenkins-run.sh <user> <password> <job/path> [curl -F args...]
# Prints the console; exit 0 only if the build result is SUCCESS.
set -euo pipefail
. "$(dirname "$0")/lib.sh"
user=$1 pass=$2 job=$3; shift 3
j_login "$user" "$pass"
n=$(j_trigger "$job" "$@")
result=$(j_wait "$job" "$n")
j_console "$job" "$n"
echo "== $job #$n: $result"
[ "$result" = SUCCESS ]
