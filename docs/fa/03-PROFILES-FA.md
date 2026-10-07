<div dir="rtl">

# نوشتن پروفایل‌ها (راهنمای ادمین)

این سند برای کسی است که policyها را تعریف می‌کند (تیم پلتفرم). کاربران عادی فقط یک پروفایل آماده را «load» می‌کنند. راهنمای آن‌ها در [04-USER-GUIDE-FA.md](04-USER-GUIDE-FA.md) آمده است.

## ۱. پروفایل چیست؟

**پروفایل** یک مجموعه‌ی نام‌دار و نسخه‌دار از قوانین است. هر پروژه‌ی GitLab **دقیقاً یک** پروفایل دارد یا هیچ پروفایلی ندارد.

- نام‌گذاری: `name@version`، مثل `no-binaries@1` یا `strict@1`.
- هر نسخه یک فایل جداست: `profiles/<name>/<version>.yaml`.
- **نسخه‌ی منتشرشده تغییرناپذیر است.** اگر قانونی باید عوض شود، نسخه‌ی بعدی را می‌سازید (`2.yaml`). فایل `1.yaml` هرگز ویرایش یا حذف نمی‌شود.
- پروفایل‌ها **روی هم نمی‌نشینند و ادغام نمی‌شوند.** نه ارث‌بری (extends) داریم و نه ترکیب چند پروفایل. قوانینی که روی یک پروژه اجرا می‌شود دقیقاً همان قوانین داخل فایل پروفایلِ آن پروژه است. پس با خواندن یک فایل می‌فهمید دقیقاً چه چیزی اجرا می‌شود.

این تغییرناپذیری در **سه لایه** اجرا می‌شود:

| لایه | چه کسی چک می‌کند | چه چیزی را می‌گیرد |
|---|---|---|
| ۱ | pre-receive hook روی مخزن `platform/policy-config` (پروفایل `policy-config-guard@1`، قانون `immutable_paths`) | push ای که فایلی زیر `profiles/` را تغییر دهد، تغییر نام دهد یا حذف کند، همان لحظه رد می‌شود |
| ۲ | Jenkins (`policy-admin/deploy`) در برابر **bundle نصب‌شده روی GitLab** | اگر hash فایل یک نسخه‌ی منتشرشده با چیزی که روی سرور فعال است فرق کند، deploy متوقف می‌شود. این چک حتی بعد از force-push یا دور زدن لایه‌ی ۱ هم کار می‌کند |
| ۳ | Jenkins در برابر **تاریخچه‌ی git** از آخرین commit مستقرشده | فایل‌های تغییرکرده یا حذف‌شده با نام فایل گزارش می‌شوند |

## ۲. ساختار مخزن GitOps (`platform/policy-config`)

<div dir="ltr">

```
policy-config/
├── settings.yaml                  # global settings
├── assignments.yaml               # project -> profile (written by Jenkins)
└── profiles/
    ├── no-binaries/
    │   ├── 1.yaml
    │   └── 2.yaml
    ├── standard/1.yaml
    ├── strict/1.yaml
    ├── docs-friendly/1.yaml
    └── policy-config-guard/1.yaml
```

</div>

## ۳. ساختار یک فایل پروفایل

<div dir="ltr">

```yaml
name: no-binaries          # must equal the directory name
version: 1                 # must equal the file name (1.yaml)
owner: platform-team       # optional, informational
description: |             # shown in Jenkins (policy/show)
  No binary files on any branch.
rules:
  - id: no-binary-files            # unique inside the profile; shown on rejection
    type: binary_files             # rule type (see section 4)
    action: block                  # block (default) | warn
    branches: ["*"]                # target branches (default: all)
    message: Store binaries in Nexus, not in Git.   # optional hint for the user
    allow_paths: ["docs/**/*.png"] # type-specific parameters
```

</div>

**فیلدهای مشترک همه‌ی قوانین:**

| فیلد | الزامی | توضیح |
|---|---|---|
| `id` | بله | حروف کوچک انگلیسی، عدد، `.`، `_` و `-`. در پیام خطا نشان داده می‌شود |
| `type` | بله | یکی از نوع‌های بخش ۴ |
| `action` | خیر | `block` (پیش‌فرض): push یا merge رد می‌شود. `warn`: پذیرفته می‌شود ولی به کاربر هشدار داده می‌شود |
| `branches` | خیر | الگوی برنچ مقصد. پیش‌فرض `["*"]`. در این الگو `*` شامل `/` هم می‌شود، پس `release/*` با `release/2024/q1` هم match می‌شود |
| `message` | خیر | راهنمایی که زیر پیام رد شدن با عنوان `hint:` نشان داده می‌شود |

فیلد ناشناخته یا اشتباه تایپی (مثلاً `extention` به جای `extensions`) **خطا** حساب می‌شود و deploy انجام نمی‌شود. پس قانونی که بی‌صدا نادیده گرفته شود وجود ندارد.

