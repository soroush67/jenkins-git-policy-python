// Job DSL run by policy-admin/deploy after every successful deploy.
// Bindings: PROFILES (newline separated name@version), TOOL_REPO, BRANCH, GIT_CRED.
def profiles = PROFILES.readLines().findAll { it.trim() }

def fromRepo = { job, String script ->
    job.with {
        definition {
            cpsScm {
                scm {
                    git {
                        remote { url(TOOL_REPO); credentials(GIT_CRED) }
                        branch("*/${BRANCH}")
                    }
                }
                scriptPath(script)
                lightweight(true)
            }
        }
    }
}

folder('policy') {
    displayName('Git Policy')
    description('Load an organisation policy profile for your GitLab project.')
}

fromRepo(pipelineJob('policy/load-profile') {
    description('''Load one of the published policy profiles for a GitLab project.
From then on every push and every merge request merge into that project is checked by the profile.
You must be Maintainer of the project in GitLab. Profiles are defined by the platform team and cannot be edited here.''')
    parameters {
        stringParam('PROJECT', '', 'GitLab project path, e.g. demo/app-a')
        choiceParam('PROFILE', profiles ?: ['(no profiles published)'], 'Profile to load (name@version, newest version first). See the job policy/show for the rules of each profile.')
        booleanParam('REPLACE_EXISTING', false, 'The project already has a profile and you want to switch to this one.')
    }
}, 'jenkins/Jenkinsfile.load-profile')

fromRepo(pipelineJob('policy/show') {
    description('Show the published profiles and their rules, or the profile of one project.')
    parameters {
        stringParam('PROJECT', '', 'GitLab project path (empty: list everything)')
    }
}, 'jenkins/Jenkinsfile.show')

fromRepo(pipelineJob('policy-admin/unload-profile') {
    description('Admin only: remove the profile of a project (its pushes are no longer checked).')
    parameters {
        stringParam('PROJECT', '', 'GitLab project path')
    }
}, 'jenkins/Jenkinsfile.unload-profile')
