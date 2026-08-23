FROM nousresearch/hermes-agent:v2026.8.19

ENV PYTHONPATH=/opt/data/py-global

RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update && apt-get install -y --no-install-recommends \
        gh \
        gcc \
        libffi-dev \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN mkdir -p /opt/data/py-global && \
    pip install --no-cache-dir -r requirements.txt --target /opt/data/py-global && \
    rm requirements.txt

ARG OPENCODE_VERSION=1.17.9

COPY assets/opencode.json /opt/config-defaults/opencode/opencode.json

RUN ARCH=$(dpkg --print-architecture) && \
    if [ "$ARCH" = "amd64" ]; then TARGET=x64; else TARGET=arm64; fi && \
    curl -fSL "https://github.com/anomalyco/opencode/releases/download/v${OPENCODE_VERSION}/opencode-linux-${TARGET}.tar.gz" -o /tmp/opencode.tar.gz && \
    tar -xzf /tmp/opencode.tar.gz -C /usr/local/bin/ opencode && \
    rm /tmp/opencode.tar.gz

COPY assets/claude-settings.json /opt/config-defaults/claude/settings.json
COPY assets/gitconfig /opt/config-defaults/git/gitconfig
RUN npm install -g @anthropic-ai/claude-code @the-open-engine/zeroshot && \
    npm cache clean --force && \
    claude --version && \
    zeroshot --version

# Patch git-pusher-template.js: branch guard fix + PR description with overview
# and quality gate evidence (feat/quality-gate-pr-description, pending upstream merge).
COPY assets/zeroshot-patches/git-pusher-template.js /usr/local/lib/node_modules/@the-open-engine/zeroshot/src/agents/git-pusher-template.js

# Patch agent-context-sections.js: inject quality gate evidence from the triggering
# VALIDATION_RESULT message into the git-pusher agent context (feat/quality-gate-pr-description).
COPY assets/zeroshot-patches/agent-context-sections.js /usr/local/lib/node_modules/@the-open-engine/zeroshot/src/agent/agent-context-sections.js

# Patch opencode adapter to pass --dir instead of relying on process CWD.
# opencode follows .git file pointers back to the main repo when started via
# process CWD, causing agents to operate on the main repo instead of the
# worktree. Passing --dir <worktree> prevents gitdir resolution.
# Pending upstream PR to zeroshot.
COPY assets/zeroshot-patches/opencode-adapter.js /usr/local/lib/node_modules/@the-open-engine/zeroshot/lib/agent-cli-provider/adapters/opencode.js
