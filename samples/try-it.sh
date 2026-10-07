#!/usr/bin/env bash
# Walk through the main scenarios on the lab by hand-sized steps.
#   samples/try-it.sh [project]      (default demo/app-a, as dev1)
# Load a profile first: Jenkins > Git Policy > load-profile.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/../lab/secrets/jenkins.env"
PROJECT=${1:-demo/app-a}
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
"$HERE/make-samples.sh" "$TMP/samples" >/dev/null
git clone -q "http://dev1:$DEV1_PASSWORD@localhost:8940/$PROJECT.git" "$TMP/repo"
cd "$TMP/repo"; git config user.name dev1; git config user.email dev1@gitpolicy.local

try() {   # try <file-in-samples> <path-in-repo>
    mkdir -p "$(dirname "$2")"; cp "$TMP/samples/$1" "$2"; echo "# run $(date +%s%N)" >> "$2"   # unique content
    git add -f "$2"; git commit -qm "chore: add $2"
    echo; echo "### push $2"
    git push origin HEAD:main 2>&1 | grep -E "^remote:|->|rejected" | sed 's/^/   /'
    git reset -q --hard origin/main
}
echo "Pushing sample files to $PROJECT as dev1 - what is rejected depends on the profile loaded"
echo "(no-binaries@1 blocks binaries/size; standard@1 also blocks .env and secrets)."
try ok.txt "ok-$(date +%s).txt"
try random.bin random.bin
try fake-elf tools/fake-elf
try library.dll lib/library.dll
try .env .env
try config.py config.py
try big.txt big.txt
