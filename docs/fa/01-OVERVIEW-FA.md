<div dir="rtl">

# gitpolicy: معرفی و معماری

**gitpolicy** یک سرویس برای اعمال policy سازمانی روی GitLab است. شما (تیم پلتفرم) قوانین را به شکل **پروفایل** می‌نویسید. هر تیم پروفایل مناسب پروژه‌ی خودش را از Jenkins «load» می‌کند. از آن لحظه هر **push**، هر **merge در Merge Request** و هر **commit از رابط وب GitLab** روی آن پروژه با قوانین پروفایل بررسی می‌شود و در صورت تخلف رد می‌شود.

نمونه‌ی کاربرد:
- فایل باینری (exe، dll، jar، zip، تصویر و …) اصلاً push نشود.
- اگر قبل از اعمال policy باینری‌ای در یک برنچ push شده، **با merge یا کپی کردن برنچ به برنچ دیگری منتقل نشود.**
- رمز، کلید خصوصی یا توکن در کد commit نشود.
- حجم فایل محدود باشد، پیام commit قالب مشخصی داشته باشد، نام برنچ‌ها استاندارد باشد، ایمیل نویسنده فقط از دامنه‌ی سازمان باشد، و …

## اجزای سیستم

<div dir="ltr">

```
                 ┌──────────────────────────────────────────────┐
  Platform team  │ GitLab: platform/policy-config  (GitOps repo) │
  ─── git push ─►│   profiles/<name>/<version>.yaml  (immutable) │
                 │   assignments.yaml   settings.yaml            │
                 └──────────────┬───────────────────────▲────────┘
                                │ poll (2 min)          │ commit "load profile X for Y"
                                ▼                       │
                 ┌──────────────────────────┐   ┌───────┴──────────────────┐
                 │ Jenkins policy-admin/    │◄──┤ Jenkins policy/          │◄── Developer
                 │   deploy                 │   │   load-profile           │   (Maintainer
                 │ test → validate →        │   │ checks GitLab role,      │    in GitLab)
                 │ compile → install        │   │ commits the assignment   │
                 └────────────┬─────────────┘   └──────────────────────────┘
                              │ deploy/push.sh (docker exec | ssh)
                              ▼
                 ┌──────────────────────────────────────────────┐
                 │ GitLab server (Gitaly)                        │
                 │  custom_hooks/pre-receive.d/50-gitpolicy      │
                 │  /opt/gitpolicy/gitpolicy   (engine, Python)  │
                 │  /etc/gitpolicy/bundle.json (compiled policy) │
                 │  /var/log/gitlab/gitpolicy/audit.log          │
                 └──────────────────────────────────────────────┘
                     ▲ every push / MR merge / web commit
```

</div>

| جزء | کجا اجرا می‌شود | کار |
|---|---|---|
| **موتور (engine)**: `gitpolicy/engine.py`، `rules.py`، `gitrepo.py`، `hook.py` | داخل سرور GitLab به شکل pre-receive hook سراسری | تصمیم می‌گیرد هر push پذیرفته شود یا رد. فقط از کتابخانه‌ی استاندارد پایتون استفاده می‌کند و با Python 3.9 که داخل GitLab هست کار می‌کند |
| **control plane**: `gitpolicy/config.py`، `cli.py` | Jenkins | فایل‌های YAML را validate و به `bundle.json` کامپایل می‌کند، تغییرناپذیری پروفایل‌ها را چک می‌کند و انتساب پروژه به پروفایل را می‌نویسد |
| **مخزن GitOps** `platform/policy-config` | GitLab | تنها منبع حقیقت (single source of truth). هر تغییر در policy یک commit است |
| **Jenkins jobs** | Jenkins | `policy-admin/deploy` (استقرار)، `policy/load-profile` (کاربر)، `policy/show` (نمایش)، `policy-admin/unload-profile` (ادمین) |
| **deploy/push.sh** | Jenkins، با اتصال به سرور GitLab | نصب کد، hook و bundle روی سرور. انتقال با `docker exec` یا `ssh` |

## چرا pre-receive hook؟

