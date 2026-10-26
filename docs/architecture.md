# Architecture

## Overview

This homelab runs a 6-node k0s Kubernetes cluster on SO Quartz ARM64 devices running DietPi. The cluster is managed via GitOps with Flux CD, which continuously reconciles cluster state from this repository.

## Cluster Topology

```
┌─────────────────────────────────────────────────────┐
│              Homelab Cluster                         │
│                                                      │
│  ┌──────────────────────┐                            │
│  │ Controller            │                            │
│  │ homelab-soquartz-1    │                            │
│  │ (k0s controller + etcd)│                           │
│  └──────────┬───────────┘                            │
│             │                                        │
│  ┌──────────┴───────────┐                           │
│  │ Workers (x5)          │                           │
│  │ homelab-soquartz-2..6 │                           │
│  └──────────────────────┘                           │
│                                                      │
│  CNI: Kuberouter (pod CIDR: 10.244.0.0/16)          │
│  Service CIDR: 10.96.0.0/12                         │
└─────────────────────────────────────────────────────┘
```

## Networking

```
External Services ──┐
                    │
                    ▼
┌─────────────────────────────────────────┐
│  Tailscale Network                       │
│  ┌─────────────┐    ┌──────────────┐   │
│  │ Tailscale    │    │ LoadBalancer │   │
│  │ Operator     │    │ (Tailscale   │   │
│  │ (tailscale/  │    │  class:      │   │
│  │  tailscale)  │    │  Hermes)     │   │
│  └──────────────┘    │ + Ingress    │   │
│                      │ (Grafana,    │   │
│                      │ Open WebUI,  │   │
│                      │ authentik…)  │   │
│                      └──────────────┘   │
│  MetalLB (metallb-system) — unused in   │
│  production (Tailscale replaces it)      │
└─────────────────────────────────────────┘
                    │
                    ▼
            Internal Services
            (ClusterIP, headless)
```

### Networking Components

- **Tailscale Operator:** Provides cluster-external access via Tailscale MagicDNS. All LoadBalancer-type services use the `tailscale` loadBalancerClass, which Tailscale Operator intercepts and exposes via the Tailnet.
- **MetalLB:** Installed but not actively used for LoadBalancer services. Kept as fallback.
- **Kuberouter:** Native Kubernetes CNI providing pod networking with autoMTU.
- **NodeLocal DNSCache:** A DaemonSet (`kube-system`, `flux/infra/node-local-dns.yaml`) runs CoreDNS on every node, bound to 169.254.20.10 on a dedicated `nodelocaldns` bridge. Pod DNS traffic to the cluster DNS IP (10.96.0.10:53) is transparently DNAT'd to the local cache via iptables PREROUTING rules (no kubelet `clusterDNS` change needed — k0s computes it from the service CIDR). This eliminates the conntrack UDP race that caused intermittent pod DNS timeouts. `cluster.local` queries forward to CoreDNS over TCP (`force_tcp`); external queries go to the node's systemd-resolved stub (127.0.0.53), which sends tailnet names to Tailscale MagicDNS and everything else to the router (fallback when resolved is absent: 100.100.100.100 directly). Node DNS is configured with `scripts/set-node-dns.sh`.

## Storage

```
┌─────────────────────────────────────────┐
│  Longhorn (longhorn-system)              │
│                                          │
│  Distributed block storage               │
│  - Replicas spread across worker nodes   │
│  - Replaces local/emptyDir for           │
│    persistent workloads                  │
│                                          │
│  StorageClass: longhorn (default)        │
└─────────────────────────────────────────┘
```

Longhorn provides persistent block storage replicated across worker nodes. All stateful applications (Prometheus, Grafana, Open WebUI, Hermes agents) use the `longhorn` StorageClass.

## GitOps Flow

```
┌──────────────┐     watch      ┌─────────────┐
│              │  ────────────►  │             │
│  Git         │                 │  Flux CD    │
│  Repository  │                 │  (flux-     │
│  (this repo) │                 │   system)   │
│              │                 │  Applies    │
│  flux/       │                 │  HelmReleases│
│  ├── cluster/ │                 │  to cluster │
│  ├── apps/    │                 │             │
│  └── infra/   │                 │             │
└──────────────┘                 └──────┬──────┘
                                        │
                                        ▼
                                ┌─────────────┐
                                │  k0s Cluster │
                                │  (6 nodes)   │
                                └─────────────┘
```

Flux CD operates in a continuous reconciliation loop:
1. Flux watches the Git repository for changes
2. On change (or every 5 minutes), it fetches the latest state
3. It applies `flux/cluster/kustomization.yaml` which references:
   - SealedSecrets CRD
   - HelmRepository definitions
   - Namespace definitions
   - Apps Kustomization (`flux/apps/`)
   - Infra Kustomization (`flux/infra/`)
4. Flux creates HelmRelease resources that install and manage each application
5. Any drift from the Git state is automatically corrected

## Secret Management

