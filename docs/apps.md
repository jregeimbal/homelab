# Apps Reference

## Hermes Agent (jon-agent namespace)

**HelmRelease:** `hermes` in `jon-agent` namespace  
**Chart source:** GitRepository `hermes-agent` (github.com/ultraworkers/hermes-agent-helm-chart)  
**Data volume:** 5Gi Longhorn (`hermes-hermes-agent-data`)

### Components

The Hermes Helm chart deploys a single pod with 3 containers:

1. **hermes** (main) — Hermes Agent runtime
   - Image: `nousresearch/hermes-agent:main`
   - API server port: 8642
   - Exposes OpenAI-compatible API at `/v1`

2. **browserless-chromium** — Browser automation
   - Image: `ghcr.io/browserless/chromium:latest`
   - CDP endpoint: `ws://127.0.0.1:3000/`
   - Resources: 2 CPU / 4Gi memory limit

3. **pip-install** (init container) — Dependency installation
   - Installs `discord.py`, `python-telegram-bot`, `faster-whisper` to `/opt/data/py-global`
   - Ensures packages are available on persistent volume

### Integrations

| Platform   | Config                              |
|------------|-------------------------------------|
| WhatsApp   | Self-chat mode, allowed users       |
| Telegram   | Home channel: -1003912742246        |
| Discord    | Home channel: 1490811659214913698   |

All platforms restricted to specific allowed user IDs.

### Model Configuration

- **Provider:** auto
- **Default model:** `mtplx-qwen38-27b-optimized-quality`
- **Base URL:** `http://jonathans-mac-studio:8000/v1` (local workstation running Ollama)
- **STT:** Enabled (faster-whisper)

### Settings

- **Max turns:** 90
- **Gateway timeout:** 1800s
- **Tool use enforcement:** enabled
- **Secret redaction:** enabled
- **Tirith security:** enabled (fail-open)

### Secrets

Referenced from `hermes-jon-secrets` SealedSecret. Contains:
- API server key
- OpenRouter API key
- HuggingFace token
- Telegram bot token

---

## Hermes Agent (ana-agent namespace)

**HelmRelease:** `hermes-ana` in `ana-agent` namespace  
**Chart source:** GitRepository `hermes-agent` (github.com/ultraworkers/hermes-agent-helm-chart)  
**Data volume:** 5Gi Longhorn (`hermes-ana-data`)

### Key Differences from jon-agent

- **No Discord or Telegram** — only WhatsApp integration (`"15404194480"`)
- **SealedSecret:** `hermes-ana-secrets` (API server key)
- **WhatsApp reply prefix:** `"🤖 *Ana's Agent*\n──────\n"`
- **No pip-install init container for telegram** — only installs `discord.py` and `faster-whisper` (telegram package not needed)
- **Data volume claim name:** `hermes-ana-data` (vs `hermes-hermes-agent-data` for jon)
- **fullnameOverride:** `hermes-ana` (vs default `hermes` for jon)
- **Base URL:** Same local model endpoint (`http://jonathans-mac-studio:1234/v1`)

### Shared Components

All other components match the jon-agent configuration:
- Same image (`nousresearch/hermes-agent:main`)
- Same browserless-chromium sidecar
- Same agent settings (max turns: 90, gateway timeout: 1800s, tool enforcement enabled)
- Same STT (faster-whisper) and Tirith security settings

---

## Hermes Agent — Wander Agent (wander-agent namespace)

**HelmRelease:** `hermes-wander` in `wander-agent` namespace
**Chart source:** GitRepository `hermes-agent` (github.com/ultraworkers/hermes-agent-helm-chart)
**Data volume:** 30Gi Longhorn
**Purpose:** Jon's personal travel-planning agent (flight/hotel research, itineraries, trip logistics)

### Key Differences from jon-agent

