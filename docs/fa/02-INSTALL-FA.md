<div dir="rtl">

# نصب و راه‌اندازی: از صفر تا نصب نهایی

این سند سه مرحله دارد:

1. **محیط توسعه:** گرفتن کد و اجرای تست‌ها (۵ دقیقه).
2. **lab محلی:** یک GitLab و یک Jenkins مستقل با docker compose، همه‌چیز خودکار (حدود ۱۰ دقیقه).
3. **نصب نهایی (production):** روی GitLab و Jenkins واقعی سازمان، قدم به قدم.

---

## بخش ۱: محیط توسعه و تست‌ها

**پیش‌نیاز:** لینوکس (یا WSL2)، `git`، `python3` نسخه‌ی ۳.۹ یا بالاتر، و `docker` (برای lab).

<div dir="ltr">

```bash
git clone https://github.com/soroush67/jenkins-git-policy-python.git
cd jenkins-git-policy-python

python3 -m venv .venv
.venv/bin/pip install pytest pyyaml

.venv/bin/python -m pytest -q          # 94 tests, ~5 seconds
```

</div>

تست‌ها روی **git واقعی** اجرا می‌شوند. یک مخزن bare به عنوان «سرور» ساخته می‌شود که hook همین پروژه روی آن نصب است، و push های واقعی به آن انجام می‌شود. پس همان مسیر کدی که داخل GitLab اجرا می‌شود اینجا هم تست می‌شود: quarantine، merge، squash، force push، ساختن و حذف برنچ.

| فایل تست | چه چیزی را پوشش می‌دهد |
|---|---|
| `tests/test_hook_push.py` | ۲۲ سناریوی push واقعی، از جمله «باینری قبل از پروفایل push شده و نباید merge شود» |
| `tests/test_config.py` | validate، کامپایل، تغییرناپذیری (در برابر bundle و در برابر git)، load کردن پروفایل، CLI |
| `tests/test_units.py` | الگوی مسیرها، واحدهای حجم، اعتبارسنجی قوانین، اولویت انتساب‌ها |
| `tests/e2e/lab-e2e.sh` | تست سرتاسری روی lab واقعی (بخش ۲): ۲۷ بررسی |

دستورهای مفید CLI:

<div dir="ltr">

```bash
.venv/bin/python -m gitpolicy validate policy-config      # validate the sample GitOps repo
.venv/bin/python -m gitpolicy show policy-config          # profiles + assignments
.venv/bin/python -m gitpolicy describe-rules              # rule types and parameters
.venv/bin/python -m gitpolicy --help
```

</div>

---

## بخش ۲: lab محلی (GitLab و Jenkins مستقل)

### ۲-۱. بالا آوردن

<div dir="ltr">

```bash
cd lab
./up.sh
```

</div>

`up.sh` این کارها را انجام می‌دهد. اسکریپت idempotent است و اجرای دوباره‌اش بی‌خطر است:

1. رمزها را به صورت تصادفی می‌سازد و در `lab/.env` و `lab/secrets/` ذخیره می‌کند. این فایل‌ها در git نیستند.
2. **GitLab CE 17.10.5** را روی پورت **8940** بالا می‌آورد. تنظیم `custom_hooks_dir` برای server hookهای سراسری هم در خود compose هست.
3. در GitLab این‌ها را می‌سازد:
   - کاربرها: `dev1` و `dev2`، و `jenkins-bot` (ادمین، صاحب توکن Jenkins)
   - گروه `platform` با پروژه‌های `git-policy` (کد همین پروژه) و `policy-config` (مخزن GitOps)
   - گروه `demo` با پروژه‌های `app-a` و `app-b`
4. **Jenkins** را روی پورت **8096** build و اجرا می‌کند. تنظیماتش کاملاً با JCasC در `lab/jenkins/casc.yaml` است.
5. job `policy-admin/deploy` را اجرا می‌کند. این job هم hook و موتور را روی GitLab نصب می‌کند و هم jobهای کاربر را می‌سازد.

در پایان، اطلاعات ورود را چاپ می‌کند (رمزها در هر نصب تصادفی‌اند):

<div dir="ltr">

