<div dir="rtl">

# نگهداری، عیب‌یابی و عملیات

در دستورهای این سند، `GP_TARGET` همان مقداری است که در Jenkins تنظیم کرده‌اید. در lab مقدارش `docker:gpp-gitlab` است.

## ۱. کارهای روزمره

| کار | چطور |
|---|---|
| ساختن پروفایل یا نسخه‌ی جدید | فایل `profiles/<name>/<n>.yaml` را در `platform/policy-config` push کنید. deploy خودکار اجرا می‌شود ([03-PROFILES-FA.md](03-PROFILES-FA.md)) |
| load کردن پروفایل برای یک پروژه | job `policy/load-profile` توسط Maintainer پروژه. ادمین هم می‌تواند `assignments.yaml` را مستقیم ویرایش کند |
| برداشتن پروفایل | job `policy-admin/unload-profile` (فقط ادمین) |
| بازنشسته کردن یک نسخه | `deprecated_profiles` در `settings.yaml` |
| دیدن وضعیت یک پروژه | job `policy/show` با `PROJECT=group/project` |
| deploy دستی | job `policy-admin/deploy` و Build Now |

## ۲. بررسی سلامت

<div dir="ltr">

```bash
GP_TARGET=docker:gpp-gitlab deploy/push.sh doctor
```

</div>

خروجی سالم:

<div dir="ltr">

```
gitpolicy 1.0.0, python 3.9.21
git: /opt/gitlab/embedded/bin/git
bundle: /etc/gitpolicy/bundle.json (source acc5c8ac7dec, 7 profiles, 3 assignments, generated ...)
hook: /var/opt/gitlab/gitaly/custom_hooks/pre-receive.d/50-gitpolicy
=> OK
```

</div>

`source` همان commit از مخزن policy-config است که الان روی سرور فعال است.

## ۳. بازگشت (rollback)

**برگرداندن policy به حالت قبل:** هر بار که bundle نصب می‌شود، نسخه‌ی قبلی در `/etc/gitpolicy/bundle.json.prev` نگه داشته می‌شود.

<div dir="ltr">

```bash
GP_TARGET=... deploy/push.sh rollback-bundle
```

</div>

> rollback فقط یک راه حل موقت است. منبع حقیقت مخزن GitOps است و deploy بعدی دوباره همان را اعمال می‌کند. برای بازگشت دائمی، تغییر را در `policy-config` با `git revert` برگردانید. توجه کنید که revert کردن *اضافه شدن* یک نسخه‌ی پروفایل ممکن نیست، چون نسخه‌های منتشرشده تغییرناپذیرند.

**خاموش کردن کامل در شرایط اضطراری:**

<div dir="ltr">

```bash
GP_TARGET=... deploy/push.sh uninstall     # removes only the hook; everything else stays
# re-enable: run policy-admin/deploy again
```

</div>

**دسترسی اضطراری برای یک نفر:** نام کاربری GitLab او را در `break_glass_users` در `settings.yaml` بنویسید و deploy کنید. push های او بررسی نمی‌شوند، ولی در audit log با `decision: bypass` ثبت می‌شوند و خودش هم پیام `BYPASSED` می‌بیند. بعد از رفع مشکل، نامش را حذف کنید.

## ۴. audit log

هر push روی پروژه‌ای که پروفایل دارد یک خط JSON در `/var/log/gitlab/gitpolicy/audit.log` روی سرور GitLab ثبت می‌کند:

<div dir="ltr">

```json
{"ts": "2026-10-07T06:13:51Z", "project": "demo/app-b", "user": "dev2", "protocol": "web",
 "profile": "no-binaries@1", "decision": "reject", "commits": 1, "files": 1, "ms": 14,
 "bundle": "acc5c8ac7dec", "refs": [["b36c84661bbb", "ef3e3e2e2cba", "refs/heads/main"]],
 "violations": [{"rule_id": "no-binary-files", "path": "blob.bin", "commit": "57de1a8a...", "text": "binary file (4.0 KB)", ...}]}
```

</div>

| `decision` | معنی |
|---|---|
| `allow` | پذیرفته شد (ممکن است هشدار هم داشته باشد) |
| `reject` | رد شد |
| `bypass` | کاربر break-glass بود |
| `error-reject` / `error-allow` | خطای داخلی رخ داد و طبق `fail_mode` رفتار شد |

`protocol: web` یعنی کار از رابط GitLab انجام شده: دکمه‌ی Merge، ویرایش وب یا API.

نمونه‌ی جستجو:

<div dir="ltr">

