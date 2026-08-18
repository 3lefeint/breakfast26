# Self-update helper. Needs `git` + the Docker CLI/compose plugin to
# fetch new releases and rebuild/restart the main `breakfast` service via
# the host's Docker socket (mounted in by docker-compose.yml) — Debian's
# own apt repo doesn't reliably ship a current docker-compose-plugin, so
# this pulls the official Docker apt repo instead. `openssh-client` is
# needed because the repo is private — fetches authenticate via a
# repo-scoped, read-only deploy key mounted in at runtime (never baked
# into the image), see docker-compose.yml.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg git openssh-client \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
       > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

# System-wide, not user-scoped — the repo is bind-mounted from the host and
# may be owned by a different UID than whatever runs this container; a
# per-user ~/.gitconfig would depend on HOME being set up for that UID,
# `--system` doesn't.
RUN git config --system --add safe.directory "*"

# GitHub's own published SSH host keys (github.com/api.github.com "meta"
# API, fetched over HTTPS/TLS), baked in at build time — so the deploy-key
# fetch at runtime can verify the host without either an interactive
# "trust on first use" prompt or blindly disabling host-key checking.
COPY updater/github_known_hosts /etc/ssh/ssh_known_hosts

WORKDIR /app
COPY updater/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY updater/app.py .

EXPOSE 8090
ENTRYPOINT ["python", "app.py"]
