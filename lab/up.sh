#!/usr/bin/env bash
# Bring up the gitpolicy lab: GitLab CE + Jenkins, users, projects, the
# policy-config GitOps repo, and a first deploy of the policy engine.
# Idempotent - safe to rerun (re-pushes the working tree to
# platform/git-policy so code/pipeline edits reach Jenkins, then redeploys).
set -euo pipefail
cd "$(dirname "$0")"
LAB_DIR=$(pwd)
PROJECT_DIR=$(cd .. && pwd)
if docker compose version >/dev/null 2>&1; then DC=(docker compose); else DC=(docker-compose); fi

GITLAB_HTTP=http://localhost:8940
JENKINS_HTTP=http://localhost:8096

gen() { head -c 64 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c "$1"; }

# ---------------------------------------------------------------- secrets
mkdir -p secrets
if [ ! -f .env ]; then
    ( umask 077; printf 'GITLAB_ROOT_PASSWORD=Gl%s7\n' "$(gen 18)" > .env )
    echo "created .env (GitLab root password)"
fi
grep -q '^DOCKER_GID=' .env || echo "DOCKER_GID=$(stat -c %g /var/run/docker.sock)" >> .env
# Jenkins plugins come from updates.jenkins.io. If it is unreachable, use a
# local Jenkins image that already has all plugins as the base image.
if ! grep -q '^JENKINS_BASE_IMAGE=' .env && ! curl -fsS -m 10 -o /dev/null https://updates.jenkins.io/update-center.json 2>/dev/null; then
    echo "updates.jenkins.io unreachable - looking for a local Jenkins image with the plugins"
    for img in $(docker images --format '{{.Repository}}:{{.Tag}}' | grep -i jenkins | grep -v '<none>'); do
        if docker run -i --rm --entrypoint sh "$img" -c 'cd /usr/share/jenkins/ref/plugins 2>/dev/null || exit 1
                for p in $(cat); do [ -e "$p.jpi" ] || [ -e "$p.hpi" ] || exit 1; done' < jenkins/plugins.txt 2>/dev/null; then
            echo "JENKINS_BASE_IMAGE=$img" >> .env; echo "   using $img"; break
        fi
    done
    grep -q '^JENKINS_BASE_IMAGE=' .env || { echo "ERROR: no local image has the plugins; set JENKINS_BASE_IMAGE in lab/.env" >&2; exit 1; }
fi
if [ ! -f secrets/jenkins.env ]; then
    ( umask 077
      printf 'JENKINS_ADMIN_PASSWORD=Ad%s1\nDEV1_PASSWORD=Dv%s1\nDEV2_PASSWORD=Dv%s2\n' \
        "$(gen 14)" "$(gen 14)" "$(gen 14)" > secrets/jenkins.env )
    echo "created secrets/jenkins.env (Jenkins + GitLab user passwords)"
fi
if [ ! -f secrets/gitlab-bot-token ]; then
    ( umask 077; printf 'glpat-gp%s' "$(gen 20)" > secrets/gitlab-bot-token )
fi
chmod 0600 secrets/gitlab-bot-token   # Jenkins (uid 1000) must read it
[ "$(id -u)" = 1000 ] || echo "WARNING: you are not uid 1000 - Jenkins may not be able to read secrets/gitlab-bot-token"
set -a; . ./.env; . secrets/jenkins.env; set +a
BOT_TOKEN=$(cat secrets/gitlab-bot-token)
# Personal API tokens of the lab users (for tests/e2e and trying the API by hand)
for u in dev1 dev2; do
    [ -f "secrets/$u-token" ] || ( umask 077; printf 'glpat-%s%s' "$u" "$(gen 20)" > "secrets/$u-token" )
done
DEV1_TOKEN=$(cat secrets/dev1-token); DEV2_TOKEN=$(cat secrets/dev2-token)

