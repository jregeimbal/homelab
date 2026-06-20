FROM nousresearch/hermes-agent:v2026.5.29.2

RUN npm install -g @anthropic-ai/claude-code && \
    claude --version