- **همه‌ی راه‌ها را پوشش می‌دهد:** push از خط فرمان (SSH و HTTP)، دکمه‌ی Merge در MR، squash merge، ویرایش فایل در وب و commit از API. همه‌ی این‌ها در GitLab از Gitaly و pre-receive hook عبور می‌کنند.
- **قبل از ثبت** اجرا می‌شود. محتوای غیرمجاز هرگز وارد مخزن نمی‌شود و بعداً هم لازم نیست پاک‌سازی شود.
- **سراسری** است (global server hook). روی تک‌تک پروژه‌ها نصب نمی‌شود و کاربر نمی‌تواند آن را دور بزند یا غیرفعال کند.
- برای پروژه‌ای که پروفایل ندارد عملاً هزینه‌ای ندارد: فقط یک جستجو در bundle انجام می‌شود و بلافاصله خارج می‌شود.

## مفاهیم کلیدی

- **پروفایل** (`name@version`): مجموعه‌ای از قوانین. نسخه‌ی منتشرشده **تغییرناپذیر** است. برای تغییر، نسخه‌ی بعدی ساخته می‌شود.
- **هر پروژه = حداکثر یک پروفایل.** پروفایل‌ها ادغام نمی‌شوند و از هم ارث نمی‌برند، پس هیچ پروفایلی روی دیگری overwrite نمی‌شود.
- **انتساب (assignment)**: نگاشت `group/project` به `name@version` در فایل `assignments.yaml`. کاربر با Jenkins این نگاشت را می‌سازد و commit آن به نام همان کاربر ثبت می‌شود.
- **bundle**: خروجی کامپایل همه‌ی پروفایل‌ها، انتساب‌ها و تنظیمات در یک فایل JSON. hook فقط همین فایل را می‌خواند (YAML لازم ندارد) و نصب آن atomic است.
- **block / warn**: هر قانون یا push را رد می‌کند یا فقط هشدار می‌دهد.

## امنیت و رفتار در خطا

| موضوع | رفتار |
|---|---|
| خطای داخلی یا bundle خراب | `fail_mode: closed` (پیش‌فرض): push رد می‌شود. `open`: پذیرفته می‌شود. در هر دو حالت در audit log ثبت می‌شود |
| bundle نامعتبر در deploy | قبل از فعال شدن، روی خود سرور با موتور بررسی می‌شود. اگر نامعتبر باشد bundle قبلی فعال می‌ماند |
| کاربر غیر Maintainer | `load-profile` رد می‌شود. نقش کاربر از API گیت‌لب خوانده می‌شود |
| پروژه‌های حساس (`platform/*`) | با `locked_projects` قفل‌اند. فقط ادمین از طریق GitOps می‌تواند تغییرشان دهد |
| شرایط اضطراری | `break_glass_users` در `settings.yaml`. هر bypass در audit log ثبت و به خود کاربر هم اعلام می‌شود |
| هویت پروژه | فقط از `GL_PROJECT_PATH` که خود GitLab تعیین می‌کند خوانده می‌شود، نه از مسیر روی دیسک |
| ورودی‌ها | hook روی پایتون با `-E -s` اجرا می‌شود، یعنی متغیرهای `PYTHON*` محیط و site-packages کاربر نادیده گرفته می‌شوند |

## محدودیت‌های این نسخه (MVP)

- tagها و refهای غیر برنچ بررسی نمی‌شوند.
- GitLab LFS: فایل pointer متنی است و رد نمی‌شود. محتوای LFS از pre-receive عبور نمی‌کند.
- در lab، Jenkins از طریق docker socket به GitLab وصل می‌شود. در production از SSH استفاده کنید ([02-INSTALL-FA.md](02-INSTALL-FA.md) بخش ۵).
- نام کاربری Jenkins و GitLab باید یکی باشد تا بررسی نقش Maintainer کار کند. در سازمان این معمولاً با LDAP مشترک برقرار است.

## فهرست مستندات

1. [01-OVERVIEW-FA.md](01-OVERVIEW-FA.md): همین سند
2. [02-INSTALL-FA.md](02-INSTALL-FA.md): نصب و راه‌اندازی از صفر تا نصب نهایی
3. [03-PROFILES-FA.md](03-PROFILES-FA.md): نوشتن پروفایل‌ها و مرجع قوانین
4. [04-USER-GUIDE-FA.md](04-USER-GUIDE-FA.md): راهنمای کاربر (load کردن پروفایل، برطرف کردن push رد‌شده)
5. [05-OPERATIONS-FA.md](05-OPERATIONS-FA.md): نگهداری، عیب‌یابی، rollback و تست

</div>