```bash
# rejections of the last day
docker exec gpp-gitlab sh -c 'tail -n 5000 /var/log/gitlab/gitpolicy/audit.log' \
  | python3 -c 'import json,sys
for l in sys.stdin:
    r=json.loads(l)
    if r["decision"]!="allow": print(r["ts"], r["project"], r["user"], r["decision"], [v["rule_id"] for v in r.get("violations",[])])'
```

</div>

> چرخش (rotation) این فایل تنظیم نشده است. اگر حجمش زیاد شد، یک قانون `logrotate` برای `/var/log/gitlab/gitpolicy/*.log` اضافه کنید.

## ۵. عیب‌یابی

| علامت | علت محتمل | راه حل |
|---|---|---|
| push باینری پذیرفته می‌شود | پروژه پروفایل ندارد | `policy/show` با `PROJECT=...` |
| همه‌چیز پذیرفته می‌شود، حتی برای پروژه‌ی دارای پروفایل | hook اجرا نمی‌شود | `deploy/push.sh doctor`. بررسی `custom_hooks_dir` در `/var/opt/gitlab/gitaly/config.toml` و این‌که فایل `pre-receive.d/50-gitpolicy` اجرایی باشد |
| `gitpolicy: internal error, push rejected (fail_mode: closed)` | bundle خراب است یا git پیدا نمی‌شود | `doctor`. در صورت لزوم `rollback-bundle` |
| deploy با `was published and its file changed` شکست می‌خورد | یک نسخه‌ی منتشرشده ویرایش شده است | ویرایش را revert کنید و نسخه‌ی جدید بسازید |
| deploy با `ERROR: Gitaly does not use ... for server hooks` شکست می‌خورد | قدم ۱ نصب انجام نشده است | [02-INSTALL-FA.md](02-INSTALL-FA.md)، قدم ۱ |
| `load-profile`: `GitLab project ... not found` با این‌که پروژه وجود دارد | توکن bot پروژه را نمی‌بیند | bot باید ادمین باشد یا عضو گروه آن پروژه |
| `load-profile`: `... is not maintainer` با این‌که کاربر Maintainer است | نام کاربری Jenkins و GitLab فرق دارد | نام‌ها را یکی کنید (LDAP مشترک) |
| پروفایل جدید در لیست کشویی نیست | deploy هنوز اجرا نشده یا شکست خورده | `policy-admin/deploy` را بررسی و اجرا کنید |
| در Jenkins: `permission denied ... docker.sock` | کاربر jenkins عضو گروه docker نیست | در lab: `DOCKER_GID` در `lab/.env` و اجرای دوباره‌ی `up.sh` |
| push بزرگ (import مخزن قدیمی) کند است یا پیام `commit rules skipped` می‌دهد | بیش از `max_commits` commit جدید دارد | رفتار عادی است. فقط تفاوت نهایی فایل‌ها بررسی می‌شود |

**اجرای دستی hook برای دیباگ** (روی یک clone محلی، بدون push):

<div dir="ltr">

```bash
GP_TARGET=... deploy/push.sh fetch-bundle /tmp/bundle.json
python3 -m gitpolicy check --bundle /tmp/bundle.json --project demo/app-a \
    --repo . --ref main --old origin/main --new HEAD
```

</div>

**لاگ‌های GitLab:** اگر hook اصلاً اجرا نشود، علت در `/var/log/gitlab/gitaly/current` دیده می‌شود.

## ۶. ساختار فایل‌ها روی سرور GitLab

| مسیر | مالک و دسترسی | محتوا |
|---|---|---|
| `/var/opt/gitlab/gitaly/custom_hooks/pre-receive.d/50-gitpolicy` | root، 0755 | wrapper شل hook |
| `/opt/gitpolicy/gitpolicy/` | root، فقط خواندنی برای بقیه | کد موتور |
| `/etc/gitpolicy/bundle.json` (و `.prev`) | root، 0644 | policy فعال و نسخه‌ی قبلی |
| `/var/log/gitlab/gitpolicy/audit.log` | git، 0750 | audit log |

## ۷. تست‌ها

<div dir="ltr">

```bash
.venv/bin/python -m pytest -q      # unit + real-git push tests (also run by every deploy)
tests/e2e/lab-e2e.sh               # full lab end-to-end (lab must be up)
samples/try-it.sh demo/app-a       # push every sample file and show the result
```

</div>

job deploy قبل از نصب، همه‌ی تست‌های pytest را روی agent اجرا می‌کند. کدی که تست‌هایش رد شوند به GitLab نمی‌رسد.

## ۸. مدیریت lab

<div dir="ltr">

```bash
lab/up.sh             # start / update (re-pushes this working tree to platform/git-policy)
lab/down.sh           # stop, keep data
lab/down.sh --wipe    # delete everything incl. generated passwords
docker logs -f gpp-jenkins
docker exec -it gpp-gitlab bash
```

</div>

</div>
