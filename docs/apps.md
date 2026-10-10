# Apps Reference

## Hermes Agent (jon-agent namespace)

**HelmRelease:** `hermes` in `jon-agent` namespace  
**Chart source:** GitRepository `hermes-agent` (github.com/ultraworkers/hermes-agent-helm-chart)  
**Data volume:** 5Gi Longhorn (`hermes-hermes-agent-data`)

### Components

The Hermes Helm chart deploys a single pod with 2 containers:

1. **hermes** (main) — Hermes Agent runtime
   - Image: `nousresearch/hermes-agent:main`
   - API server port: 8642
   - Exposes OpenAI-compatible API at `/v1`

2. **browserless-chromium** — Browser automation
   - Image: `ghcr.io/browserless/chromium:latest`
   - CDP endpoint: `ws://127.0.0.1:3000/`
   - Resources: 2 CPU / 4Gi memory limit

**Python dependencies** (not a container) — core packages (discord.py, python-telegram-bot, python-dotenv) live in the image's sealed venv `/opt/hermes/.venv`; optional extras (faster-whisper, firecrawl, …) are lazy-installed by hermes into `/opt/data/lazy-packages` (appended to `sys.path`; the venv always wins)

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
- **Python dependencies:** same as jon-agent — sealed venv in the image plus hermes-managed extras (e.g. `faster-whisper`) lazy-installed into `/opt/data/lazy-packages`
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

## Trading Assistant (trading-assistant namespace)

**Source:** github.com/jregeimbal/trading-assistant (private)
**Image:** `ghcr.io/jregeimbal/trading-assistant:<datetime_sha>` (private; pulled with the `ghcr-pull` SealedSecret), built by that repo's CI for amd64 and arm64
**Manifests:** `flux/apps/trading-assistant.yaml`
**Purpose:** Jon's S&P 500 strategy research (backtests, strategy builder, reports) and the daily trading agent that runs strategies in brokerage accounts (Webull paper now; live and IRA accounts later)

### Components

| Component | Kind | Details |
|---|---|---|
| `trading-postgres` | StatefulSet + Service | Postgres 18, 10Gi Longhorn at `/var/lib/postgresql` (the Postgres 18 volume path). Prices, strategies, backtest runs, accounts, agent orders. |
| `trading-assistant-web` | Deployment | `ta serve`: strategy builder, Runs, Agents tab, reports. 5Gi Longhorn at `/data` (price cache, backtest artifacts). Memory limit 3Gi (full backtests peak ~1.6 GB). |
| `trading-assistant` | Service (Tailscale LB) | Tailnet only: `trading-assistant.<tailnet>.ts.net`, plus an HTTP Basic login on every page and API route (user `jon`). Only `/healthz` is open, for probes. The Agents tab can submit orders. |
| `trading-agent-plan` | CronJob, weekdays 18:15 ET | Refreshes prices (last 45 days, plus full history only for tickers whose dividend/split adjustments changed), records fills, plans the next session's orders. A few minutes. |
| `trading-agent-execute` | CronJob, weekdays 15:50 ET | Submits planned orders as market orders before the 4 pm close. Skipped if it can't start within 5 minutes; never retried. |
| `trading-agent-execute-open` | CronJob, weekdays 9:40 ET | Submits only the planned sells, for accounts whose "Sells submit at" setting is the open; their buys still go in at 15:50. Same skip/no-retry rules. |
| `trading-data-reference` | CronJob, 1st of month 07:00 ET | S&P 500 membership history and sector classifications |

All containers run as non-root with a read-only root filesystem, except Postgres (UID 999, writable data dir). Jobs rebuild their price cache from Postgres in an `emptyDir`.

### Secrets

