# Homelab

A 6-node Kubernetes homelab running k0s on SO Quartz devices, managed via GitOps with Flux CD.

## Architecture

```mermaid
graph TB
    subgraph "Homelab Cluster — SO Quartz (DietPi)"
        subgraph "k0s Controller"
            C1[homelab-soquartz-1<br/>Controller]
        end
        subgraph "k0s Workers"
            W1[homelab-soquartz-2<br/>Worker]
            W2[homelab-soquartz-3<br/>Worker]
            W3[homelab-soquartz-4<br/>Worker]
            W4[homelab-soquartz-5<br/>Worker]
            W5[homelab-soquartz-6<br/>Worker]
        end
    end

    subgraph "GitOps"
        REPO[Git Repository<br/>homelab]
        FLUX[Flux CD]
    end

    subgraph "Infrastructure"
        LS[Longhorn<br/>Storage]
        ML[MetalLB<br/>Networking]
        TS[Tailscale<br/>Operator]
        NLD[NodeLocal DNSCache<br/>per-node DNS]
        SS[SealedSecrets]
    end

    subgraph "Applications"
        HERMES_J[Hermes Agent<br/>jon-agent]
        HERMES_A[Hermes Agent<br/>ana-agent]
        HERMES_W[Hermes Agent<br/>wander-agent]
        OW[Open WebUI<br/>open-webui]
        PROM[Prometheus<br/>monitoring]
        GRAF[Grafana<br/>monitoring]
    end

    subgraph "External"
        WA[WhatsApp]
        TG[Telegram]
        DC[Discord]
        MODEL[Local LLM (mtplx)<br/>jonathans-mac-studio]
    end

    REPO --> FLUX
    FLUX --> C1
    FLUX --> W1
    FLUX --> W2
    FLUX --> W3
    FLUX --> W4
    FLUX --> W5

    C1 --> LS
    C1 --> ML
    C1 --> TS
    C1 --> NLD
    C1 --> SS
    NLD -->|node DNS via systemd-resolved| TS

    W1 --> LS
    W2 --> LS
    W3 --> LS
    W4 --> LS
    W5 --> LS

    HERMES_J --> WA
    HERMES_J --> TG
    HERMES_J --> DC
    HERMES_J --> MODEL
    HERMES_A --> WA
    HERMES_A --> TG
    HERMES_A --> DC
    HERMES_A --> MODEL
    HERMES_W --> WA
    HERMES_W --> MODEL

    OW --> HERMES_J
    GRAF --> PROM
```

## Quick Start

1. **Burn DietPi images** to MicroSD cards for each node using `setup/burn-url-to-device.sh`
2. **Boot nodes** and configure network access
3. **Deploy the cluster** with `k0sctl apply`
4. **Bootstrap Flux CD** to start GitOps management

See the [Setup Guide](docs/setup-guide.md) for detailed instructions.

## Cluster

| Node                  | Role     | OS     |
|-----------------------|----------|--------|
| homelab-soquartz-1    | controller | DietPi |
| homelab-soquartz-2    | worker   | DietPi |
| homelab-soquartz-3    | worker   | DietPi |
| homelab-soquartz-4    | worker   | DietPi |
| homelab-soquartz-5    | worker   | DietPi |
| homelab-soquartz-6    | worker   | DietPi |

- **Orchestration:** k0s (single-binary Kubernetes)
- **CNI:** Kuberouter
- **Provisioning:** k0sctl

[Read more about the cluster setup](docs/setup-guide.md#step-3-deploy-k0s-cluster)

## Overview

GitOps-managed Kubernetes cluster with Tailscale for external access and Longhorn for distributed storage. Flux CD continuously reconciles cluster state from this repository.

[Full architecture details →](docs/architecture.md)

## What's Running

| App        | Namespace    | Description                                    | Access         |
|------------|-------------|------------------------------------------------|----------------|
| Hermes (jon) | jon-agent  | AI agent with WhatsApp/Telegram/Discord integrations | Tailscale LB (API 8642, webui 8787, desktop 9119) + Ingress (HTTPS dashboard, authentik SSO) |
| Hermes (ana) | ana-agent  | AI agent (second instance)                     | ClusterIP      |
| Hermes (wander) | wander-agent | Personal travel-planning agent, WhatsApp only | Tailscale LB (API 8642, webui 8787, desktop 9119) |
| Open WebUI | open-webui  | Web UI for LLM interaction, backed by Hermes   | Tailscale Ingress (HTTPS) |
| Prometheus | monitoring  | Metrics collection and storage                 | ClusterIP      |
| Grafana    | monitoring  | Metrics visualization dashboard                | Tailscale Ingress (HTTPS) |
| Authentik  | authentik   | Identity provider (SSO/OIDC) for homelab apps  | Tailscale Ingress (HTTPS) |
| Trading Assistant | trading-assistant | Strategy research UI and daily trading agent (Webull paper) | Tailscale Ingress (HTTPS, authentik SSO) |
| Sofarmap | sofarmap | Printable maps of Jon's travels (PostGIS, map editor) | Tailscale Ingress (HTTPS, authentik SSO) |

[Full app reference →](docs/apps.md)

## Infrastructure

| Component      | Namespace      | Purpose                              |
|---------------|----------------|--------------------------------------|
| Longhorn      | longhorn-system| Distributed block storage (UI behind authentik: `https://longhorn.<tailnet>.ts.net`) |
| MetalLB       | metallb-system | Layer 2 load balancer (fallback)     |
| Tailscale     | tailscale      | External access via Tailnet          |
| NodeLocal DNSCache | kube-system | Per-node DNS cache on 169.254.20.10 (DaemonSet on every node); external DNS via the node's systemd-resolved, tailnet names via Tailscale MagicDNS |
| SealedSecrets | flux-system    | Encrypted secrets for Git            |

[Full infrastructure reference →](docs/infrastructure.md)

## GitOps

Flux CD watches this repository and automatically applies all Kubernetes manifests. Changes to `flux/` are deployed within minutes of being pushed.

- **Source:** `flux/cluster/kustomization.yaml`
- **Apps:** `flux/apps/`
- **Infrastructure:** `flux/infra/`

[GitOps flow details →](docs/architecture.md#gitops-flow)

## CI/CD

GitHub Actions builds the custom Hermes Docker image (`ghcr.io/jregeimbal/hermes-agent-jregeimbal-homelab`, amd64 + arm64) from `Dockerfile`.

- [CI](.github/workflows/ci.yml) — YAML/JSON lint, kubeconform manifest validation, gitleaks secret scanning, Claude Code security review (runs on PRs after the other checks pass)
- [Docker Build](.github/workflows/docker-build.yml) — build and push to GHCR, plus pre-merge gates: contract tests (manifest replay against the pinned chart) and the upstream changelog diff
- [Security Review](.github/workflows/security.yml) — manual dispatch only

[Pre-merge gate details →](docs/ci-gates.md)

## Docs

- [Setup Guide](docs/setup-guide.md) — Image burning, node setup, k0s deployment, Flux bootstrap
- [Architecture](docs/architecture.md) — Full architecture with diagrams and data flow
- [Apps Reference](docs/apps.md) — Detailed reference for all deployed applications
- [Infrastructure Reference](docs/infrastructure.md) — Storage, networking, secrets, Helm repos
