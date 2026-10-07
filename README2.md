# jenkins-git-policy-python

پروژه‌ی `jenkins-git-policy-python` یک سامانه‌ی اعمال Policy روی Git است که هدف اصلی آن کنترل متمرکز عملیات Push و Merge در سطح سازمان است. این سامانه به‌گونه‌ای طراحی شده که بتوان قوانینی مانند جلوگیری از ورود فایل‌های باینری، DLL، فایل‌های بزرگ، فایل‌های حاوی Secret، Force Push، حذف Branch، نام‌گذاری نامعتبر Branch و سایر محدودیت‌های سازمانی را تعریف کرد و پیش از آن‌که تغییرات واقعاً وارد Repository شوند، آن‌ها را بررسی و در صورت نقض Policy رد کرد.

نکته‌ی مهم در معماری این پروژه این است که Jenkins مسئول اجرای Policy هنگام Push نیست. Jenkins در این معماری نقش Control Plane را دارد؛ یعنی Policyها را اعتبارسنجی، Compile و Deploy می‌کند. Enforcement واقعی در سمت Git server و در مرحله‌ی `pre-receive` انجام می‌شود. در محیط GitLab این Hook در مسیر پردازش GitLab/Gitaly اجرا می‌شود و در یک Git server معمولی نیز می‌توان همین Engine را به‌عنوان `pre-receive hook` روی یک Bare Repository اجرا کرد.

به زبان ساده، جریان کلی سامانه به این شکل است:

```text
Policy YAML
    |
    v
gitpolicy validate
    |
    v
gitpolicy compile
    |
    v
bundle.json
    |
    v
Git pre-receive hook
    |
    v
gitpolicy hook
    |
    v
engine.py
    |
    v
rules.py
    |
    +------> ACCEPT
    |
    +------> REJECT
```

Policyهای این پروژه به‌صورت Profile تعریف می‌شوند. هر Profile مجموعه‌ای از Ruleهاست و دارای نام و Version مشخص است. برای مثال Profile زیر:

```text
no-binaries@1
```

نسخه‌ی اول Policyای با نام `no-binaries` است. اگر بعداً این Policy نیاز به تغییر داشته باشد، نسخه‌ی قبلی ویرایش نمی‌شود، بلکه Version جدید ساخته می‌شود:

```text
no-binaries@2
```

این موضوع یکی از اصول مهم طراحی پروژه است. Profileهایی که منتشر شده‌اند Immutable هستند و نباید بعداً تغییر داده یا حذف شوند. این ویژگی باعث می‌شود Policy سازمان قابل Audit و قابل بازسازی باشد و تغییر یک فایل قدیمی باعث تغییر ناگهانی رفتار پروژه‌هایی که هنوز از Version قبلی استفاده می‌کنند نشود.

## ساختار کلی پروژه

ساختار Repository به‌صورت کلی به شکل زیر است:

```text
gitpolicy/
policy-config/
jenkins/
deploy/
lab/
samples/
tests/
docs/
tools/
```

دایرکتوری `gitpolicy/` شامل Engine اصلی Python است. در این قسمت منطق اجرای Ruleها، ارتباط با Git، خواندن Bundle، پردازش Refها، CLI و Hook قرار دارد.

دایرکتوری `policy-config/` نمونه‌ی Repository مربوط به Policyهای سازمان است. فایل‌های YAML مربوط به Profileها، Assignment پروژه‌ها و تنظیمات سراسری در این بخش قرار دارند.

دایرکتوری `jenkins/` Pipelineهای Jenkins را نگهداری می‌کند. Jenkins از این Pipelineها برای Validate کردن Configuration، اجرای Testها، Compile کردن Policyها، Deploy کردن Engine و Bundle و همچنین مدیریت Assignment Profileها استفاده می‌کند.

دایرکتوری `deploy/` شامل Scriptهایی است که Engine و `bundle.json` را روی Git server نصب می‌کنند.

دایرکتوری `lab/` یک محیط آزمایش کامل شامل GitLab و Jenkins فراهم می‌کند تا سامانه را پیش از ورود به محیط Production به‌صورت End-to-End تست کرد.

دایرکتوری `tests/` شامل Unit Test، Integration Test و End-to-End Test است.

دایرکتوری `docs/` مستندات تکمیلی پروژه را نگهداری می‌کند.

## نصب محیط توسعه

برای دریافت Repository ابتدا آن را Clone می‌کنیم:

```bash
git clone https://github.com/soroush67/jenkins-git-policy-python.git
cd jenkins-git-policy-python
```

سپس یک Python Virtual Environment می‌سازیم:

```bash
python3 -m venv .venv
```

Dependencyهای موردنیاز Control Plane و Testها را نصب می‌کنیم:

```bash
.venv/bin/pip install pytest pyyaml
```

بعد می‌توان کل Test Suite پروژه را اجرا کرد:

```bash
.venv/bin/python -m pytest -q
```

