FROM nousresearch/hermes-agent:v2026.5.29.2

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN mkdir -p /opt/data/py-global && \
    pip install --no-cache-dir -r requirements.txt --target /opt/data/py-global && \
    rm requirements.txt

RUN npm install -g @anthropic-ai/claude-code && \
    npm cache clean --force && \
    claude --version
