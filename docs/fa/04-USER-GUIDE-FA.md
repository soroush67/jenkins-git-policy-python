<div dir="rtl">

# راهنمای کاربر: load کردن پروفایل برای پروژه

این راهنما برای توسعه‌دهنده‌ها و maintainerهای پروژه‌هاست. تیم پلتفرم پروفایل‌ها را ساخته است. شما فقط یکی از آن‌ها را برای پروژه‌ی خودتان انتخاب می‌کنید.

## ۱. پیش‌نیاز

- در **GitLab**، نقش **Maintainer** (یا Owner) پروژه را داشته باشید. با نقش Developer نمی‌توانید پروفایل پروژه را عوض کنید.
- در **Jenkins** حساب کاربری داشته باشید و **نام کاربری Jenkins با نام کاربری GitLab یکی باشد.** Jenkins نقش شما را با همین نام از GitLab می‌پرسد.

## ۲. دیدن پروفایل‌های موجود

Jenkins را باز کنید، وارد پوشه‌ی **Git Policy** شوید و job **show** را با **Build with Parameters** اجرا کنید:

- اگر `PROJECT` را خالی بگذارید، فهرست همه‌ی پروفایل‌ها، پروژه‌هایی که پروفایل دارند و توضیح همه‌ی نوع قوانین را می‌بینید.
- اگر `PROJECT=demo/app-a` بدهید، پروفایل فعلی پروژه، این‌که چه کسی و کِی آن را load کرده، و قوانینش را می‌بینید.

نمونه‌ی خروجی:

<div dir="ltr">

```
project demo/app-a: profile no-binaries@1
  loaded by dev1 at 2026-10-07T06:10:02Z
  No binary files on any branch. Blocks executables, archives, images and any ...
  - no-binary-files        binary_files          block branches=*
  - no-binary-extensions   forbidden_extensions  block branches=* {"extensions": [".exe", ".dll", ...]}
  - max-10mb               max_file_size         block branches=* {"max_size": 10485760}
```

</div>

## ۳. load کردن پروفایل

در پوشه‌ی **Git Policy**، job **load-profile** را با **Build with Parameters** اجرا کنید:

| پارامتر | مقدار |
|---|---|
| `PROJECT` | مسیر پروژه در GitLab، مثل `demo/app-a` (همان چیزی که در URL پروژه می‌بینید) |
| `PROFILE` | از لیست کشویی انتخاب کنید. نسخه‌ی جدیدتر هر پروفایل بالاتر است |
| `REPLACE_EXISTING` | فقط وقتی تیک بزنید که پروژه از قبل پروفایل دارد و می‌خواهید آن را عوض کنید |

بعد از اجرا، Jenkins این مراحل را انجام می‌دهد:
1. بررسی می‌کند که پروژه در GitLab وجود دارد و شما Maintainer آن هستید.
2. انتساب را به نام شما در مخزن `platform/policy-config` commit می‌کند (GitOps).
3. job `policy-admin/deploy` را اجرا می‌کند تا تغییر روی GitLab فعال شود.

وقتی build سبز شد، **از همان لحظه** همه‌ی push ها و merge های آن پروژه بررسی می‌شوند.

### خطاهای رایج load-profile

| پیام | معنی |
|---|---|
| `project demo/app-a already has profile X - set REPLACE_EXISTING` | پروژه از قبل پروفایل دارد. برای عوض کردن آن تیک `REPLACE_EXISTING` را بزنید |
| `dev1 is not maintainer (or higher) of demo/app-b` | در GitLab نقش Maintainer این پروژه را ندارید |
| `GitLab project demo/x not found` | مسیر پروژه اشتباه است |
| `project platform/... is locked` | پروفایل این پروژه فقط با تصمیم تیم پلتفرم عوض می‌شود |
| `profile X is deprecated` | این نسخه بازنشسته شده است. نسخه‌ی جدیدتر را انتخاب کنید |

> برداشتن پروفایل (unload) فقط کار ادمین است و با job `policy-admin/unload-profile` انجام می‌شود. کاربر عادی نمی‌تواند policy پروژه را خاموش کند.

## ۴. وقتی push شما رد می‌شود