در نسخه‌ی فعلی پروژه، Test Suite شامل ۹۴ تست است و در محیط آزمایشی ما هر ۹۴ تست با موفقیت اجرا شدند:

```text
94 passed
```

برای مشاهده‌ی CLI پروژه می‌توان از دستور زیر استفاده کرد:

```bash
PYTHONPATH=. .venv/bin/python -m gitpolicy --help
```

دستورهای اصلی CLI شامل موارد زیر هستند:

```text
validate
compile
diff
assign
unassign
list-profiles
show
describe-rules
gitlab-check
hook
check
doctor
```

## Policy چیست؟

در این پروژه Policy مستقیماً یک Rule منفرد نیست. Policy به شکل یک Profile تعریف می‌شود و هر Profile می‌تواند شامل چند Rule باشد.

برای مثال:

```text
policy-config/profiles/no-binaries/1.yaml
```

می‌تواند چنین محتوایی داشته باشد:

```yaml
name: no-binaries
version: 1
owner: platform-team

description: |
  No binary files on any branch.

rules:

  - id: no-binary-files
    type: binary_files
    action: block
    branches:
      - "*"
    message: Store binaries in Nexus/Artifactory, not in Git.

  - id: no-binary-extensions
    type: forbidden_extensions
    action: block
    branches:
      - "*"
    extensions:
      - .exe
      - .dll
      - .so
      - .jar
      - .war
      - .bin
      - .zip

  - id: max-10mb
    type: max_file_size
    action: block
    branches:
      - "*"
    max_size: 10MB
```

در این Profile سه Rule وجود دارد. Rule اول محتوای فایل را بررسی می‌کند تا فایل باینری وارد Git نشود. Rule دوم فایل‌ها را بر اساس Extension بررسی می‌کند و Rule سوم فایل‌های بزرگ‌تر از ۱۰ مگابایت را رد می‌کند.

بنابراین ساختار مفهومی به این صورت است:

```text
Profile
  |
  +--> Rule
  |
  +--> Rule
  |
  +--> Rule
```

## ارتباط YAML و Python

نکته‌ی اساسی این پروژه این است که فایل YAML فقط Configuration است و منطق واقعی Policy در Python پیاده‌سازی شده است.

برای مثال:

```yaml
type: binary_files
```

به‌تنهایی هیچ الگوریتمی برای تشخیص فایل باینری ندارد. این مقدار به Engine می‌گوید که کلاس مربوط به `binary_files` را در `gitpolicy/rules.py` اجرا کند.

در Python کلاسی مانند زیر وجود دارد:

```python
class BinaryFiles(Rule):
    TYPE = "binary_files"
```

برای Rule مربوط به Extension نیز کلاس دیگری وجود دارد:

```python
class ForbiddenExtensions(Rule):
    TYPE = "forbidden_extensions"
```

تمام Ruleهای قابل استفاده در YAML در Registry مربوط به `RULE_TYPES` ثبت شده‌اند.

از نظر مفهومی می‌توان این رابطه را این‌گونه بیان کرد:

```text
YAML     = What
rules.py = How
engine.py = When and on what
hook.py  = Enforcement point
```

یعنی YAML مشخص می‌کند چه قانونی باید اجرا شود، `rules.py` مشخص می‌کند آن قانون از نظر فنی چگونه تشخیص داده شود، `engine.py` مشخص می‌کند این Rule روی چه Commitها و تغییراتی اجرا شود و `hook.py` نتیجه را به Git برمی‌گرداند تا Push قبول یا رد شود.

## Ruleهای موجود

نسخه‌ی فعلی پروژه Ruleهای زیر را در اختیار دارد:

```text
binary_files
forbidden_extensions
forbidden_paths
max_file_size
secret_patterns
immutable_paths
commit_message
author_email
branch_name
no_force_push
no_branch_delete
```

Rule مربوط به `binary_files` محتوای فایل را بررسی می‌کند. تشخیص فقط بر اساس Extension انجام نمی‌شود و فایل‌هایی که دارای NUL byte یا Magic Numberهای شناخته‌شده هستند نیز قابل شناسایی‌اند.

Rule مربوط به `forbidden_extensions` فایل‌ها را بر اساس Extension مسدود می‌کند. برای مثال:

```yaml
- id: no-dll
  type: forbidden_extensions
  extensions:
    - .dll
    - .exe
    - .jar
```

Rule مربوط به `forbidden_paths` می‌تواند مسیرهایی مانند `.env`، فایل‌های PEM و دایرکتوری‌های Secret را مسدود کند.

```yaml
- id: no-env
  type: forbidden_paths
  patterns:
    - ".env"
    - ".env.*"
    - "*.pem"
    - "secrets/"
```

Rule مربوط به `max_file_size` روی Size فایل Policy اعمال می‌کند:

```yaml
- id: max-size
  type: max_file_size
  max_size: 10MB
```