```
Lab is up.
  GitLab   http://localhost:8940
     root        / Gl...   (GitLab admin)
     dev1        / Dv...   (maintainer of demo/app-a, developer of demo/app-b)
     dev2        / Dv...   (maintainer of demo/app-b, developer of demo/app-a)
  Jenkins  http://localhost:8096
     admin       / Ad...   (everything)
     dev1 / dev2 - same passwords as in GitLab (only the "Git Policy" folder)
  API tokens:    lab/secrets/dev1-token, lab/secrets/dev2-token, lab/secrets/gitlab-bot-token (admin)
```

</div>

اطلاعات ورود را بعداً هم می‌توانید ببینید:

<div dir="ltr">

```bash
cat lab/.env lab/secrets/jenkins.env
```

</div>

> **شبکه‌ی محدود:** اگر `updates.jenkins.io` در دسترس نباشد، `up.sh` خودش دنبال یک image محلی جنکینز می‌گردد که پلاگین‌های لازم را داشته باشد و آن را به عنوان image پایه انتخاب می‌کند (`JENKINS_BASE_IMAGE` در `lab/.env`). اگر چنین imageی پیدا نکند، می‌توانید این متغیر را دستی تنظیم کنید.

### ۲-۲. حساب‌های کاربری و دسترسی‌ها در lab

| سیستم | کاربر | نقش |
|---|---|---|
| GitLab | `root` | ادمین GitLab |
| GitLab | `dev1` | Maintainer پروژه‌ی `demo/app-a` و Developer پروژه‌ی `demo/app-b` |
| GitLab | `dev2` | Maintainer پروژه‌ی `demo/app-b` و Developer پروژه‌ی `demo/app-a` |
| GitLab | `jenkins-bot` | ادمین. توکنش در Jenkins با شناسه‌ی credential به نام `gitlab-bot` ذخیره شده است |
| Jenkins | `admin` | همه‌چیز |
| Jenkins | `dev1`، `dev2` | فقط پوشه‌ی **Git Policy**، یعنی jobهای `load-profile` و `show`، با دسترسی Read و Build |

### ۲-۳. امتحان کردن دستی

1. با `dev1` وارد Jenkins (`http://localhost:8096`) شوید، پوشه‌ی **Git Policy** و بعد job **load-profile** را باز کنید و **Build with Parameters** را بزنید:
   `PROJECT=demo/app-a`، `PROFILE=no-binaries@1`.
2. یک باینری push کنید:

<div dir="ltr">

```bash
git clone http://dev1:<password>@localhost:8940/demo/app-a.git && cd app-a
head -c 4096 /dev/urandom > tool.bin && git add tool.bin && git commit -m "add tool"
git push      # -> remote: gitpolicy: push REJECTED by profile no-binaries@1 ...
```

</div>

3. یا همه‌ی سناریوها را یکجا اجرا کنید:

<div dir="ltr">

```bash
samples/try-it.sh demo/app-a
```

</div>

4. سناریوی «باینری‌ای که قبلاً push شده نباید merge شود»: با `dev2` در `demo/app-b` (که هنوز پروفایل ندارد) یک باینری را در یک feature branch push کنید. بعد پروفایل را load کنید و در GitLab یک MR بسازید و Merge را بزنید. merge انجام نمی‌شود و علت رد شدن روی صفحه‌ی MR نشان داده می‌شود.

### ۲-۴. تست سرتاسری خودکار

<div dir="ltr">

```bash
tests/e2e/lab-e2e.sh       # 27 checks; rerunnable
```

</div>

این تست موارد زیر را بررسی می‌کند:
- دسترسی‌های Jenkins
- load کردن پروفایل توسط Maintainer، و رد شدن درخواست Developer، پروژه‌ی ناموجود و تعویض بدون `REPLACE_EXISTING`
- رد شدن push باینری و پسوند ممنوع
- رد شدن commit وب یا API
- رد شدن merge در MR از دو مسیر API و UI، همراه با نمایش پیام روی صفحه‌ی MR
- رد شدن کپی برنچ آلوده
- محافظت مخزن policy-config از خودش
- ظاهر شدن پروفایل جدید در لیست کشویی
- ثبت در audit log

### ۲-۵. خاموش کردن و پاک کردن lab

<div dir="ltr">

```bash
lab/down.sh            # stop (data kept)
lab/down.sh --wipe     # stop + delete all lab data and generated passwords
```

</div>

---

## بخش ۳: نصب نهایی (production)، نمای کلی

