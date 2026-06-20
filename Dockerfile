FROM nousresearch/hermes-agent:v2026.5.29.2

ENV PYTHONPATH=/opt/data/py-global
ENV ANTHROPIC_AUTH_TOKEN=lmstudio
ENV ANTHROPIC_BASE_URL=http://jonathans-mac-studio:1234
ENV CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

RUN apt-get update && apt-get install -y --no-install-recommends \
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