Rule مربوط به `secret_patterns` فایل‌های متنی را برای Credentialها و Secretهای شناخته‌شده بررسی می‌کند.

Rule `immutable_paths` اجازه می‌دهد فایل یا مسیر مشخصی پس از ایجاد، دیگر قابل تغییر، Rename یا Delete نباشد.

Rule `commit_message` پیام Commit را با Regular Expression بررسی می‌کند.

Rule `author_email` می‌تواند Author Email را محدود کند.

Rule `branch_name` برای Naming Convention مربوط به Branch استفاده می‌شود.

Rule `no_force_push` از Non-Fast-Forward Update جلوگیری می‌کند.

Rule `no_branch_delete` از حذف Branchهای مشخص جلوگیری می‌کند.

هر Rule می‌تواند `action` داشته باشد:

```yaml
action: block
```

یا:

```yaml
action: warn
```

در حالت `block` نقض Rule باعث Reject شدن Push می‌شود. در حالت `warn` Push پذیرفته می‌شود ولی پیام هشدار برای کاربر نمایش داده می‌شود.

همچنین می‌توان Scope مربوط به Branch را مشخص کرد:

```yaml
branches:
  - main
  - develop
  - release/*
```

یا Rule را روی همه‌ی Branchها اجرا کرد:

```yaml
branches:
  - "*"
```

## Validate کردن Policy

پس از ایجاد یا تغییر Policy باید Repository مربوط به Policyها Validate شود.

دستور:

```bash
PYTHONPATH=. .venv/bin/python -m gitpolicy validate policy-config
```

یا در محیط Lab:

```bash
PYTHONPATH=. .venv/bin/python -m gitpolicy validate \
  /tmp/gitpolicy-lab/policy-config
```

Validation فقط Syntax ساده‌ی YAML را بررسی نمی‌کند. این مرحله بررسی می‌کند که Profile دارای ساختار معتبر باشد، نام و Version صحیح باشند، Rule Type معتبر باشد، Parameterهای لازم وجود داشته باشند، Field ناشناخته وجود نداشته باشد، Assignment به Profile موجود اشاره کند و محدودیت‌های مربوط به Immutable بودن Versionهای منتشرشده نقض نشده باشند.

برای مثال اگر اشتباه بنویسیم:

```yaml
type: binary_file
```

در حالی که Type صحیح:

```yaml
type: binary_files
```

است، Validation باید Fail شود.

به همین ترتیب اگر برای Rule مربوط به Extension پارامتر موردنیاز `extensions` وجود نداشته باشد، Configuration معتبر نخواهد بود.

در داخل `rules.py` تابع `normalize()` یکی از قسمت‌های مهم Validation است. این تابع Specification مربوط به هر Rule را گرفته و بررسی می‌کند که `id` معتبر باشد، `type` شناخته‌شده باشد، `action` معتبر باشد، `branches` ساختار مناسب داشته باشد و Parameterهای اختصاصی Rule از Type صحیح برخوردار باشند.

## Compile کردن Policy

بعد از Validation، Configuration به یک Bundle تبدیل می‌شود.

برای مثال:

```bash
PYTHONPATH=. .venv/bin/python -m gitpolicy compile \
  /tmp/gitpolicy-lab/policy-config \
  -o /tmp/gitpolicy-lab/bundle.json \
  --source-commit local-test
```

فایل خروجی:

```text
bundle.json
```

است.

این فایل Snapshot اجرایی Policyهای سازمان است و شامل مواردی مانند Settings، Profileها، Ruleها، Assignmentها و Source Commit می‌شود.

نمونه‌ی ساده‌شده:

```json
{
  "profiles": {
    "no-binaries@1": {
      "rules": [
        {
          "id": "no-binary-files",
          "type": "binary_files",
          "action": "block"
        }
      ]
    }
  },
  "assignments": [
    {
      "project": "demo/app",
      "profile": "no-binaries@1"
    }
  ]
}
```

Runtime مربوط به Hook فایل‌های YAML را مستقیماً نمی‌خواند. Hook فقط `bundle.json` را Load می‌کند.

این جداسازی چند مزیت مهم دارد. Parsing و Validation سنگین YAML در زمان Push انجام نمی‌شود، Python Runtime سمت Git server به PyYAML نیاز ندارد، Configuration پیش از Deploy بررسی شده است و رفتار Hook قابل پیش‌بینی‌تر و سریع‌تر می‌شود.

## Assignment یک Profile به Project

ساختن Profile به‌تنهایی باعث اجرای آن نمی‌شود. باید مشخص شود کدام Project از کدام Profile استفاده کند.

این Mapping در:

```text
assignments.yaml
```

نگهداری می‌شود.

برای مثال:

```yaml
demo/app:
  profile: no-binaries@1
  by: admin
```

معنی آن این است که تمام Pushها و Mergeهایی که برای Project با نام:

```text
demo/app
```

انجام می‌شوند باید با Profile:

```text
no-binaries@1
```

بررسی شوند.

Assignment را می‌توان از CLI نیز انجام داد:

```bash
PYTHONPATH=. .venv/bin/python -m gitpolicy assign \
  policy-config \
  --project demo/app \
  --profile no-binaries@1 \
  --by admin
```

بعد از Assignment باید Configuration دوباره Validate و Compile شود تا Assignment جدید وارد `bundle.json` شود.

در محیط Production این کار می‌تواند توسط Jenkins انجام شود.

## Immutable Profileها

یکی از ویژگی‌های اصلی معماری این پروژه Versioned و Immutable بودن Profileهاست.

اگر Profile زیر منتشر شده باشد:

```text
no-binaries@1
```

نباید فایل مربوط به Version `1` را بعداً تغییر داد.

اگر Policy جدیدی لازم باشد باید فایل جدیدی ساخته شود:

```text
no-binaries@2
```

و Projectهایی که لازم است به Version جدید مهاجرت کنند به‌صورت Explicit روی `@2` قرار می‌گیرند.

این طراحی باعث می‌شود بتوان دقیقاً مشخص کرد که یک Project در یک زمان مشخص تحت چه Policyای بوده است.

پروژه چند لایه برای جلوگیری از تغییر Profileهای منتشرشده در نظر گرفته است. خود Repository مربوط به Policy می‌تواند با Rule `immutable_paths` محافظت شود، Deploy می‌تواند Hash Profileهای قبلی را با Bundle نصب‌شده مقایسه کند و Git History نیز برای تشخیص تغییر فایل‌های Version قدیمی بررسی شود.

## Enforcement در Git

تا این مرحله فقط Configuration آماده شده است. Enforcement واقعی زمانی شروع می‌شود که Git یک عملیات Push را دریافت کند.

Git Server پیش از Update کردن Referenceهای Repository، Hook مربوط به `pre-receive` را اجرا می‌کند.

Git اطلاعات مربوط به Ref Update را روی Standard Input به Hook می‌دهد:

```text
<old-sha> <new-sha> <ref>
```

برای مثال:

```text
0bf33a74... bb07ab5... refs/heads/main
```

این اطلاعات به Engine می‌گوید Branch `main` قرار است از Commit قبلی به Commit جدید منتقل شود.

اگر Hook با Exit Code صفر خارج شود:

```text
exit 0
```

Git عملیات را Accept می‌کند.

اگر Hook با Exit Code غیر صفر خارج شود:

```text
exit 1
```

Git Push را Reject می‌کند.

## hook.py

Entry Point اصلی Enforcement در:

```text
gitpolicy/hook.py
```

قرار دارد.

در محیط GitLab اطلاعاتی مانند Project، User و Protocol از Environment دریافت می‌شوند:

```text
GL_PROJECT_PATH
GL_USERNAME
GL_PROTOCOL
```

برای مثال:

```text
GL_PROJECT_PATH=demo/app
GL_USERNAME=john
GL_PROTOCOL=ssh
```

Hook همچنین Updateهای Git را از stdin دریافت می‌کند.

بعد `bundle.json` Load می‌شود و Project جاری در Assignmentها Resolve می‌شود.

اگر Project هیچ Profileای نداشته باشد، Policy مربوط به Profile روی آن اجرا نمی‌شود.

اگر Profile وجود داشته باشد، Ruleهای Profile ساخته می‌شوند و Engine برای بررسی Push فراخوانی می‌شود.

## engine.py

فایل:

```text
gitpolicy/engine.py
```

مسئول اصلی Orchestration اجرای Ruleها است.

Engine مشخص می‌کند چه Commitهایی جدید هستند، چه فایل‌هایی تغییر کرده‌اند و کدام Rule باید روی Ref، Commit یا Change اجرا شود.

Ruleها از نظر نقطه‌ی اجرای خود سه دسته‌ی اصلی دارند:

```text
REF
COMMIT
CHANGE
```

Ruleهای REF روی خود Reference Update اجرا می‌شوند. برای مثال `no_force_push` و `no_branch_delete`.

Ruleهای COMMIT روی Commitهای جدید اجرا می‌شوند. برای مثال `commit_message` و `author_email`.

Ruleهای CHANGE روی فایل‌های تغییرکرده اجرا می‌شوند. برای مثال `binary_files`، `forbidden_extensions` و `secret_patterns`.

## تعیین Commitهای جدید

فرض کنیم وضعیت Repository قبل از Push به شکل زیر باشد:

```text
A --- B --- C
```

و Developer دو Commit جدید داشته باشد:

```text
A --- B --- C --- D --- E
```

Git به Hook می‌گوید:

```text
old = C
new = E
```

Engine عملاً Commitهایی را پیدا می‌کند که از `new` قابل دسترسی هستند ولی از `old` قابل دسترسی نیستند.

از نظر مفهومی:

```bash
git rev-list E ^C
```

