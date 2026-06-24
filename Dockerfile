FROM nousresearch/hermes-agent:v2026.6.19

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
COPY assets/hermes-skills/autonomous-ai-agents/zeroshot/SKILL.md /opt/config-defaults/hermes-skills/autonomous-ai-agents/zeroshot/SKILL.md
RUN npm install -g @anthropic-ai/claude-code github:jregeimbal/zeroshot#fix/git-pusher-default-branch-guard && \
    npm cache clean --force && \
    claude --version && \
    zeroshot --version
