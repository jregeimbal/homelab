FROM nousresearch/hermes-agent:v2026.7.7.2

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

COPY assets/claude-settings.json /root/.claude/settings.json
RUN npm install -g @anthropic-ai/claude-code && \
    npm cache clean --force && \
    claude --version