نتیجه:

```text
D
E
```

است.

بنابراین Engine دقیقاً Commitهایی را بررسی می‌کند که قرار است وارد Branch مقصد شوند.

این طراحی یک ویژگی امنیتی مهم دارد. اگر یک Commit آلوده قبلاً در Branch دیگری وجود داشته باشد، ولی حالا قرار باشد وارد Branch مقصد شود، دوباره بررسی می‌شود. به همین دلیل فایلی که قبلاً در یک Feature Branch وارد Repository شده نمی‌تواند صرفاً به دلیل قدیمی بودن از Policy فرار کند و بعداً به `main` یا `develop` Merge شود.

## بررسی Changeهای هر Commit

بعد از پیدا کردن Commitها، Engine تغییرات فایل‌ها را از Git استخراج می‌کند.

برای مثال:

```text
M README.md
A bad.bin
M config.yml
```

هر تغییر به یک Rule مربوط به `CHANGE` داده می‌شود.

مثلاً Rule `binary_files` فایل `bad.bin` را بررسی می‌کند. اگر NUL byte یا Signature باینری در فایل پیدا شود، یک Violation ایجاد می‌شود.

Rule `forbidden_extensions` نیز Path را بررسی می‌کند. اگر `.bin` در لیست Extensionهای ممنوع باشد، Violation دیگری ساخته می‌شود.

بنابراین ممکن است یک فایل چند Rule را هم‌زمان نقض کند.

برای مثال در Lab فایل:

```text
bad.bin
```

هم توسط `binary_files` و هم توسط `forbidden_extensions` شناسایی شد.

## Violation و تصمیم نهایی

هر Rule می‌تواند صفر یا چند Violation برگرداند.

Violation شامل اطلاعاتی مانند Rule ID، Rule Type، Action، Branch، Commit، Path، Message و Hint است.

اگر فقط Violationهایی با:

```text
action: warn
```

وجود داشته باشند، Push پذیرفته می‌شود ولی Warning چاپ می‌شود.

اگر حداقل یک Violation با:

```text
action: block
```

وجود داشته باشد، نتیجه‌ی نهایی Push Reject خواهد بود.

در این حالت `hook.py` با Exit Code یک خارج می‌شود و Git عملیات را متوقف می‌کند.

خروجی نمونه:

```text
remote: gitpolicy: push REJECTED by profile no-binaries@1
remote: [no-binary-files] bad.bin: binary file
remote: [no-binary-extensions] bad.bin: forbidden file extension
remote: hint: Store build outputs and binaries in Nexus/Artifactory, not in Git.
```

و Git در انتها اعلام می‌کند:

```text
! [remote rejected] main -> main (pre-receive hook declined)
```

در این حالت Reference سمت Server تغییر نکرده است.

## Audit Log

gitpolicy نتیجه‌ی بررسی Pushها را می‌تواند در Audit Log ثبت کند.

برای مثال:

```json
{
  "project": "demo/app",
  "user": "john",
  "profile": "no-binaries@1",
  "decision": "reject",
  "commits": 1,
  "files": 1,
  "violations": []
}
```

در Audit اطلاعاتی مانند Project، User، Protocol، Ref، Bundle Version، تعداد Commit، تعداد فایل، زمان اجرای Policy، تصمیم نهایی و Violationها ثبت می‌شوند.

این قابلیت برای Compliance و بررسی Incident بسیار مهم است.

## اجرای پروژه بدون GitLab

Engine برای تست الزاماً به GitLab نیاز ندارد.

می‌توان یک Bare Repository محلی ساخت:

```bash
mkdir -p /tmp/gitpolicy-lab
cd /tmp/gitpolicy-lab

git init --bare server.git
```

سپس Client را Clone کرد:

```bash
git clone /tmp/gitpolicy-lab/server.git client
cd client
```

و برای Bare Repository یک Hook ساخت:

```text
/tmp/gitpolicy-lab/server.git/hooks/pre-receive
```

برای شبیه‌سازی GitLab می‌توان Environment Variableها را دستی تعریف کرد:

```bash
#!/bin/sh

export GL_USERNAME="john"
export GL_PROJECT_PATH="demo/app"
export GL_PROTOCOL="ssh"

export GITPOLICY_BUNDLE="/tmp/gitpolicy-lab/bundle.json"
export GITPOLICY_AUDIT_LOG="/tmp/gitpolicy-lab/audit.log"
export GITPOLICY_REPO="/tmp/gitpolicy-lab/server.git"

export PYTHONPATH="/root/jenkins-git-policy-python"

exec /root/jenkins-git-policy-python/.venv/bin/python \
  -m gitpolicy hook
```

سپس Hook اجرایی می‌شود:

```bash
chmod +x /tmp/gitpolicy-lab/server.git/hooks/pre-receive
```

از این لحظه هر:

```bash
git push origin main
```

واقعاً از داخل `gitpolicy` عبور می‌کند.