| قدم | کجا | خلاصه |
|---|---|---|
| ۱ | GitLab | فعال کردن global server hooks (`custom_hooks_dir`) |
| ۲ | GitLab | ساختن کاربر سرویس `jenkins-bot` و توکن آن |
| ۳ | GitLab | ساختن مخزن‌های `platform/git-policy` و `platform/policy-config` و محافظت از آن‌ها |
| ۴ | Jenkins | پلاگین‌ها، agent دارای python3، credential، متغیرهای محیطی، دسترسی‌ها و job استقرار |
| ۵ | Jenkins به GitLab | راه انتقال (SSH) |
| ۶ | Jenkins | اولین deploy و بررسی سلامت |
| ۷ | سازمان | rollout تدریجی |

### قدم ۱: فعال کردن server hookها در GitLab

روی سرور GitLab (Omnibus)، در فایل `/etc/gitlab/gitlab.rb` این خط را بگذارید:

<div dir="ltr">

```ruby
gitaly['configuration'] = { hooks: { custom_hooks_dir: '/var/opt/gitlab/gitaly/custom_hooks' } }
```

</div>

> اگر `gitaly['configuration']` از قبل تنظیمات دیگری دارد، فقط کلید `hooks:` را به همان hash اضافه کنید و آن را دوباره تعریف نکنید.

<div dir="ltr">

```bash
sudo gitlab-ctl reconfigure
grep custom_hooks_dir /var/opt/gitlab/gitaly/config.toml   # must print the path
```

</div>

GitLab داکری: همین خط را در `GITLAB_OMNIBUS_CONFIG` اضافه کنید (مثل `lab/docker-compose.yml`) یا داخل container در `gitlab.rb` بگذارید و `gitlab-ctl reconfigure` بزنید.

**پیش‌نیاز پایتون:** موتور با پایتونی که داخل خود GitLab هست کار می‌کند (`/opt/gitlab/embedded/bin/python3`، نسخه‌ی ۳.۹ در GitLab 17) و به هیچ پکیج اضافه‌ای نیاز ندارد.

### قدم ۲: کاربر سرویس و توکن

یک کاربر `jenkins-bot` بسازید و برایش Personal Access Token بسازید (Admin، سپس Users، سپس jenkins-bot، سپس Access Tokens):
- **Scopes:** `api` (یا `read_api` به همراه `read_repository` و `write_repository`)
- **چرا ادمین؟** job `load-profile` نقش کاربر را در **هر پروژه‌ای** از GitLab می‌پرسد (`/projects/:id/members/all/:user`). برای پروژه‌های private این کار فقط برای ادمین یا عضو آن گروه ممکن است. اگر نمی‌خواهید bot ادمین باشد، آن را با نقش **Reporter** عضو همه‌ی گروه‌هایی کنید که قرار است پروفایل بگیرند.
- توکن تاریخ انقضا دارد. تاریخ تمدیدش را در تقویم تیم ثبت کنید.

### قدم ۳: مخزن‌ها در GitLab

<div dir="ltr">

```bash
# 1) the engine + pipelines (this project)
git clone https://github.com/soroush67/jenkins-git-policy-python.git
cd jenkins-git-policy-python
git remote add company https://gitlab.company.com/platform/git-policy.git
git push company main

# 2) the GitOps policy repository, seeded from the sample
mkdir /tmp/policy-config && cp -a policy-config/. /tmp/policy-config/ && cd /tmp/policy-config
git init -b main && git add -A && git commit -m "Initial policy repository"
git remote add origin https://gitlab.company.com/platform/policy-config.git
git push -u origin main
```

</div>

**محافظت از مخزن‌ها:** در هر دو پروژه بروید به Settings، سپس Repository، سپس Protected branches، و برای `main` تنظیم کنید:
- **Allowed to push:** فقط Maintainerها، یعنی تیم پلتفرم و `jenkins-bot`
- **Allowed to merge:** Maintainerها
- عضوهای گروه `platform` را محدود به تیم پلتفرم نگه دارید.

نمونه‌ی `settings.yaml` گروه `platform/*` را قفل کرده (`locked_projects`) و `assignments.yaml` پروفایل `policy-config-guard@1` را به مخزن policy-config نسبت داده است. پس از اولین deploy، فایل‌های منتشرشده‌ی پروفایل حتی با push مستقیم هم قابل تغییر نیستند.

### قدم ۴: Jenkins

**۴-الف. پلاگین‌ها** (فهرست در `lab/jenkins/plugins.txt`):

<div dir="ltr">