# ----------------------------------------------------------------- gitlab
echo "==> starting GitLab (first start takes several minutes)"
"${DC[@]}" up -d gitlab
until [ "$(docker inspect -f '{{.State.Health.Status}}' gpp-gitlab)" = healthy ]; do sleep 10; printf '.'; done; echo " GitLab healthy"

echo "==> GitLab: users, groups, projects (idempotent)"
docker exec -i gpp-gitlab gitlab-rails runner - <<RUBY
org = Organizations::Organization.default_organization rescue nil
admin = User.find_by_username('root')

def ensure_user(admin, org, username, name, password, is_admin: false)
  u = User.find_by_username(username)
  unless u
    u = Users::CreateService.new(admin, {
      username: username, name: name, email: "#{username}@gitpolicy.local",
      password: password, password_confirmation: password, skip_confirmation: true,
      organization_id: org&.id
    }.compact).execute.payload[:user]
    raise "user #{username} not created" unless u&.persisted?
  end
  u.update!(password: password, password_confirmation: password, password_automatically_set: false) unless u.valid_password?(password)
  u.update!(admin: true) if is_admin && !u.admin?
  u.update!(password_expires_at: nil) if u.password_expires_at  # no forced change at first login
  u
end

bot  = ensure_user(admin, org, 'jenkins-bot', 'Jenkins Bot', SecureRandom.hex(24) + 'Aa1!', is_admin: true)
dev1 = ensure_user(admin, org, 'dev1', 'Developer One', '${DEV1_PASSWORD}')
dev2 = ensure_user(admin, org, 'dev2', 'Developer Two', '${DEV2_PASSWORD}')
{ dev1 => '${DEV1_TOKEN}', dev2 => '${DEV2_TOKEN}' }.each do |u, tok|
  next if u.personal_access_tokens.active.where(name: 'lab').exists?
  t = u.personal_access_tokens.create!(name: 'lab', scopes: [:api], expires_at: 300.days.from_now)
  t.set_token(tok); t.save!
end
unless bot.personal_access_tokens.active.where(name: 'gitpolicy').exists?
  t = bot.personal_access_tokens.create!(name: 'gitpolicy', scopes: [:api, :read_repository, :write_repository], expires_at: 300.days.from_now)
  t.set_token('${BOT_TOKEN}'); t.save!
end

def ensure_group(admin, org, path)
  g = Group.find_by_full_path(path)
  return g if g
  r = Groups::CreateService.new(admin, { name: path, path: path, visibility_level: 0, organization_id: org&.id }.compact).execute
  g = r.respond_to?(:payload) ? r.payload[:group] : r
  raise "group #{path} not created" unless g&.persisted?
  g
end

def ensure_project(admin, group, name)
  p = Project.find_by_full_path("#{group.full_path}/#{name}")
  return p if p
  p = Projects::CreateService.new(admin, { name: name, path: name, namespace_id: group.id, visibility_level: 0, initialize_with_readme: false }).execute
  raise "project #{name}: #{p.errors.full_messages.join(', ')}" unless p.persisted?
  p
end

platform = ensure_group(admin, org, 'platform')
demo = ensure_group(admin, org, 'demo')
%w[git-policy policy-config].each { |n| ensure_project(admin, platform, n) }
a = ensure_project(admin, demo, 'app-a')
b = ensure_project(admin, demo, 'app-b')
platform.add_member(bot, :maintainer) unless platform.members.exists?(user_id: bot.id)
{ a => { dev1 => :maintainer, dev2 => :developer }, b => { dev2 => :maintainer, dev1 => :developer } }.each do |proj, members|
  members.each { |u, role| proj.add_member(u, role) unless proj.members.exists?(user_id: u.id) }
end
puts "gitlab objects ok"
RUBY