## ۴. مرجع نوع قوانین

فهرست کامل را با این دستور هم می‌توانید ببینید:

<div dir="ltr">

```bash
python3 -m gitpolicy describe-rules
```

</div>

### ۴-۱. `binary_files`: جلوگیری از فایل باینری

تشخیص با همان روش خود git انجام می‌شود: وجود بایت NUL در ۸۰۰۰ بایت اول فایل. علاوه بر آن magic number فرمت‌های رایج هم بررسی می‌شود: ELF، PE/EXE ویندوز، ZIP/JAR، PNG، JPEG، GIF، PDF، gzip، 7z، RAR و Mach-O. یعنی فایل باینری‌ای که پسوندش را به `.txt` عوض کرده باشند هم گرفته می‌شود.

| پارامتر | نوع | پیش‌فرض | توضیح |
|---|---|---|---|
| `allow_paths` | لیست الگو | `[]` | مسیرهایی که باینری در آن‌ها مجاز است |
| `allow_extensions` | لیست | `[]` | پسوندهای مجاز، مثل `[.png, .pdf]` |
| `scan_bytes` | عدد | `8000` | چند بایت اول فایل بررسی شود |

### ۴-۲. `forbidden_extensions`: پسوندهای ممنوع

<div dir="ltr">

```yaml
- id: no-exe
  type: forbidden_extensions
  extensions: [.exe, .dll, jar]      # dot optional, case-insensitive
  allow_paths: ["tools/vendor/**"]
```

</div>

### ۴-۳. `forbidden_paths`: مسیرهای ممنوع

`patterns` با منطقی شبیه `.gitignore` بررسی می‌شوند (جزئیات در بخش ۵).

<div dir="ltr">

```yaml
- id: no-env
  type: forbidden_paths
  patterns: [".env", ".env.*", "*.pem", "secrets/"]
  allow_paths: [".env.example"]
```

</div>

### ۴-۴. `max_file_size`: حداکثر حجم فایل

`max_size` می‌تواند عدد بایت یا رشته‌ای مثل `500KB`، `10MB` یا `1GB` باشد. `allow_paths` هم دارد.

### ۴-۵. `secret_patterns`: جلوگیری از نشت رمز و توکن

الگوهای داخلی (اگر `builtin: true` باشد، که پیش‌فرض است):

| نام | چه چیزی را می‌گیرد |
|---|---|
| `private-key` | `-----BEGIN ... PRIVATE KEY` |
| `aws-access-key-id` | `AKIA...` یا `ASIA...` |
| `gitlab-token` | `glpat-...` |
| `github-token` | `ghp_...`، `gho_...` و مشابه |
| `slack-token` | `xoxb-...` و مشابه |
| `password-assignment` | `password = "..."` یا `pwd: '...'` |

الگوی اختصاصی سازمان را به شکل `نام: regex` اضافه می‌کنید:

<div dir="ltr">

```yaml
- id: no-secrets
  type: secret_patterns
  patterns:
    internal-token: 'INT-[0-9]{8}'
  allow_paths: ["tests/fixtures/**"]
  max_scan_size: 1MB        # larger files are skipped
```

</div>

### ۴-۶. `immutable_paths`: فایل‌های تغییرناپذیر

فایل‌های منطبق با الگو را می‌شود **اضافه** کرد، ولی بعد از آن **ویرایش، تغییر نام یا حذف** ممکن نیست. خود مخزن policy-config با همین قانون محافظت می‌شود.

### ۴-۷. `commit_message`: قالب پیام commit

| پارامتر | پیش‌فرض | توضیح |
|---|---|---|
| `pattern` | (الزامی) | regex |
| `subject_only` | `true` | فقط خط اول پیام بررسی شود |
| `skip_merges` | `true` | merge commitها بررسی نشوند. پیام merge را خود GitLab می‌سازد |

### ۴-۸. `author_email`: ایمیل نویسنده‌ی commit

مثلاً فقط دامنه‌ی سازمان: `pattern: '@company\.com$'`.

### ۴-۹. `branch_name`: نام‌گذاری برنچ‌ها

موقع **ساختن** برنچ جدید بررسی می‌شود. فیلد `branches` در این قانون نادیده گرفته می‌شود.

### ۴-۱۰. `no_force_push` و `no_branch_delete`

جلوگیری از بازنویسی تاریخچه (force push) و حذف برنچ‌های منطبق با `branches`.

> **نکته:** GitLab خودش «Protected Branches» دارد. این دو قانون برای وقتی است که بخواهید این محدودیت‌ها را هم به صورت GitOps و یکسان برای همه‌ی پروژه‌ها اجرا کنید.

## ۵. الگوی مسیرها