- **WhatsApp only** — no Telegram or Discord integration
- **New WhatsApp identity** — brand-new number/session, not jon-agent's; linked via QR scan on first boot (no static token, session lives on the PVC)
- **WhatsApp mode: `bot`** (vs `self-chat` for jon) — open to any sender (`WHATSAPP_ALLOWED_USERS=*`, `WHATSAPP_ALLOW_ALL_USERS=true`), group chats allowed (`WHATSAPP_GROUP_POLICY=open`), read receipts enabled. `WHATSAPP_ALLOW_ALL_USERS` is required — the gateway refuses to start at all with an open dm/group policy unless it's set
- **SealedSecret:** `hermes-wander-secrets` (API server key, dashboard session token, Firecrawl key)
- **WhatsApp reply prefix:** `"🤖 *Wander Agent*\n──────\n"`
- **No Context7 MCP server or GitHub token passthrough** — not relevant to travel planning
- **fullnameOverride:** `hermes-wander` (vs default `hermes` for jon)
- **Dashboard basic auth configured explicitly** (`config.values.dashboard.basic_auth` in `hermes-wander.yaml`) — as of a June 2026 image hardening, `hermes dashboard --insecure` no longer bypasses auth on a `0.0.0.0` bind; jon-agent/ana-agent's dashboards work only because an auth provider was registered out-of-band on their (older) persistent volumes. A brand-new PVC has none, so this had to be set explicitly or `hermes-desktop` crash-loops. The password hash is committed; the plaintext password was shared with Jon directly, not stored in the repo

### Shared Components

Otherwise mirrors jon-agent: browser automation, desktop dashboard container, STT, same disabled-skills list, same local model endpoint, same security/Tirith settings.

### Setup Required Before Deploy

Nothing outstanding — `API_SERVER_KEY` and `HERMES_DASHBOARD_SESSION_TOKEN` are self-generated and sealed already, and `FIRECRAWL_API_KEY` reuses the same Firecrawl key as jon-agent (pulled from the live `hermes-jon-secrets` and re-sealed for this namespace). On first boot, scan the WhatsApp QR code from the pod logs to link the new number.

**Note:** unlike jon-agent's allowlisted `self-chat` mode, Wander Agent runs in open `bot` mode (`WHATSAPP_ALLOWED_USERS=*`, `WHATSAPP_GROUP_POLICY=open`) — anyone who has or finds the linked number can message it, including in group chats.

---

## Open WebUI (open-webui namespace)

**HelmRelease:** `open-webui` in `open-webui` namespace  
**Chart source:** `openwebui` HelmRepository (open-webui.github.io/helm-charts)  
**Version:** 14.6.0  
**Data volume:** 10Gi Longhorn

### Components

- Open WebUI web interface (ghcr.io/open-webui/open-webui)
- Exposed via LoadBalancer with `tailscale` class → accessible on Tailnet
- Default model: `meta-llama/llama-3.1-8b-instruct:latest`

### API Configuration

- **OpenAI API URL:** `http://hermes-hermes-agent.jon-agent.svc.cluster.local:8642/v1`
- **API key:** from `open-webui-secret` SealedSecret
- **Ollama:** disabled
- **Pipelines:** disabled

### Secrets

- `open-webui-secret` — General Open WebUI secrets and Hermes API key

---

## Prometheus (monitoring namespace)

**HelmRelease:** `prometheus` in `monitoring` namespace  
**Chart source:** `prometheus-community` HelmRepository  
**Version:** 29.8.0

### Configuration

- **Storage:** 5Gi Longhorn (volumeClaimTemplate)
- **Access:** ClusterIP (internal only, scraped by Grafana)

---

## Grafana (monitoring namespace)

**HelmRelease:** `grafana` in `monitoring` namespace  
**Chart source:** `grafana` HelmRepository  
**Version:** 10.5.15

### Configuration

- **Storage:** 5Gi Longhorn
- **Admin password:** admin (change in production)
- **Access:** LoadBalancer with `tailscale` class → accessible on Tailnet
- **Data source:** Prometheus (`http://prometheus-server.monitoring.svc.cluster.local`)

### Custom Dashboards

Custom node dashboard available at `assets/grafana-dashboards/nodes.json`.

---

## App Summary

| App        | Namespace    | Storage     | Access     | Chart Version |
|------------|-------------|-------------|------------|---------------|
| Hermes (jon) | jon-agent  | 5Gi Longhorn| ClusterIP  | from git      |
| Hermes (ana) | ana-agent  | 5Gi Longhorn| ClusterIP  | from git      |
| Hermes (wander) | wander-agent | 30Gi Longhorn| ClusterIP  | from git   |
| Open WebUI | open-webui  | 10Gi Longhorn| Tailscale LB | 14.6.0      |
| Prometheus | monitoring  | 5Gi Longhorn| ClusterIP  | 29.8.0        |
| Grafana    | monitoring  | 5Gi Longhorn| Tailscale LB | 10.5.15     |
