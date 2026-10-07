<div dir="rtl">

# HANDOFF: خلاصه‌ی کامل پروژه‌ی gitpolicy (نسخه‌ی پایتون)

این فایل را هر جا ببرید، کافی است تا کار را بدون شروع از صفر ادامه دهید. همه‌ی تصمیم‌ها، ساختار، وضعیت تست‌ها، محدودیت‌ها و قدم‌های بعدی در آن آمده است.

- **مخزن:** https://github.com/soroush67/jenkins-git-policy-python
- **مسیر روی ماشین توسعه:** `/home/soroush/infra/jenkins-git-policy-python`
- **تاریخ:** 2026-10-07، نسخه‌ی `1.0.0` (MVP)

---

## ۱. خواسته‌ی اولیه

> یک MVP برای نوشتن policy سازمانی در GitLab، با دست باز در تعریف قوانین. مثلاً فایل باینری push نشود، و اگر push شده، با merge بین برنچ‌ها جابه‌جا نشود. هر policy یک **profile** باشد و پروفایل‌ها روی هم overwrite نشوند. سرویس با Jenkins و GitLab به صورت **GitOps** مدیریت شود. من پروفایل را می‌سازم و به کاربر می‌گویم آن را load کند. مستند فارسی روان از نصب تا نصب نهایی، زبان Python، تست، نمونه‌ها، GitLab و Jenkins مستقل برای پروژه، و push به GitHub.

## ۲. تصمیم‌هایی که با کاربر گرفته شد

| سؤال | تصمیم |
|---|---|
| کاربر پروفایل را چطور load می‌کند؟ | با **job Jenkins** (`policy/load-profile`). Jenkins انتساب را در مخزن GitOps commit می‌کند. کاربر نمی‌تواند پروفایل را ویرایش کند |
| معنی «overwrite نشود» | **نسخه‌دار و تغییرناپذیر**: `name@version`. نسخه‌ی منتشرشده هرگز عوض نمی‌شود. هر پروژه دقیقاً یک پروفایل دارد. ارث‌بری و ادغام وجود ندارد |
| محل اجرای policy | **pre-receive hook سراسری** در GitLab (Gitaly). push، merge در MR، squash، commit وب و API را پوشش می‌دهد |
| محیط lab | **docker compose محلی**: GitLab روی پورت 8940 و Jenkins روی پورت 8096. نام‌ها و پورت‌ها با lab‌های دیگر ماشین تداخل ندارند |

تصمیم‌های فنی دیگر:
- موتور hook **فقط از stdlib** استفاده می‌کند و با **Python 3.9** کار می‌کند (پایتون داخل GitLab: `/opt/gitlab/embedded/bin/python3`). پس روی سرور GitLab هیچ پکیجی نصب نمی‌شود.
- YAML فقط در Jenkins خوانده می‌شود (PyYAML). خروجی کامپایل یک `bundle.json` است و hook فقط همین را می‌خواند.
- **قاعده‌ی محدوده‌ی commitها** (هسته‌ی خواسته‌ی «باینری بین برنچ‌ها حرکت نکند»):
  - به‌روزرسانی برنچ: `rev-list new ^old`. **عمداً** `--not --all` استفاده نشده، پس commitهایی که در برنچ دیگری هستند هم بررسی می‌شوند.
  - ساختن برنچ جدید: `rev-list new ^<default-branch>`.
  - merge commit نسبت به parent اول diff می‌شود (`--diff-merges=first-parent`).
- تغییرناپذیری پروفایل در **سه لایه** اجرا می‌شود:
  1. hook روی خود مخزن policy-config (قانون `immutable_paths`)
  2. deploy در برابر sha256 فایل‌ها در bundle نصب‌شده
  3. deploy در برابر تاریخچه‌ی git از `source_commit` آخرین deploy
- `load-profile` نقش **Maintainer** کاربر در GitLab را با API چک می‌کند (`GP_REQUIRE_ROLE`). شرطش این است که نام کاربری Jenkins و GitLab یکی باشد.
- پیش‌فرض `fail_mode: closed` است. `break_glass_users` برای مواقع اضطراری است و در audit log ثبت می‌شود. `locked_projects: [platform/*]` تنظیم شده است.
- پیام‌ها با پیشوند `GL-HOOK-ERR:` برای `GL_PROTOCOL=web` چاپ می‌شوند تا در UI گیت‌لب دیده شوند. تأیید شده که پیام کامل روی صفحه‌ی MR (در `merge_error`) نمایش داده می‌شود.

## ۳. ساختار کد

<div dir="ltr">