- `trading-assistant-secrets`: `POSTGRES_PASSWORD`, `TA_DATABASE_URL`, `TA_AUTH_PASSWORD` (web UI login; the plaintext was shared with Jon directly, not stored in the repo), `WEBULL_PAPER_APP_KEY`, `WEBULL_PAPER_APP_SECRET`, `TA_SECRET_KEY` (master key that encrypts API keys entered on an account in the Agents tab; they're stored encrypted in Postgres and never shown again). Live Webull keys (`WEBULL_APP_KEY` / `WEBULL_APP_SECRET`) are deliberately left out of the secret; a live account can take its keys in the Agents tab instead. If `TA_SECRET_KEY` is lost or changed, saved keys must be re-entered on each account (nothing else is affected).
- `ghcr-pull`: docker-registry secret with a read:packages-only token. Create it with `deploy/seal-ghcr-pull-secret.sh` in the trading-assistant repo.

### Operations

- **Run a job now:** `kubectl -n trading-assistant create job --from=cronjob/trading-agent-plan plan-manual-$(date +%s)`
- **Logs:** `kubectl -n trading-assistant logs job/<name>`
- **Pause trading:** `kubectl -n trading-assistant patch cronjob trading-agent-execute -p '{"spec":{"suspend":true}}'` (and the same for `trading-agent-execute-open`). This won't survive the next Flux sync, so for a lasting pause set `suspend: true` in the manifest, or turn off auto-submit for the account in the Agents tab.
- **Upgrade:** bump the image tag on all four containers in `flux/apps/trading-assistant.yaml`.
- **Change the UI password:** re-seal `trading-assistant-secrets` with a new `TA_AUTH_PASSWORD`, keeping the other keys (`kubectl get secret` then `kubeseal`), then restart `trading-assistant-web`.

---

## Authentik (authentik namespace)

**Manifests:** `flux/apps/authentik.yaml`, `flux/apps/authentik-secrets.sealedsecret.yaml`
**Chart source:** `authentik` HelmRepository (charts.goauthentik.io), version 2026.8.3
**Purpose:** Identity provider (SSO via OIDC, SAML, LDAP, and forward auth) for the homelab apps

### Components

| Component | Kind | Details |
|---|---|---|
| `authentik-postgres` | StatefulSet + Service | Postgres 18, 5Gi Longhorn at `/var/lib/postgresql` (the Postgres 18 volume path). The chart's bundled Bitnami Postgres is disabled. |
| `authentik-server` | Deployment (chart) | Web UI, API, and the embedded outpost. Memory limit 1.5Gi. |
| `authentik-worker` | Deployment (chart) | Background tasks, blueprints, and managed outposts. Memory limit 1.5Gi. |
| `authentik` | Ingress (`tailscale` class) | Tailnet only, with HTTPS: `https://authentik.<tailnet>.ts.net`. Tailscale issues the Let's Encrypt cert, which OIDC redirects and secure cookies need. |

Since 2025.10, Authentik no longer needs Redis.

### Secrets

- `authentik-secrets`: `AUTHENTIK_SECRET_KEY` (signs cookies and derives unique user IDs; **never change it** after the first install), `AUTHENTIK_POSTGRESQL__PASSWORD` (Postgres reads the same key), `AUTHENTIK_BOOTSTRAP_PASSWORD` (the first-run password for `akadmin`; it's read only when the database is empty).

### Operations

- **First login:** user `akadmin`, password from `kubectl -n authentik get secret authentik-secrets -o jsonpath='{.data.AUTHENTIK_BOOTSTRAP_PASSWORD}' | base64 -d`. Then create your own admin user, add it to `authentik Admins`, and deactivate `akadmin`.
- **SSO apps:** Grafana and Open WebUI are defined in the `authentik-blueprint-sso` ConfigMap in `flux/apps/authentik.yaml`, a blueprint the worker applies on start and whenever it changes. To add an app, add a provider and application entry there (client ID in the blueprint, secret via `!Env` from `authentik-oidc-clients`), and seal the same secret into the app's namespace. Pods reach `https://authentik.<tailnet>.ts.net` directly, because node DNS forwards to MagicDNS.
  - **Grafana:** "Sign in with authentik". Members of `authentik Admins` get the Grafana Admin role, and everyone else gets Viewer. The local `admin` login still works.
  - **Open WebUI:** "Continue with authentik". Accounts are tied to the authentik user's OIDC subject, not their email. Merging by email is deliberately off: authentik sends `email_verified: false`, so a user who could change their email could take over someone else's account. The first account created becomes admin, and later SSO users start as `pending`. If an SSO login's email already belongs to a local account, Open WebUI refuses it ("email taken").
  - **Longhorn:** the UI has no login of its own, so authentik proxies it. The `longhorn` Tailscale Ingress points at `authentik-server`, whose embedded outpost matches the `longhorn.<tailnet>.ts.net` host to a proxy provider, requires an `authentik Admins` login, and then forwards to `longhorn-frontend`. The blueprint sets the embedded outpost's whole provider list, so add any future proxy providers to it there, not in the UI.
- **Upgrade:** bump `version` in the HelmRelease. Upgrade one minor release at a time (for example 2026.8 → 2026.10), and back up Postgres first: `kubectl -n authentik exec authentik-postgres-0 -- pg_dump -U authentik authentik > authentik.sql`.
- **Fresh install must migrate in one uninterrupted run.** If the first migration run on an empty database is killed partway, the next start runs the legacy `tenant_to_brand` system migration. That migration rewrites the partial history (`authentik_tenants` → `authentik_brands`), and every later start fails with `InconsistentMigrationHistory`. On these nodes the first run takes more than 10 minutes, which is why the HelmRelease has a 20m timeout and a 30m `progressDeadlineSeconds`. To recover a fresh install that never came up:
  1. `flux suspend hr authentik -n authentik`, then scale `authentik-server` and `authentik-worker` to 0. Wait until their pods are gone, or they'll reconnect and race the reset.
  2. Drop and recreate the `authentik` database.
  3. Run the migrations alone in a one-off pod: the server image with the same env, `command: ["python", "-m", "lifecycle.migrate"]`, `workingDir: /`.
  4. When it succeeds, scale the server and worker back to 1 and `flux resume hr authentik -n authentik`.

  Never drop the database of an install that has users. This recovery is only for an install that never finished its first start.

---

## Open WebUI (open-webui namespace)

**HelmRelease:** `open-webui` in `open-webui` namespace  
**Chart source:** `openwebui` HelmRepository (open-webui.github.io/helm-charts)  
**Version:** 14.6.0  
**Data volume:** 10Gi Longhorn

### Components

- Open WebUI web interface (ghcr.io/open-webui/open-webui)
- Exposed through a Tailscale Ingress at `https://open-webui.<tailnet>.ts.net` (Service is ClusterIP)
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
- **Access:** Tailscale Ingress at `https://grafana.<tailnet>.ts.net` (Service is ClusterIP)
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
| Open WebUI | open-webui  | 10Gi Longhorn| Tailscale Ingress (HTTPS) | 14.6.0      |
| Prometheus | monitoring  | 5Gi Longhorn| ClusterIP  | 29.8.0        |
| Grafana    | monitoring  | 5Gi Longhorn| Tailscale Ingress (HTTPS) | 10.5.15     |