در تست عملی، Push یک فایل متنی سالم پذیرفته شد، اما اضافه کردن:

```bash
printf '\x00\x01\x02\x03\x04\x05' > bad.bin
```

و سپس:

```bash
git add bad.bin
git commit -m "add binary"
git push origin main
```

باعث شد `gitpolicy` Push را Reject کند.

این تست ثابت می‌کند که Enforcement مستقل از Jenkins انجام می‌شود و Jenkins فقط برای مدیریت Policy ضروری است، نه برای تصمیم‌گیری لحظه‌ی Push.

## Jenkins چه نقشی دارد؟

Jenkins Control Plane سامانه است.

Job اصلی Deploy در:

```text
jenkins/Jenkinsfile.deploy
```

قرار دارد.

جریان Deploy به‌صورت مفهومی چنین است:

```text
Checkout policy-config
        |
        v
Run tests
        |
        v
Fetch installed bundle
        |
        v
Validate
        |
        v
Check immutability
        |
        v
Compile
        |
        v
Install Engine
        |
        v
Install bundle.json
        |
        v
Doctor
```

Jenkins هیچ Push کاربر را مستقیماً بررسی نمی‌کند. Jenkins فقط Runtime Policy را آماده می‌کند.

این تفکیک بسیار مهم است:

```text
Jenkins = Control Plane

Git pre-receive = Enforcement Plane
```

اگر Jenkins در لحظه‌ی Push خاموش باشد ولی Engine و Bundle قبلاً روی Git server نصب شده باشند، Policy همچنان می‌تواند Push را بررسی کند.

## Job مربوط به Load Profile

پروژه یک Jenkins Job برای Assignment Profile دارد:

```text
policy/load-profile
```

کاربر یا Maintainer می‌تواند از Profileهای منتشرشده یکی را برای Project انتخاب کند.

Job ابتدا از GitLab بررسی می‌کند که Project وجود داشته باشد و User Role موردنیاز را داشته باشد. سپس `assignments.yaml` را تغییر می‌دهد، Commit ایجاد می‌کند و Job مربوط به Deploy را اجرا می‌کند.

بنابراین User عادی خود Rule را تغییر نمی‌دهد. Platform Team Profile را ایجاد می‌کند و User فقط Profile مجاز را انتخاب می‌کند.

## GitOps

Policy Configuration داخل Git نگهداری می‌شود.

به همین دلیل تمام تغییرات Policy:

```text
Versioned
Auditable
Reviewable
Rollbackable
```

هستند.

Source of Truth واقعی Repository مربوط به `policy-config` است.

Jenkins وضعیت این Repository را به وضعیت Runtime روی GitLab تبدیل می‌کند.

از این نظر Flow پروژه کاملاً GitOps است:

```text
Git Repository
      |
      v
Desired Policy State
      |
      v
Jenkins Reconciliation
      |
      v
bundle.json
      |
      v
GitLab Runtime State
```

## Fail Mode

در:

```text
settings.yaml
```

می‌توان مشخص کرد اگر Engine یا Bundle دچار مشکل شد چه رفتاری انجام شود.

حالت امن:

```yaml
fail_mode: closed
```

در این حالت اگر Policy Engine نتواند تصمیم معتبر بگیرد، Push رد می‌شود.

حالت دیگر:

```yaml
fail_mode: open
```

است که در صورت Error داخلی Push را قبول می‌کند.

برای Policy امنیتی Production معمولاً `closed` مناسب‌تر است.

## Break Glass

برای شرایط اضطراری می‌توان Userهایی را به‌عنوان Break Glass تعریف کرد:

```yaml
break_glass_users:
  - root
```

Push این Userها می‌تواند Policy را Bypass کند، ولی این اتفاق در Audit Log ثبت می‌شود.

Break Glass برای Incident و Disaster Recovery در نظر گرفته شده و نباید به‌عنوان روش معمول کار استفاده شود.

## Locked Projects

در Settings می‌توان Projectهای حساس را Locked کرد:

```yaml
locked_projects:
  - platform/*
```

در این حالت User عادی نمی‌تواند از Job مربوط به `load-profile`، Profile پروژه‌های مذکور را تغییر دهد و این Assignmentها باید توسط Platform Admin مدیریت شوند.

## Deprecated Profile

Profile منتشرشده نباید حذف شود، ولی می‌توان آن را Deprecated کرد.

برای مثال:

```yaml
deprecated_profiles:
  - no-binaries@1
```

Projectهایی که از قبل روی `no-binaries@1` هستند همچنان کار می‌کنند، ولی Project جدید دیگر نمی‌تواند آن Version را Load کند.

## نوشتن یک Policy جدید با Rule موجود

اگر Rule موردنیاز از قبل در Engine وجود داشته باشد، نیاز به تغییر Python نیست.

برای مثال برای جلوگیری از `.rpm` و `.deb` می‌توان Profile جدید ساخت:

```text
profiles/no-packages/1.yaml
```

محتوا:

```yaml
name: no-packages
version: 1

owner: platform-team

description: |
  Prevent Linux package files from being stored in Git.

rules:

  - id: no-linux-packages
    type: forbidden_extensions
    action: block
    branches:
      - "*"
    extensions:
      - .rpm
      - .deb
```

بعد:

```bash
python3 -m gitpolicy validate policy-config
```

و سپس:

```bash
python3 -m gitpolicy compile policy-config -o bundle.json
```

و در نهایت Profile به Project Assign می‌شود.

پس برای Ruleهایی که Engine از قبل می‌شناسد، توسعه‌ی Python لازم نیست.

## اضافه کردن Rule Type جدید

اگر نیاز سازمان چیزی باشد که Engine هنوز نمی‌شناسد، باید Rule Type جدیدی به `rules.py` اضافه شود.

برای مثال فرض کنیم بخواهیم User مشخصی اجازه‌ی Push نداشته باشد.

در نسخه‌ی فعلی پروژه `GL_USERNAME` در `hook.py` دریافت می‌شود، ولی Rule استانداردی برای Block کردن User وجود ندارد.

برای اضافه کردن این قابلیت باید Rule جدیدی مانند:

```text
forbidden_users
```

طراحی شود.

از نظر مفهومی کلاس آن می‌تواند شبیه این باشد:

```python
class ForbiddenUsers(Rule):

    TYPE = "forbidden_users"

    PARAMS = {
        "users": ("list", True, None),
    }

    REF = True

    def check_ref(self, ctx, update):

        if ctx.user.lower() in {
            u.lower() for u in self.p["users"]
        }:
            return [
                self.v(
                    update,
                    "user %r is not allowed to push" % ctx.user
                )
            ]

        return []
```

بعد Rule در `RULE_TYPES` Register می‌شود.

سپس Profile می‌تواند چنین باشد:

```yaml
name: restricted-users
version: 1

rules:

  - id: block-john
    type: forbidden_users
    action: block
    users:
      - john
```

ولی برای این قابلیت باید Username از `hook.py` وارد Context مربوط به `engine.py` نیز شود. این مثال نشان می‌دهد تفاوت میان نوشتن یک Policy با Rule موجود و توسعه‌ی Capability جدید چیست.

## تست Policy

Policy در چند سطح تست می‌شود.

سطح اول Validation است:

```bash
python3 -m gitpolicy validate policy-config
```

این مرحله Configuration را بررسی می‌کند.

سطح دوم Test Suite Python است:

```bash
python3 -m pytest -q
```

این Test Suite Ruleها و رفتار Engine را بررسی می‌کند.

سطح سوم Dry Run است که می‌تواند Policy را روی Repository محلی و Range مشخصی از Commitها بررسی کند.

سطح چهارم و مهم‌ترین سطح، End-to-End Test واقعی با `git push` است.

در این تست یک Bare Repository داریم، `pre-receive` واقعی اجرا می‌شود، Engine Commitها را بررسی می‌کند و Git براساس Exit Code Hook عملیات را Accept یا Reject می‌کند.

این سطح از Test دقیق‌ترین شبیه‌سازی رفتار Production است.

## Profileهای موجود در نمونه‌ی فعلی

نسخه‌ی فعلی Configuration نمونه شامل پنج خانواده‌ی Profile است:

```text
docs-friendly
no-binaries
policy-config-guard
standard
strict
```

از آنجا که `no-binaries` دو Version دارد، تعداد Profile Versionها شش عدد است:

```text
docs-friendly@1
no-binaries@1
no-binaries@2
policy-config-guard@1
standard@1
strict@1
```

`no-binaries@1` فایل‌های باینری، Extensionهای باینری شناخته‌شده و فایل‌های بزرگ‌تر از Limit تعریف‌شده را مسدود می‌کند.

`no-binaries@2` Version جدیدتر همین Policy است و تفاوت‌هایی مانند مجاز بودن بعضی Assetهای مستندات و Limit متفاوت دارد.

`docs-friendly@1` برای Repositoryهای مستندات طراحی شده و بعضی Imageها و PDFها را در مسیرهای مشخص مجاز می‌کند.

`standard@1` مجموعه‌ی عمومی‌تری از Ruleهای سازمانی شامل جلوگیری از Binary، Secret، فایل‌های حساس، Force Push و حذف Branchهای اصلی است.

`strict@1` محدودیت‌های بیشتری مانند Commit Message Convention و Branch Naming Convention دارد.

`policy-config-guard@1` از Repository مربوط به خود Policyها محافظت می‌کند و اجازه‌ی تغییر Versionهای منتشرشده را نمی‌دهد.

## امنیت معماری

مزیت اصلی این معماری در محل Enforcement آن است.

اگر Policy فقط در Pre-commit اجرا شود، Developer می‌تواند آن را با:

