<div dir="rtl">

# jenkins-git-policy-python

> Organisation-wide Git push/merge policies for GitLab, as immutable versioned **profiles**, managed GitOps-style by Jenkins. Python, global pre-receive hook. Docs in Persian: [`docs/fa/`](docs/fa/01-OVERVIEW-FA.md).

**gitpolicy** به شما اجازه می‌دهد برای GitLab سازمان policy بنویسید. مثلاً: فایل باینری push نشود، و اگر قبلاً push شده، با merge به برنچ دیگری منتقل نشود. هر policy یک **پروفایل** نسخه‌دار و تغییرناپذیر است. شما پروفایل را می‌سازید و کاربر آن را از Jenkins برای پروژه‌ی خودش load می‌کند. همه‌چیز GitOps است: Jenkins مخزن policy را validate می‌کند و روی GitLab مستقر می‌کند.

## شروع سریع

<div dir="ltr">

```bash
python3 -m venv .venv && .venv/bin/pip install pytest pyyaml
.venv/bin/python -m pytest -q          # 94 tests

lab/up.sh                              # GitLab :8940 + Jenkins :8096, prints the logins
tests/e2e/lab-e2e.sh                   # 27 end-to-end checks on the lab
samples/try-it.sh demo/app-a           # push sample files, see what is rejected
```

</div>

## مستندات

| سند | برای |
|---|---|
| [01-OVERVIEW-FA.md](docs/fa/01-OVERVIEW-FA.md) | معرفی، معماری، مفاهیم، امنیت، محدودیت‌ها |
| [02-INSTALL-FA.md](docs/fa/02-INSTALL-FA.md) | نصب از صفر: تست‌ها، lab، و نصب نهایی روی GitLab و Jenkins سازمان |
| [03-PROFILES-FA.md](docs/fa/03-PROFILES-FA.md) | نوشتن پروفایل، مرجع کامل قوانین (ادمین) |
| [04-USER-GUIDE-FA.md](docs/fa/04-USER-GUIDE-FA.md) | راهنمای کاربر: load کردن پروفایل، درست کردن push رد‌شده |
| [05-OPERATIONS-FA.md](docs/fa/05-OPERATIONS-FA.md) | نگهداری، rollback، audit log، عیب‌یابی |
| [HANDOFF-FA.md](HANDOFF-FA.md) | خلاصه‌ی کامل پروژه برای ادامه‌ی کار در جای دیگر |

## ساختار

<div dir="ltr">

```
gitpolicy/          engine (hook, stdlib only, Python 3.9+) + control plane (config/cli, needs PyYAML)
policy-config/      sample GitOps policy repository (profiles, assignments, settings)
jenkins/            Jenkinsfiles + jobs.groovy (Job DSL for the user jobs)
deploy/             push.sh (docker|ssh transport) + server-side install functions + hook wrapper
lab/                docker compose lab: GitLab CE 17.10.5 + Jenkins (JCasC)
samples/            extra profile examples + scripts that trigger each rule
tests/              pytest (real git pushes through the real hook) + e2e/lab-e2e.sh
docs/fa/            Persian documentation
```

</div>

</div>