```
┌─────────────────────────────────────────┐
│  SealedSecrets                           │
│                                          │
│  Plaintext secrets ──► kubeseal ──►     │
│    (never committed)                     │
│                                  Encrypted│
│                                  SealedSecret│
│                                  (committed) │
│                                          │
│  Flux applies SealedSecret ──►           │
│  SealedSecrets controller                │
│  decrypts using cluster key              │
│  ──► Kubernetes Secret                   │
└─────────────────────────────────────────┘
```

Secrets are managed via SealedSecrets:
- Plaintext secrets are never committed to the repository
- `secrets/encrypted/sealed-secrets-crd.yaml` contains the SealedSecrets CRD
- Application-specific secrets are sealed and stored as `.sealedsecret.yaml` files in `flux/apps/`
- The SealedSecrets controller in the cluster decrypts them into Kubernetes Secrets

## Application Architecture

See [docs/apps.md](./apps.md) for detailed application reference.

### High-Level App Topology

```
┌──────────────────────────────────────────────────────┐
│  jon-agent/                                          │
│  ┌─────────────────────────────────────────────┐    │
│  │  hermes (HelmRelease from hermes-agent git) │    │
│  │  ┌──────────┐  ┌────────────────────────┐  │    │
│  │  │ hermes   │  │ browserless-chromium    │  │    │
│  │  │ agent    │  │ (CDP browser automation)│  │    │
│  │  └──────────┘  └────────────────────────┘  │    │
│  │  Python deps: sealed venv (discord.py,      │    │
│  │  telegram) + lazy-packages on the PVC       │    │
│  │  (faster-whisper, firecrawl; venv wins)     │    │
│  └─────────────────────────────────────────────┘    │
│       │    │    │    │                              │
│       │    │    │    └──► WhatsApp                   │
│       │    │    └───────► Telegram                   │
│       │    └────────────► Discord                    │
│       └─────────────────► Local model (Open WebUI)   │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│  open-webui/                                         │
│  ┌─────────────────────────────────────────────┐    │
│  │  open-webui (HelmRelease from bitnami)      │    │
│  │  Configured with OpenAI-compatible API       │    │
│  │  endpoint → http://hermes-hermes-agent:8642  │    │
│  └─────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│  monitoring/                                         │
│  ┌──────────────┐    ┌──────────────┐               │
│  │ prometheus   │    │ grafana      │               │
│  │ (HelmRelease)│    │ (HelmRelease)│               │
│  │              │───►│ datasources: │               │
│  │ Longhorn 5Gi │    │ prometheus   │               │
│  └──────────────┘    │              │               │
│                      │ Longhorn 5Gi │               │
│                      │ LoadBalancer │               │
│                      │ (tailscale)  │               │
│                      └──────────────┘               │
└──────────────────────────────────────────────────────┘
```

## Flux CD Structure

```
flux/
├── kustomization.yaml          # Entry point → references flux/cluster/
├── cluster/
│   ├── kustomization.yaml      # Cluster-level resources
│   ├── namespaces.yaml         # All namespaces
│   ├── helmrepositories.yaml   # All Helm/Git repositories
│   └── apps-kustomization.yaml # Triggers apps deployment
├── infra/
│   ├── kustomization.yaml      # Infra entry point
│   ├── sealed-secrets.yaml     # SealedSecrets controller
│   ├── longhorn.yaml           # Longhorn storage
│   ├── metallb.yaml            # MetalLB (fallback)
│   ├── tailscale.yaml          # Tailscale operator
│   ├── tailscale-connector.yaml# Tailscale cluster egress
│   └── node-local-dns.yaml     # NodeLocal DNSCache (per-node DNS)
└── apps/
    ├── kustomization.yaml      # Apps entry point
    ├── hermes-jon.yaml         # Hermes agent (jon)
    ├── hermes-ana.yaml         # Hermes agent (ana)
    ├── hermes-wander.yaml      # Hermes agent (wander)
    ├── hermes-jon-tailscale.yaml
    ├── hermes-wander-tailscale.yaml
    ├── hermes-jon-secrets.sealedsecret.yaml
    ├── hermes-ana-secrets.sealedsecret.yaml
    ├── hermes-wander-secrets.sealedsecret.yaml
    ├── monitoring.yaml         # Prometheus + Grafana
    ├── grafana-oidc.sealedsecret.yaml
    ├── open-webui.yaml         # Open WebUI
    ├── open-webui-secret.sealedsecret.yaml
    ├── open-webui-oidc.sealedsecret.yaml
    ├── authentik.yaml          # Identity provider (+ SSO blueprint)
    ├── authentik-secrets.sealedsecret.yaml
    ├── authentik-oidc-clients.sealedsecret.yaml
    ├── trading-assistant.yaml  # Strategy research UI + trading agent
    ├── trading-assistant-secrets.sealedsecret.yaml
    ├── trading-assistant-ghcr-pull.sealedsecret.yaml
    ├── sofarmap.yaml           # Travel maps (PostGIS)
    ├── sofarmap-secrets.sealedsecret.yaml
    └── sofarmap-ghcr-pull.sealedsecret.yaml
```