```
gitpolicy/
  __init__.py      version, BUNDLE_FORMAT
  globs.py         .gitignore-like path globs, branch/project globs
  gitrepo.py       git plumbing: rev-list, diff-tree -z, cat-file --batch(-check), large-blob streaming
  rules.py         11 rule types + normalize() validation + Violation
  engine.py        Bundle (load/resolve), RefUpdate, evaluate()  <- commit-range logic lives here
  hook.py          pre-receive entry: env GL_*, fail_mode, break-glass, audit log, GL-HOOK-ERR output
  config.py        YAML loading/validation, compile_bundle, immutability checks, assign/unassign
  gitlab.py        GitLab API (project exists, effective member access level)
  cli.py           validate | compile | diff | assign | unassign | list-profiles | show |
                   describe-rules | gitlab-check | hook | check (dry-run) | doctor
policy-config/     sample GitOps repo: settings.yaml, assignments.yaml, 6 profile versions
jenkins/           Jenkinsfile.deploy | .load-profile | .show | .unload-profile, jobs.groovy
deploy/push.sh     transport docker:|ssh:|ssh-docker: ; actions install-code, install-bundle,
                   fetch-bundle, rollback-bundle, doctor, uninstall
deploy/gitlab/     server-lib.sh (runs as root on GitLab), pre-receive.in (hook wrapper)
lab/               docker-compose.yml, up.sh, down.sh, lib.sh (Jenkins REST), jenkins/ (Dockerfile, casc, plugins)
samples/           profiles/company-java.yaml, monorepo-paths.yaml, make-samples.sh, try-it.sh
tests/             conftest.py (bare repo + real hook), test_hook_push.py, test_config.py,
                   test_units.py, e2e/lab-e2e.sh
docs/fa/           01-OVERVIEW, 02-INSTALL, 03-PROFILES, 04-USER-GUIDE, 05-OPERATIONS
tools/rtl.py       wraps Persian Markdown in <div dir="rtl"> (code blocks ltr)
```

</div>

**نوع قوانین:** `binary_files`، `forbidden_extensions`، `forbidden_paths`، `max_file_size`، `secret_patterns`، `immutable_paths`، `commit_message`، `author_email`، `branch_name`، `no_force_push`، `no_branch_delete`. هر قانون فیلدهای `action` (block یا warn)، `branches` و `message` هم دارد.

**افزودن نوع قانون جدید:** یک کلاس در `rules.py` بسازید که از `Rule` ارث ببرد و `TYPE`، `PARAMS` و یکی از callbackهای `check_ref`، `check_commit` یا `check_change` را داشته باشد. بعد کلاس را به `RULE_TYPES` اضافه و تستش را در `tests/test_hook_push.py` بنویسید.

## ۴. جریان کار (GitOps)

1. ادمین فایل `profiles/<name>/<n>.yaml` را به `platform/policy-config` push می‌کند.
2. `policy-admin/deploy` (با poll هر ۲ دقیقه) این مراحل را اجرا می‌کند:
   - pytest
   - گرفتن bundle نصب‌شده از GitLab
   - `validate --previous` به همراه `--git-base`
   - `compile`
   - `push.sh install-code` و `install-bundle` (که bundle را قبل از فعال‌سازی روی خود سرور با doctor چک می‌کند)
   - `doctor`
   - Job DSL، که `policy/load-profile` را با لیست به‌روز پروفایل‌ها دوباره می‌سازد
3. کاربر `policy/load-profile` را اجرا می‌کند:
   - `gitlab-check` (وجود پروژه و نقش Maintainer)
   - `assign` (اگر پروژه پروفایل داشته باشد، تعویض فقط با `REPLACE_EXISTING` ممکن است)
   - commit به نام کاربر و push با ۳ بار تلاش مجدد
   - `build policy-admin/deploy`

## ۵. وضعیت تست‌ها (2026-10-07)

| تست | نتیجه |
|---|---|
| `pytest` (unit، تست push با git واقعی، config، CLI) | **۹۴ از ۹۴** پاس شد. job deploy هم در Jenkins همین‌ها را اجرا می‌کند |
| `tests/e2e/lab-e2e.sh` روی lab واقعی | **۲۷ از ۲۷** پاس شد. چند بار اجرای پشت‌سرهم هم مشکلی نداشت |
| `samples/try-it.sh` با `standard@1` | همه‌ی نوع‌ها رد شدند: باینری، ELF، dll، `.env`، کلید AWS، فایل ۱۲ مگابایتی |
| import موتور با Python 3.9.21 داخل GitLab | انجام شد |
| rollback-bundle و redeploy | انجام شد |
| زمان hook | حدود ۱۳ تا ۱۵ میلی‌ثانیه برای هر push کوچک |