# Push a directory's content as the single tree of <group/repo>'s main branch.
#   push_tree <group/repo> <src_dir> <message> [only_if_empty]
push_tree() {
    local repo=$1 src=$2 msg=$3 only_if_empty=${4:-}
    local url="http://jenkins-bot:${BOT_TOKEN}@localhost:8940/${repo}.git"
    local tmp; tmp=$(mktemp -d)
    if git clone -q "$url" "$tmp/r" 2>/dev/null && [ -n "$(git -C "$tmp/r" rev-parse -q --verify HEAD 2>/dev/null)" ]; then
        if [ -n "$only_if_empty" ]; then rm -rf "$tmp"; echo "   $repo: already seeded, left as is"; return; fi
    else
        rm -rf "$tmp/r"; git init -q -b main "$tmp/r"; git -C "$tmp/r" remote add origin "$url"
    fi
    find "$tmp/r" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
    cp -a "$src"/. "$tmp/r"/
    git -C "$tmp/r" add -A
    if git -C "$tmp/r" -c user.name="lab seed" -c user.email=seed@gitpolicy.local commit -q -m "$msg" 2>/dev/null; then
        git -C "$tmp/r" push -q origin HEAD:main
        echo "   $repo: pushed"
    else
        echo "   $repo: unchanged"
    fi
    rm -rf "$tmp"
}

echo "==> seeding repositories"
SRC=$(mktemp -d)
tar -C "$PROJECT_DIR" --exclude=.git --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache \
    --exclude=lab/.env --exclude=lab/secrets -cf - . | tar -C "$SRC" -xf -
push_tree platform/git-policy "$SRC" "lab: sync engine + pipelines from the working tree"
rm -rf "$SRC"
push_tree platform/policy-config "$PROJECT_DIR/policy-config" "Initial policy repository" only_if_empty
push_tree demo/app-a "$LAB_DIR/seed/app" "Initial commit" only_if_empty
push_tree demo/app-b "$LAB_DIR/seed/app" "Initial commit" only_if_empty

# ---------------------------------------------------------------- jenkins
echo "==> starting Jenkins"
"${DC[@]}" up -d --build jenkins
until curl -fsS -o /dev/null "$JENKINS_HTTP/login" 2>/dev/null; do sleep 5; printf '.'; done; echo " Jenkins up"
# Jobs created by JCasC while Jenkins is still loading can be missing until
# the next start - restart once if so.
sleep 5
if ! curl -fsS -u "admin:$JENKINS_ADMIN_PASSWORD" "$JENKINS_HTTP/job/policy-admin/job/deploy/api/json" >/dev/null 2>&1; then
    docker restart gpp-jenkins >/dev/null
    until curl -fsS -o /dev/null "$JENKINS_HTTP/login" 2>/dev/null; do sleep 5; printf '.'; done
    echo " Jenkins restarted (jobs registered)"
fi

echo "==> running policy-admin/deploy (installs the hook on GitLab, generates the user jobs)"
if "$LAB_DIR/jenkins-run.sh" admin "$JENKINS_ADMIN_PASSWORD" policy-admin/deploy > "$LAB_DIR/secrets/last-deploy.log" 2>&1; then
    echo "   deploy: SUCCESS"
else
    tail -40 "$LAB_DIR/secrets/last-deploy.log"; echo "   deploy: FAILED (full log: lab/secrets/last-deploy.log)"; exit 1
fi

cat <<MSG

Lab is up.
  GitLab   $GITLAB_HTTP
     root        / $GITLAB_ROOT_PASSWORD   (GitLab admin)
     dev1        / $DEV1_PASSWORD   (maintainer of demo/app-a, developer of demo/app-b)
     dev2        / $DEV2_PASSWORD   (maintainer of demo/app-b, developer of demo/app-a)
  Jenkins  $JENKINS_HTTP
     admin       / $JENKINS_ADMIN_PASSWORD   (everything)
     dev1 / dev2 - same passwords as in GitLab (only the "Git Policy" folder)
  API tokens:    lab/secrets/dev1-token, lab/secrets/dev2-token, lab/secrets/gitlab-bot-token (admin)
  Policy repo:   $GITLAB_HTTP/platform/policy-config
  Try: Jenkins > Git Policy > load-profile  (PROJECT=demo/app-a, PROFILE=no-binaries@1)
MSG
