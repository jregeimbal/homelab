FROM nousresearch/hermes-agent:v2026.5.29.2

RUN npm install -g @anthropic-ai/claude-code && \
    npm cache clean --force && \
    claude --version
# test v2: verify docker build with fixed version tags