```bash
git commit --no-verify
```

یا با حذف Hook دور بزند.

اگر Policy فقط در CI اجرا شود، Commit قبلاً وارد Git server شده است و CI فقط بعداً متوجه نقض Policy می‌شود.

اما `pre-receive` روی Server پیش از Update شدن Ref اجرا می‌شود.

بنابراین Trust Boundary واقعی به این صورت است:

```text
Untrusted Developer
       |
       v
Git Push
       |
       v
Server-side pre-receive
       |
       v
Policy Enforcement
       |
       +------ ACCEPT
       |
       +------ REJECT
```

Developer نمی‌تواند Server-side Hook را از روی سیستم خودش Disable کند.

## محدودیت‌های نسخه‌ی فعلی

نسخه‌ی فعلی پروژه MVP است و محدودیت‌هایی دارد.

Tagها تحت Policyهای معمول Branch بررسی نمی‌شوند.

Git LFS به‌صورت کامل Scan نمی‌شود، زیرا Git Repository معمولاً فقط Pointer مربوط به LFS Object را مشاهده می‌کند.

برای Audit Log باید Log Rotation مناسب در Production در نظر گرفته شود.

Transportهای Deployment باید پیش از استفاده در Production با Topology واقعی GitLab تست شوند.

Deployment روی GitLab نیازمند دسترسی حساس به Gitaly و Hook directory است و بهتر است Sudo Permissionها تا حد امکان محدود شوند.

همچنین Assignment فعلی بر مبنای Project/Profile طراحی شده است و هر Project یک Profile مؤثر دارد. اگر Policyهای کاملاً Global مانند Block کردن یک User در تمام Repositoryهای سازمان لازم باشند، بهتر است مفهوم Global Rule یا Global Policy جداگانه به معماری اضافه شود تا مجبور نباشیم Profile اصلی هر Project را جایگزین کنیم.

## جریان کامل از نوشتن Policy تا Reject شدن Push

اگر تمام معماری را در یک Flow واحد خلاصه کنیم، روند به شکل زیر است:

```text
Platform Admin
      |
      v
profiles/my-policy/1.yaml
      |
      v
gitpolicy validate
      |
      v
Configuration valid?
      |
      +---- NO ----> stop
      |
     YES
      |
      v
gitpolicy compile
      |
      v
bundle.json
      |
      v
Deploy to Git server
      |
      |
      |                   Developer
      |                       |
      |                       v
      |                    git push
      |                       |
      +-----------------------+
                              |
                              v
                       pre-receive hook
                              |
                              v
                           hook.py
                              |
                              v
                     Bundle.resolve(project)
                              |
                              v
                       assigned profile
                              |
                              v
                       build rule objects
                              |
                              v
                         engine.py
                              |
                 +------------+------------+
                 |            |            |
                 v            v            v
              Ref rules   Commit rules  Change rules
                 |            |            |
                 +------------+------------+
                              |
                              v
                          violations
                              |
                  +-----------+-----------+
                  |                       |
                  v                       v
           no blocking rule        blocking violation
                  |                       |
                  v                       v
               exit 0                  exit 1
                  |                       |
                  v                       v
           PUSH ACCEPTED            PUSH REJECTED
```

این Flow هسته‌ی اصلی پروژه است.

## جمع‌بندی

`jenkins-git-policy-python` در اصل یک Policy Enforcement Engine برای Git است. Profileها و Ruleها مشخص می‌کنند چه چیزی مجاز یا غیرمجاز است، Configuration به یک Bundle اجرایی Compile می‌شود، Assignment مشخص می‌کند هر Project از چه Profileای استفاده کند، `pre-receive hook` پیش از Accept شدن Push اجرا می‌شود، `hook.py` Request را وارد Engine می‌کند، `engine.py` Commitها و Changeهای لازم را از Git استخراج می‌کند، `rules.py` Ruleهای مربوطه را اجرا می‌کند و در نهایت Push با Exit Code صفر پذیرفته یا با Exit Code یک رد می‌شود.

Jenkins در این معماری مسئول Policy Management و Deployment است و Git server مسئول Enforcement است. این جداسازی باعث می‌شود Policy امنیتی به Pipeline وابسته نباشد و حتی عملیات‌هایی مانند Push مستقیم، Merge از GitLab UI، Web Commit یا API نیز در نقطه‌ی Server-side کنترل شوند.

در ساده‌ترین تعریف می‌توان کل معماری پروژه را در چهار جمله خلاصه کرد:

**Profile مشخص می‌کند چه Policyای باید اعمال شود. Rule مشخص می‌کند آن Policy از نظر فنی چگونه تشخیص داده شود. Engine مشخص می‌کند Rule روی چه Commitها، Refها و فایل‌هایی اجرا شود. Pre-receive Hook تضمین می‌کند که نتیجه‌ی Policy واقعاً قبل از ورود تغییرات به Repository اعمال شود.**
