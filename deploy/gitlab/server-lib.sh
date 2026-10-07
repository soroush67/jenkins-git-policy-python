# Functions executed ON the GitLab server (as root) by deploy/push.sh.
# Works for GitLab Omnibus on a host and for the gitlab/gitlab-ce container.
set -euo pipefail

GP_HOME=${GP_HOME:-/opt/gitpolicy}                    # engine code
GP_ETC=${GP_ETC:-/etc/gitpolicy}                      # active bundle
GP_LOG=${GP_LOG:-/var/log/gitlab/gitpolicy}           # audit log
GP_HOOKS_DIR=${GP_HOOKS_DIR:-/var/opt/gitlab/gitaly/custom_hooks}
GP_HOOK=$GP_HOOKS_DIR/pre-receive.d/50-gitpolicy
GP_PY=${GP_PY:-/opt/gitlab/embedded/bin/python3}
GP_GIT_USER=${GP_GIT_USER:-git}

gp_python() {
    [ -x "$GP_PY" ] || GP_PY=$(command -v python3 || true)
    [ -n "$GP_PY" ] || { echo "ERROR: no python3 on the GitLab server" >&2; exit 1; }
}

gp_check_gitaly() {
    # Gitaly only runs global hooks from its configured custom_hooks_dir.
    local cfg=/var/opt/gitlab/gitaly/config.toml
    if [ -f "$cfg" ] && ! grep -Eq "custom_hooks_dir *= *[\"']$GP_HOOKS_DIR[\"']" "$cfg"; then
        echo "ERROR: Gitaly does not use $GP_HOOKS_DIR for server hooks." >&2
        echo "  add to /etc/gitlab/gitlab.rb:" >&2
        echo "    gitaly['configuration'] = { hooks: { custom_hooks_dir: '$GP_HOOKS_DIR' } }" >&2
        echo "  then run: gitlab-ctl reconfigure" >&2
        exit 1
    fi
}

gp_install_code() {   # $1 = directory containing gitpolicy/ and deploy/gitlab/
    local src=$1
    gp_python
    gp_check_gitaly
    install -d -m 0755 "$GP_HOME" "$GP_ETC" "$GP_HOOKS_DIR/pre-receive.d"
    install -d -m 0750 -o "$GP_GIT_USER" -g "$GP_GIT_USER" "$GP_LOG"
    # replace the package atomically: new copy next to it, then rename
    rm -rf "$GP_HOME/gitpolicy.new"
    cp -r "$src/gitpolicy" "$GP_HOME/gitpolicy.new"
    find "$GP_HOME/gitpolicy.new" -name '__pycache__' -prune -exec rm -rf {} +
    chmod -R a+rX,go-w "$GP_HOME/gitpolicy.new"
    rm -rf "$GP_HOME/gitpolicy.old"
    [ -d "$GP_HOME/gitpolicy" ] && mv "$GP_HOME/gitpolicy" "$GP_HOME/gitpolicy.old"
    mv "$GP_HOME/gitpolicy.new" "$GP_HOME/gitpolicy"
    rm -rf "$GP_HOME/gitpolicy.old"
    sed "s#@PYTHON@#$GP_PY#; s#@HOME@#$GP_HOME#; s#@ETC@#$GP_ETC#; s#@LOG@#$GP_LOG#" \
        "$src/deploy/gitlab/pre-receive.in" > "$GP_HOOK.tmp"
    chmod 0755 "$GP_HOOK.tmp"
    mv "$GP_HOOK.tmp" "$GP_HOOK"
    echo "gitpolicy code installed: $GP_HOME/gitpolicy ($("$GP_PY" -c "import sys; sys.path.insert(0,'$GP_HOME'); import gitpolicy; print(gitpolicy.__version__)"))"
    echo "hook installed: $GP_HOOK"
}

gp_install_bundle() {   # $1 = new bundle.json
    local new=$1
    gp_python
    install -d -m 0755 "$GP_ETC"
    # refuse a bundle the engine cannot read (never activate a broken policy)
    PYTHONPATH="$GP_HOME" "$GP_PY" -m gitpolicy doctor --bundle "$new" >/dev/null || {
        PYTHONPATH="$GP_HOME" "$GP_PY" -m gitpolicy doctor --bundle "$new" >&2 || true
        echo "ERROR: bundle rejected by the engine, active policy unchanged" >&2
        exit 1
    }
    [ -f "$GP_ETC/bundle.json" ] && cp -p "$GP_ETC/bundle.json" "$GP_ETC/bundle.json.prev"
    install -m 0644 "$new" "$GP_ETC/bundle.json.tmp"
    mv "$GP_ETC/bundle.json.tmp" "$GP_ETC/bundle.json"
    echo "bundle activated: $GP_ETC/bundle.json"
}

gp_fetch_bundle() {
    [ -f "$GP_ETC/bundle.json" ] && cat "$GP_ETC/bundle.json" || true
}

gp_rollback_bundle() {
    [ -f "$GP_ETC/bundle.json.prev" ] || { echo "ERROR: no previous bundle" >&2; exit 1; }
    cp -p "$GP_ETC/bundle.json" "$GP_ETC/bundle.json.rolledback" 2>/dev/null || true
    cp -p "$GP_ETC/bundle.json.prev" "$GP_ETC/bundle.json"
    echo "previous bundle re-activated"
}

gp_doctor() {
    gp_python
    gp_check_gitaly
    PYTHONPATH="$GP_HOME" "$GP_PY" -m gitpolicy doctor --bundle "$GP_ETC/bundle.json" --hook "$GP_HOOK"
}

gp_uninstall() {
    rm -f "$GP_HOOK"
    echo "hook removed ($GP_HOOK); code ($GP_HOME) and bundle ($GP_ETC) left in place"
}