| الگو | با چه چیزی match می‌شود |
|---|---|
| `*.exe` | هر فایل `.exe` در هر پوشه‌ای (الگوی بدون `/` با نام فایل در هر سطحی match می‌شود) |
| `/README.md` | فقط `README.md` در ریشه‌ی مخزن |
| `docs/**/*.png` | `docs/a.png` و `docs/x/y/a.png` |
| `secrets/` | هر چیزی زیر پوشه‌ای به نام `secrets`، در هر سطحی |
| `assets/**` | همه‌چیز زیر `assets` |
| `f[0-9].txt` | `f1.txt`، `f2.txt` و غیره |

## ۶. دقیقاً چه چیزی بررسی می‌شود؟ (مهم)

برای هر برنچی که push یا merge می‌شود:

- **به‌روزرسانی برنچ** (old به new): **همه‌ی commitهایی که به این برنچ اضافه می‌شوند** بررسی می‌شوند، حتی اگر قبلاً در برنچ دیگری وجود داشته باشند. به همین دلیل فایلی که قبل از load شدن پروفایل در یک feature branch push شده، **با merge به main نمی‌رسد.** فرقی نمی‌کند merge با دکمه‌ی GitLab باشد، merge محلی، fast-forward یا squash.
- **ساختن برنچ جدید**: commitهایی که روی برنچ پیش‌فرض (main) نیستند بررسی می‌شوند. ساختن برنچ از یک main تمیز سریع است. کپی کردن یک برنچ آلوده به اسم جدید رد می‌شود.
- **حذف برنچ**: فقط `no_branch_delete` بررسی می‌شود.
- اگر باینری در یک commit اضافه و در commit بعدی پاک شود، باز هم push رد می‌شود، چون فایل در تاریخچه می‌ماند.
- merge commitها نسبت به parent اول بررسی می‌شوند، یعنی همان چیزی که merge وارد برنچ مقصد می‌کند.
- **tagها** و refهای داخلی GitLab بررسی نمی‌شوند (محدودیت MVP).
- اگر تعداد commitهای جدید از `max_commits` بیشتر شود (مثلاً موقع import یک مخزن قدیمی)، فقط **تفاوت نهایی فایل‌ها** بررسی می‌شود و قوانین commit (پیام و ایمیل) اجرا نمی‌شوند. این موضوع به کاربر اعلام می‌شود.

## ۷. چرخه‌ی کار: ساختن پروفایل جدید یا نسخه‌ی جدید

<div dir="ltr">

```bash
git clone http://<gitlab>/platform/policy-config.git && cd policy-config
mkdir -p profiles/my-team
$EDITOR profiles/my-team/1.yaml

# validate locally (same check Jenkins runs)
python3 -m gitpolicy validate .
python3 -m gitpolicy show .

git add profiles/my-team/1.yaml
git commit -m "add profile my-team@1"
git push origin main          # Jenkins policy-admin/deploy runs within ~2 minutes
```

</div>

بعد از deploy موفق، `my-team@1` در لیست کشویی job `policy/load-profile` اضافه می‌شود.

**تغییر دادن یک پروفایل:** فایل `profiles/my-team/2.yaml` را بسازید (معمولاً کپی‌شده از `1.yaml` با تغییرات). پروژه‌هایی که `@1` دارند روی `@1` می‌مانند. هر پروژه با `load-profile` و تیک `REPLACE_EXISTING` به `@2` منتقل می‌شود. برای انتقال یکجا، ادمین می‌تواند `assignments.yaml` را ویرایش کند.

**بازنشسته کردن یک نسخه:** نام آن را در `settings.yaml` زیر `deprecated_profiles` بنویسید. پروژه‌هایی که از قبل آن را دارند کار می‌کنند، ولی دیگر کسی نمی‌تواند آن را load کند.

## ۸. `settings.yaml`

<div dir="ltr">

```yaml
fail_mode: closed            # closed: reject on internal error | open: allow
break_glass_users: []        # GitLab users that bypass everything (audited)
locked_projects: [platform/*]  # load-profile cannot change these
deprecated_profiles: []      # name@version that can no longer be loaded
max_commits: 10000
```

</div>

## ۹. `assignments.yaml`

این فایل را Jenkins می‌نویسد. هر تغییر یک commit به نام کاربری است که پروفایل را load کرده:

<div dir="ltr">

```yaml
demo/app-a:
  profile: no-binaries@1
  by: dev1
  at: '2026-10-07T06:10:02Z'
platform/policy-config:
  profile: policy-config-guard@1
  by: admin
```

</div>

ادمین می‌تواند الگو هم بنویسد، مثلاً `demo/*: standard@1`. اولویت این‌طور است: اول مسیر دقیق پروژه، بعد طولانی‌ترین (دقیق‌ترین) الگو.

## ۱۰. امتحان کردن پروفایل قبل از انتشار (dry-run)

بدون push، روی یک clone محلی:

<div dir="ltr">

```bash
python3 -m gitpolicy compile policy-config -o /tmp/bundle.json
python3 -m gitpolicy check --bundle /tmp/bundle.json --project demo/app-a \
    --repo ~/src/app-a --ref main --old origin/main --new feature/x
```

</div>

</div>