در خط فرمان چیزی شبیه این می‌بینید:

<div dir="ltr">

```
remote: gitpolicy: push REJECTED by profile no-binaries@1 (1 violation)
remote:   [no-binary-files] tool.bin @ 3f2a9c1e0b: binary file (4.0 KB) (branch main)
remote:   hint: [no-binary-files] Store build outputs and binaries in Nexus/Artifactory, not in Git.
remote: gitpolicy 1.0.0 - remove the offending content from the history (e.g. git rebase -i) and push again
To http://localhost:8940/demo/app-a.git
 ! [remote rejected] HEAD -> main (pre-receive hook declined)
```

</div>

هر خط به این شکل است: `[شناسه‌ی قانون] فایل @ commit: علت (branch برنچ)`.

اگر در **GitLab** روی دکمه‌ی **Merge** یک Merge Request کلیک کنید و محتوا با پروفایل نخواند، merge انجام نمی‌شود و همین پیام در صفحه‌ی MR نشان داده می‌شود.

### چطور درستش کنم؟

فایل در **تاریخچه** است. فقط پاک کردن آن در یک commit جدید کافی نیست، چون commit قبلی هنوز آن را دارد. باید آن را از commitهایی که push نشده‌اند بیرون بیاورید.

**حالت ۱: فایل در آخرین commit است:**

<div dir="ltr">

```bash
git rm --cached tool.bin            # keep it on disk, drop it from git
echo tool.bin >> .gitignore
git add .gitignore
git commit --amend --no-edit
git push
```

</div>

**حالت ۲: فایل در یکی از commitهای قبلی است:**

<div dir="ltr">

```bash
git rebase -i origin/main           # mark the commit that added the file as "edit"
git rm --cached tool.bin
git commit --amend --no-edit
git rebase --continue
git push
```

</div>

**حالت ۳: فایل از قبل روی یک feature branch در سرور است** (قبل از load شدن پروفایل push شده) و حالا MR آن merge نمی‌شود: برنچ را بازنویسی کنید (مثل حالت ۲) و با `git push --force-with-lease` روی همان feature branch بفرستید. اگر پروفایل `no_force_push` را برای آن برنچ اعمال نکرده باشد، این push پذیرفته می‌شود. در غیر این صورت یک برنچ جدید از main بسازید و فقط تغییرات سالم را به آن ببرید (`git cherry-pick`).

**فایل‌های بزرگ یا باینری که واقعاً لازم‌اند** (مثل خروجی build یا dependency) را در مخزن artifact مثل Nexus بگذارید، یا از تیم پلتفرم پروفایلی بخواهید که آن مسیر را در `allow_paths` داشته باشد.

### هشدار (warn)

بعضی قوانین فقط هشدار می‌دهند. push پذیرفته می‌شود و این پیام را می‌بینید:

<div dir="ltr">

```
remote: gitpolicy: WARNING (profile strict@1) - push accepted, but please fix:
remote:   [big-file-warning] data.json @ 1a2b3c4d5e: file is 1.4 MB, limit is 1.0 MB (branch feature/x)
```

</div>

## ۵. سؤال‌های پرتکرار

**آیا پروفایل روی همه‌ی برنچ‌ها اعمال می‌شود؟** هر قانون فیلد `branches` دارد. خروجی job `show` نشان می‌دهد هر قانون روی کدام برنچ‌ها اجرا می‌شود. اگر قانونی فقط روی `main` باشد، روی feature branch اجرا نمی‌شود، ولی همان محتوا **با merge به main رد می‌شود.**

**می‌توانم دو پروفایل را با هم load کنم؟** نه. هر پروژه دقیقاً یک پروفایل دارد. اگر ترکیب خاصی لازم دارید، از تیم پلتفرم بخواهید یک پروفایل جدید بسازد.

**پروفایل‌ها را خودم می‌توانم تغییر بدهم؟** نه. پروفایل‌ها را تیم پلتفرم در مخزن `platform/policy-config` تعریف می‌کند و نسخه‌های منتشرشده تغییرناپذیرند.

**tagها هم بررسی می‌شوند؟** در این نسخه (MVP) خیر.

</div>