```
configuration-as-code workflow-aggregator pipeline-stage-view git credentials
credentials-binding job-dsl cloudbees-folder role-strategy lockable-resources timestamper
```

</div>

**۴-ب. agent:** jobها روی nodeی با label به نام `gitpolicy` اجرا می‌شوند که این‌ها را داشته باشد:

<div dir="ltr">

```bash
# Debian/Ubuntu agent
sudo apt-get install -y python3 python3-yaml python3-pytest git openssh-client
```

</div>

**۴-ج. credential:** از مسیر Manage Jenkins، Credentials، System، Global، یک credential از نوع *Username with password* بسازید:
- ID: `gitlab-bot`
- Username: `jenkins-bot`
- Password: توکن قدم ۲

**۴-د. متغیرهای محیطی:** از مسیر Manage Jenkins، System، Global properties، Environment variables. در lab این‌ها با JCasC تنظیم شده‌اند:

| متغیر | مقدار نمونه | توضیح |
|---|---|---|
| `GP_TOOL_REPO` | `https://gitlab.company.com/platform/git-policy.git` | کد موتور و pipelineها |
| `GP_CONFIG_REPO` | `https://gitlab.company.com/platform/policy-config.git` | مخزن GitOps |
| `GP_BRANCH` | `main` | |
| `GP_GIT_CRED` | `gitlab-bot` | شناسه‌ی credential |
| `GP_TARGET` | `ssh:gitpolicy-deploy@gitlab.company.com` | راه انتقال به سرور GitLab (قدم ۵) |
| `GP_REQUIRE_ROLE` | `maintainer` | حداقل نقش GitLab برای load کردن پروفایل (`developer`، `maintainer` یا `owner`) |
| `GITLAB_URL` | `https://gitlab.company.com` | آدرس API |

**۴-ه. Job DSL:** از مسیر Manage Jenkins، Security، گزینه‌ی *Enable script security for Job DSL scripts* را **خاموش** کنید. اسکریپت `jenkins/jobs.groovy` فقط از مخزن ادمین (`platform/git-policy`) و فقط در job ادمین اجرا می‌شود.

**۴-و. دسترسی‌ها (Role-based Strategy):** نمونه‌ی کامل در `lab/jenkins/casc.yaml` هست:
- نقش global به نام `authenticated-read` با دسترسی `Overall/Read` برای گروه `authenticated`
- نقش item به نام `policy-user` با الگوی `policy(/.*)?` و دسترسی‌های `Job/Read` و `Job/Build` برای گروه `authenticated`، یا گروه LDAP توسعه‌دهنده‌ها
- پوشه‌ی `policy-admin` فقط برای ادمین‌ها

> **مهم:** نام کاربری Jenkins باید با نام کاربری GitLab یکی باشد. وقتی هر دو به یک LDAP یا AD وصل باشند، این شرط خودبه‌خود برقرار است.

**۴-ز. job استقرار:** فقط همین یک job را دستی (یا با JCasC) بسازید. بقیه‌ی jobها را خودش می‌سازد:
- New Item، نام `policy-admin`، نوع Folder
- داخل آن: New Item، نام `deploy`، نوع Pipeline
- Definition: *Pipeline script from SCM*، SCM: Git، Repository: `GP_TOOL_REPO`، Credentials: `gitlab-bot`، Branch: `*/main`، Script Path: `jenkins/Jenkinsfile.deploy`

همین تنظیم را می‌توانید از بخش `jobs:` در `lab/jenkins/casc.yaml` کپی کنید.

### قدم ۵: راه انتقال Jenkins به سرور GitLab

`deploy/push.sh` سه نوع `GP_TARGET` را می‌شناسد:

| `GP_TARGET` | حالت | پیش‌نیاز |
|---|---|---|
| `docker:<container>` | GitLab داکری روی همان ماشین Jenkins (lab) | دسترسی Jenkins به docker socket |
| `ssh:<user@host>` | GitLab Omnibus روی سرور | کاربر SSH با `sudo` بدون رمز |
| `ssh-docker:<user@host>:<container>` | GitLab داکری روی سرور دیگر | کاربر SSH عضو گروه `docker` |

نمونه برای `ssh:`:

<div dir="ltr">

