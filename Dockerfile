FROM nousresearch/hermes-agent:v0.22.5
# CI: see docs/ci-gates.md for pre-merge gates

RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update && apt-get install -y --no-install-recommends \
        gh \
        gcc \
        libffi-dev \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

ARG OPENCODE_VERSION=1.17.9

COPY assets/opencode.json /opt/config-defaults/opencode/opencode.json

RUN ARCH=$(dpkg --print-architecture) && \
    if [ "$ARCH" = "amd64" ]; then TARGET=x64; else TARGET=arm64; fi && \
    curl -fSL "https://github.com/anomalyco/opencode/releases/download/v${OPENCODE_VERSION}/opencode-linux-${TARGET}.tar.gz" -o /tmp/opencode.tar.gz && \
    tar -xzf /tmp/opencode.tar.gz -C /usr/local/bin/ opencode && \
    rm /tmp/opencode.tar.gz

COPY assets/claude-settings.json /opt/config-defaults/claude/settings.json
COPY assets/gitconfig /opt/config-defaults/git/gitconfig

# The v0.22.x base reorganizes the toolchain: node + npm are staged in the
# pm-managed store (HERMES_RUNTIME_DIR, /opt/hermes/tools) with only the
# binaries symlinked into /usr/local/bin, so `npm install -g` no longer lands
# under /usr/local — the global prefix follows npm's own store entry. Resolve
# the prefix at build time instead of hardcoding a layout, and put its bin dir
# on PATH for the verification below (the new prefix/bin is not on the default
# PATH). The runtime PATH is handled by hermes's store activation, which puts
# the store's bin dirs first.
#
# The bundled npm (12.x) blocks dependency install scripts by default under
# its allowScripts policy (npm 12 runs scripts only for explicitly allowed
# packages). Allow claude-code's postinstall — it downloads the platform
# binary, and without it `claude --version` fails (exit 2). The
# project-scoped better-sqlite3 install (an implicit node-gyp build) is
# allowed via the project .npmrc, since --allow-scripts is rejected on
# project-scoped installs.
#
# Workaround: zeroshot pins better-sqlite3@^12.6.2, whose native addon doesn't
# build against hermes-agent's bundled Node 26 (v8::PropertyCallbackInfo lost
# ::This()), which fails npm's normal install before we ever get a chance to
# swap it. Install zeroshot with scripts skipped so the broken build never
# runs, force a Node 26-compatible better-sqlite3 in its place, then rebuild
# zeroshot's other native deps (node-pty, puppeteer) that got skipped too.
# Drop this once zeroshot bumps its own better-sqlite3 pin upstream.
RUN NPM_PREFIX=$(npm config get prefix) && \
    echo "npm prefix: $NPM_PREFIX" && \
    PATH="$NPM_PREFIX/bin:$PATH" npm install -g --allow-scripts=@anthropic-ai/claude-code @anthropic-ai/claude-code && \
    PATH="$NPM_PREFIX/bin:$PATH" npm install -g --ignore-scripts @the-open-engine/zeroshot && \
    (cd "$NPM_PREFIX/lib/node_modules/@the-open-engine/zeroshot" && \
        printf 'allow-scripts=better-sqlite3,node-pty,puppeteer\n' > .npmrc && \
        npm install better-sqlite3@^12.11.1 --no-save && \
        npm rebuild node-pty puppeteer) && \
    printf 'require("better-sqlite3"); require("node-pty"); console.log("zeroshot native deps load ok");\n' > "$NPM_PREFIX/lib/node_modules/@the-open-engine/zeroshot/.native-probe.js" && \
    (cd "$NPM_PREFIX/lib/node_modules/@the-open-engine/zeroshot" && node .native-probe.js) && \
    rm "$NPM_PREFIX/lib/node_modules/@the-open-engine/zeroshot/.native-probe.js" && \
    PATH="$NPM_PREFIX/bin:$PATH" npm cache clean --force && \
    PATH="$NPM_PREFIX/bin:$PATH" claude --version && \
    PATH="$NPM_PREFIX/bin:$PATH" zeroshot --version

# Stage the zeroshot patches in a fixed location (COPY cannot use shell
# variables), then apply them against the resolved global prefix. Each target
# directory must already exist: a silent miss would leave zeroshot unpatched.
#
# Patch git-pusher-template.js: branch guard fix + PR description with overview
# and quality gate evidence (feat/quality-gate-pr-description, pending upstream merge).
# Patch agent-context-sections.js: inject quality gate evidence from the triggering
# VALIDATION_RESULT message into the git-pusher agent context (feat/quality-gate-pr-description).
# Patch opencode adapter to pass --dir instead of relying on process CWD.
# opencode follows .git file pointers back to the main repo when started via
# process CWD, causing agents to operate on the main repo instead of the
# worktree. Passing --dir <worktree> prevents gitdir resolution.
# Pending upstream PR to zeroshot.
COPY assets/zeroshot-patches/ /opt/zeroshot-patches/
RUN NPM_PREFIX=$(npm config get prefix) && \
    ZS="$NPM_PREFIX/lib/node_modules/@the-open-engine/zeroshot" && \
    test -d "$ZS" || { echo "zeroshot not installed at $ZS" >&2; exit 1; } && \
    for d in src/agents src/agent lib/agent-cli-provider/adapters; do \
        test -d "$ZS/$d" || { echo "zeroshot layout missing $d" >&2; exit 1; }; \
    done && \
    cp /opt/zeroshot-patches/git-pusher-template.js "$ZS/src/agents/git-pusher-template.js" && \
    cp /opt/zeroshot-patches/agent-context-sections.js "$ZS/src/agent/agent-context-sections.js" && \
    cp /opt/zeroshot-patches/opencode-adapter.js "$ZS/lib/agent-cli-provider/adapters/opencode.js" && \
    rm -rf /opt/zeroshot-patches