"""gitpolicy - organisation-wide Git push/merge policies for GitLab.

Two halves:
  * the *engine* (rules, engine, gitrepo, hook) runs inside the GitLab server
    as a global pre-receive hook. It uses the Python standard library only and
    stays compatible with Python 3.9 (the interpreter embedded in GitLab).
  * the *control plane* (config, cli) runs in Jenkins: it validates the YAML
    profiles kept in the GitOps repository and compiles them into one JSON
    bundle that the hook reads.
"""

__version__ = "1.0.0"

# Version of the compiled bundle format the hook understands.
BUNDLE_FORMAT = 1