```bash
# on the GitLab server
sudo useradd -m -s /bin/bash gitpolicy-deploy
echo 'gitpolicy-deploy ALL=(root) NOPASSWD: /bin/bash -s, /usr/bin/bash -s' | sudo tee /etc/sudoers.d/gitpolicy-deploy
sudo chmod 0440 /etc/sudoers.d/gitpolicy-deploy
sudo -u gitpolicy-deploy mkdir -p -m 700 /home/gitpolicy-deploy/.ssh
# append the PUBLIC key of the Jenkins agent user to:
#   /home/gitpolicy-deploy/.ssh/authorized_keys

# on the Jenkins agent (as the user that runs the builds)
ssh-keygen -t ed25519 -N '' -f ~/.ssh/id_ed25519      # if it has no key yet
ssh gitpolicy-deploy@gitlab.company.com true             # accept the host key once
```

</div>

> **وضعیت تست:** حالت `docker:` در lab به طور کامل تست شده است (تست e2e). حالت‌های `ssh:` و `ssh-docker:` دقیقاً همان اسکریپت را از راه دیگری اجرا می‌کنند (`ssh ... sudo bash -s` یا `ssh ... docker exec -i ... bash -s`)، ولی در lab تست نشده‌اند. اولین deploy را با دقت دنبال کنید.

> **امنیت:** این کاربر در عمل دسترسی root روی سرور GitLab دارد، چون `sudo bash -s` یعنی هر اسکریپتی را با root اجرا کند. حالت `ssh-docker` (عضویت در گروه docker) هم همین سطح دسترسی را دارد. کلید SSH را فقط روی agent مخصوص این jobها نگه دارید.

### قدم ۶: اولین deploy و بررسی

job `policy-admin/deploy` را اجرا کنید (Build Now). خروجی موفق شبیه این است:

<div dir="ltr">

```
94 passed in 4.62s
no bundle installed yet (first deploy)
OK: 6 profile version(s), 1 assignment(s)
compiled bundle.json: 6 profile version(s), 1 assignment(s)
  + profile no-binaries@1
  ...
  + platform/policy-config -> policy-config-guard@1
gitpolicy code installed: /opt/gitpolicy/gitpolicy (1.0.0)
hook installed: /var/opt/gitlab/gitaly/custom_hooks/pre-receive.d/50-gitpolicy
bundle activated: /etc/gitpolicy/bundle.json
=> OK
```

</div>

بعد از آن پوشه‌ی **Git Policy** با jobهای `load-profile` و `show` ساخته می‌شود و job `policy-admin/unload-profile` هم اضافه می‌شود.

بررسی دستی روی سرور GitLab:

<div dir="ltr">

```bash
sudo PYTHONPATH=/opt/gitpolicy /opt/gitlab/embedded/bin/python3 -m gitpolicy doctor \
    --bundle /etc/gitpolicy/bundle.json \
    --hook /var/opt/gitlab/gitaly/custom_hooks/pre-receive.d/50-gitpolicy
```

</div>

**تست دود (smoke test):** یک پروژه‌ی آزمایشی بسازید، `no-binaries@1` را برایش load کنید و یک فایل باینری push کنید. push باید رد شود.

### قدم ۷: rollout تدریجی در سازمان (پیشنهاد)

1. **هفته‌ی اول:** یک نسخه از پروفایل بسازید که همه‌ی قوانینش `action: warn` باشد (مثلاً `standard-audit@1`) و آن را روی چند پروژه load کنید. کاربران فقط هشدار می‌بینند و audit log نشان می‌دهد چه چیزهایی رد می‌شد.
2. **بعد از آن:** تیم‌ها نسخه‌ی `block` را load کنند (`standard@1`).
3. **پروژه‌های قدیمی بزرگ:** محتوای قدیمی main دوباره بررسی نمی‌شود. فقط چیزهای جدیدی که وارد برنچ می‌شوند بررسی می‌شوند. پس load کردن پروفایل روی مخزن قدیمی کار روزمره را قفل نمی‌کند.

### به‌روزرسانی موتور

کد جدید را به `platform/git-policy` push کنید. job deploy در poll بعدی (حداکثر ۲ دقیقه) تست‌ها را اجرا می‌کند و کد جدید را نصب می‌کند. نصب کد atomic است و push هایی که در همان لحظه در جریان‌اند آسیبی نمی‌بینند.

### حذف کامل

<div dir="ltr">

```bash
GP_TARGET=ssh:gitpolicy-deploy@gitlab.company.com deploy/push.sh uninstall   # removes the hook
# optional, on the server: sudo rm -rf /opt/gitpolicy /etc/gitpolicy
```

</div>

</div>
