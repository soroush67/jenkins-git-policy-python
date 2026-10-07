#!/usr/bin/env bash
# Deliver gitpolicy to the GitLab server and run actions there.
#
#   GP_TARGET=<transport> deploy/push.sh <action> [arg]
#
# Transports (GP_TARGET):
#   docker:<container>                   GitLab in a local container (lab: docker:gpp-gitlab)
#   ssh:<user@host>                      GitLab Omnibus installed on the host (user needs sudo)
#   ssh-docker:<user@host>:<container>   GitLab in a container on a remote host (user in group docker)
#
# Actions:
#   install-code              install/upgrade the engine + the pre-receive hook wrapper
#   install-bundle <file>     validate and atomically activate a compiled bundle.json
#   fetch-bundle <out>        copy the active bundle to <out> (empty file if none)
#   rollback-bundle           re-activate the previous bundle
#   doctor                    health check on the server
#   uninstall                 remove the hook wrapper (policy no longer enforced)
#
# Everything runs as one self-contained script on the server (data embedded
# as base64), so the same code path works over docker exec and ssh.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
TARGET=${GP_TARGET:?set GP_TARGET (e.g. docker:gpp-gitlab)}
ACTION=${1:?usage: push.sh <action> [arg]}

remote() {   # stdin = bash script, run as root on the GitLab server
    case "$TARGET" in
        docker:*)     docker exec -i -u root "${TARGET#docker:}" bash -s ;;
        ssh:*)        ssh -o BatchMode=yes "${TARGET#ssh:}" sudo bash -s ;;
        ssh-docker:*) local rest=${TARGET#ssh-docker:}
                      ssh -o BatchMode=yes "${rest%:*}" docker exec -i -u root "${rest##*:}" bash -s ;;
        *) echo "unknown GP_TARGET transport: $TARGET" >&2; exit 2 ;;
    esac
}

server_lib() { cat "$HERE/gitlab/server-lib.sh"; }

case "$ACTION" in
    install-code)
        payload=$(tar -C "$ROOT" --exclude=__pycache__ -czf - gitpolicy deploy/gitlab | base64 -w0)
        { server_lib; cat <<EOF
tmp=\$(mktemp -d); trap 'rm -rf "\$tmp"' EXIT
echo '$payload' | base64 -d | tar -xzf - -C "\$tmp"
gp_install_code "\$tmp"
EOF
        } | remote ;;
    install-bundle)
        file=${2:?install-bundle <bundle.json>}
        payload=$(base64 -w0 < "$file")
        { server_lib; cat <<EOF
tmp=\$(mktemp); trap 'rm -f "\$tmp"' EXIT
echo '$payload' | base64 -d > "\$tmp"
gp_install_bundle "\$tmp"
EOF
        } | remote ;;
    fetch-bundle)
        out=${2:?fetch-bundle <out>}
        { server_lib; echo 'gp_fetch_bundle'; } | remote > "$out" ;;
    rollback-bundle) { server_lib; echo 'gp_rollback_bundle'; } | remote ;;
    doctor)          { server_lib; echo 'gp_doctor'; } | remote ;;
    uninstall)       { server_lib; echo 'gp_uninstall'; } | remote ;;
    *) echo "unknown action: $ACTION" >&2; exit 2 ;;
esac
