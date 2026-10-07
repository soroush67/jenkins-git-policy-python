# JENKINS_IMAGE: the official image by default. Where updates.jenkins.io is
# unreachable, up.sh picks a local Jenkins image that already contains the
# plugins (only missing plugins are downloaded).
ARG JENKINS_IMAGE=jenkins/jenkins:lts-jdk17
FROM ${JENKINS_IMAGE}
USER root
# python3 + PyYAML + pytest: the gitpolicy control plane and its tests.
# docker-cli: lab transport (GP_TARGET=docker:<container>); openssh-client:
# production transports (ssh:, ssh-docker:).
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-yaml python3-pytest docker-cli openssh-client \
 && rm -rf /var/lib/apt/lists/*
USER jenkins
COPY plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN missing=""; \
    for p in $(grep -v '^#' /usr/share/jenkins/ref/plugins.txt); do \
        [ -e "/usr/share/jenkins/ref/plugins/$p.jpi" ] || [ -e "/usr/share/jenkins/ref/plugins/$p.hpi" ] || missing="$missing $p"; \
    done; \
    if [ -n "$missing" ]; then jenkins-plugin-cli --plugins $missing; else echo "all plugins already in the base image"; fi
COPY casc.yaml /usr/share/jenkins/ref/casc.yaml
