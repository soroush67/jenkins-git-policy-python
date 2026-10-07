# policy-config (GitOps repository)

This repository is the single source of truth for the GitLab push/merge
policies. Jenkins validates every change and deploys it to GitLab.

    settings.yaml                    global settings
    assignments.yaml                 project -> profile (managed by Jenkins policy/load-profile)
    profiles/<name>/<version>.yaml   one IMMUTABLE profile version per file

* To create a profile: add `profiles/<name>/1.yaml`.
* To change a profile: add `profiles/<name>/<next>.yaml` - never edit a
  published file (the pre-receive hook and the Jenkins deploy both reject it).
* Users load a profile for their project with the Jenkins job
  `policy/load-profile`.

Documentation (Persian): `docs/fa/` in the jenkins-git-policy-python repository.