موارد کلیدی که در lab واقعی دیده و تأیید شد:
- باینری‌ای که قبل از load شدن پروفایل روی یک feature branch push شده بود: merge آن در MR **رد شد**. پیام gitpolicy در `merge_error` صفحه‌ی MR نمایش داده شد و audit log آن را با `protocol: web` و قانون `no-binary-files` ثبت کرد.
- commit باینری از API یا وب رد شد.
- کپی برنچ آلوده به اسم جدید رد شد. برنچ جدید از main تمیز پذیرفته شد.
- ویرایش `profiles/no-binaries/1.yaml` با push مستقیم توسط hook رد شد.
- dev1 که فقط Developer پروژه‌ی `demo/app-b` است نتوانست برای آن پروفایل load کند.

## ۶. lab و حساب‌ها

<div dir="ltr">

```bash
lab/up.sh        # idempotent; prints all logins at the end
cat lab/.env lab/secrets/jenkins.env    # passwords (random per install, git-ignored)
```

</div>

| سیستم | آدرس | کاربرها |
|---|---|---|
| GitLab | http://localhost:8940 | `root` (ادمین)، `dev1` (Maintainer پروژه‌ی app-a)، `dev2` (Maintainer پروژه‌ی app-b)، `jenkins-bot` (ادمین، توکن در `lab/secrets/gitlab-bot-token`) |
| Jenkins | http://localhost:8096 | `admin`، `dev1` و `dev2` با همان رمزهای GitLab، فقط پوشه‌ی Git Policy |

- containerها: `gpp-gitlab` و `gpp-jenkins`
- پروژه‌ی compose: `gitpolicy-py-lab`
- توکن API کاربرها: `lab/secrets/dev1-token` و `lab/secrets/dev2-token`

**نکته‌های lab:**
- از این شبکه `updates.jenkins.io` در دسترس نبود. `up.sh` خودش image محلی `compose-paas-lab-jenkins:latest` را که همه‌ی پلاگین‌ها را دارد به عنوان پایه انتخاب کرد (`JENKINS_BASE_IMAGE` در `lab/.env`). روی ماشین دیگر با اینترنت آزاد، image رسمی استفاده می‌شود.
- در lab، Jenkins از docker socket استفاده می‌کند (`GP_TARGET=docker:gpp-gitlab`).
- کاربر ادمین در GitLab، در `Group#member?` همیشه true برمی‌گرداند. به همین دلیل عضویت با `members.exists?(user_id:)` چک می‌شود.

## ۷. محدودیت‌ها و کارهای باقی‌مانده

- **حالت‌های `ssh:` و `ssh-docker:` در `push.sh` تست نشده‌اند.** فقط `docker:` در lab تست شده است. اولین نصب production را با دقت دنبال کنید.
- کاربر deploy روی سرور GitLab عملاً دسترسی root دارد (`sudo bash -s`). بهبود ممکن: یک اسکریپت ثابت روی سرور و محدود کردن sudo به همان.
- tagها و refهای غیر برنچ بررسی نمی‌شوند. GitLab LFS هم بررسی نمی‌شود (pointer متنی است).
- برای audit log هنوز logrotate تنظیم نشده است.
- `load-profile` فرض می‌کند نام کاربری Jenkins با GitLab یکی است.
- برداشتن پروفایل فقط توسط ادمین ممکن است (`policy-admin/unload-profile`).
- **ایده‌های بعدی:**
  - status check روی MR، تا قبل از کلیک روی Merge کاربر ببیند MR رد خواهد شد
  - بررسی tagها
  - حالت audit-only سراسری
  - اعلان (Slack یا ایمیل) برای رد شدن push
  - گزارش هفتگی از audit log

## ۸. اگر جای دیگری ادامه می‌دهید

<div dir="ltr">

```bash
git clone https://github.com/soroush67/jenkins-git-policy-python.git && cd jenkins-git-policy-python
python3 -m venv .venv && .venv/bin/pip install pytest pyyaml && .venv/bin/python -m pytest -q
lab/up.sh && tests/e2e/lab-e2e.sh
```

</div>

بعد از هر تغییر در کد، `lab/up.sh` را دوباره اجرا کنید. این اسکریپت working tree را به `platform/git-policy` در GitLab lab push می‌کند و deploy را دوباره اجرا می‌کند. بعد `tests/e2e/lab-e2e.sh` را اجرا کنید.

برای مستندات فارسی، بعد از نوشتن متن این دستور را اجرا کنید تا راست‌چین شوند:

<div dir="ltr">

```bash
python3 tools/rtl.py docs/fa/*.md
```

</div>

</div>
