# Flux CD GitOps Migration Design

**Date:** 2026-05-23
**Status:** Approved
**Cluster:** k0s homelab (1 controller + 5 workers)

## Current State

- **Cluster:** k0s, 12 namespaces, 1 controller + 5 worker nodes (SOQuartz SBCs)
- **Apps:** hermes-agent (jon-agent), hermes-ana (ana-agent), open-webui
- **Infrastructure:** longhorn (storage), metallb (LoadBalancer), tailscale (network), metrics-server
- **Helm releases:** hermes (jon-agent), hermes-ana (ana-agent), metallb (metallb-system)
- **Current management:** k0sctl for cluster provisioning, manual kubectl/Helm for apps
- **No ingresses** — services exposed via MetalLB IPs + Tailscale
- **Repo:** `github.com/jonregeimbal/homelab`

## Design Decisions

| Decision | Choice |
|----------|--------|
| Repo structure | Single repo (existing homelab repo), layered |
| Secret management | SealedSecrets |
| Flux topology | Layered: cluster → infra → apps |
| App scope | All apps under Flux (including longhorn, metallb, tailscale) |
| Helm chart source | OCI where available, Helm repos otherwise |
| Migration approach | Parallel then switch (verify each app before removing manual install) |
| Git source | Existing GitHub repo via `flux bootstrap github` |
| Monitoring | Grafana + Prometheus |
| Values organization | Base + overlays per environment |
| Migration order | User apps first (hermes, hermes-ana, open-webui), then infra |

## Repo Structure

```
homelab/
├── flux/
│   ├── cluster/
│   │   ├── kustomization.yaml        # Flux CRDs (SealedSecrets CRD, etc.)
│   │   ├── helmrepositories.yaml     # Helm repo definitions (OCI + traditional)
│   │   └── namespaces.yaml           # Namespace definitions
│   ├── infra/
│   │   ├── kustomization.yaml        # References infra HelmReleases
│   │   ├── longhorn.yaml
│   │   ├── metallb.yaml
│   │   └── tailscale.yaml
│   └── apps/
│       ├── kustomization.yaml        # References app HelmReleases
│       ├── hermes-jon.yaml
│       ├── hermes-ana.yaml
│       ├── open-webui.yaml
│       └── monitoring.yaml           # Prometheus + Grafana
├── values/
│   ├── base/
│   │   ├── longhorn-values.yaml
│   │   ├── metallb-values.yaml
│   │   ├── tailscale-values.yaml
│   │   ├── hermes-jon-values.yaml
│   │   ├── hermes-ana-values.yaml
│   │   ├── open-webui-values.yaml
│   │   └── monitoring-values.yaml
│   └── overlays/
│       └── homelab/
│           ├── longhorn-values.yaml
│           ├── metallb-values.yaml
│           ├── tailscale-values.yaml
│           ├── hermes-jon-values.yaml
│           ├── hermes-ana-values.yaml
│           ├── open-webui-values.yaml
│           └── monitoring-values.yaml
├── secrets/
│   └── encrypted/
│       └── *.sealedsecret.yaml
└── k0sctl.yaml                       # Unchanged — cluster provisioning
```

## HelmChart Sources

| App | Source Type | URL |
|-----|------------|-----|
| longhorn | Helm repo | `https://charts.longhorn.io` |
| metallb | OCI | `oci://ghcr.io/metallb/charts/metallb` |
| tailscale | Helm repo | `https://tailscale.github.io/helm-charts` |
| hermes-agent | Git repo | `https://github.com/ultraworkers/hermes-agent-helm-chart` |
| open-webui | Helm repo | `https://perdy.github.io/helm-charts` |
| prometheus | OCI | `oci://ghcr.io/prometheus-community/charts/prometheus` |
| grafana | OCI | `oci://ghcr.io/grafana/helm/charts/grafana` |
| sealed-secrets | Helm repo | `https://bitnami-labs.github.io/sealed-secrets` |

## Secret Management

SealedSecrets workflow:

1. Install SealedSecrets controller via HelmRelease
2. Encrypt secrets locally with `kubeseal` CLI → `*.sealedsecret.yaml`
3. Commit encrypted SealedSecrets to repo (safe to commit)
4. SealedSecrets controller decrypts and creates plain Secrets in-cluster

Secrets to encrypt:
- Hermes tokens (DISCORD_TOKEN, TELEGRAM_TOKEN, etc.)
- Open-webui secrets
- Any other app credentials

## Monitoring Stack

**Prometheus** (`monitoring` namespace):
- Chart: `prometheus-community/prometheus` (OCI)
- Storage: Longhorn PVC (20Gi)
- Access: ClusterIP (via Tailscale)

**Grafana** (`monitoring` namespace):
- Chart: `grafana/grafana` (OCI)
- Storage: Longhorn PVC (5Gi)
- Access: LoadBalancer (MetalLB) + Tailscale
- Auto-configured with Prometheus datasource

Data flow: Kubernetes API → Prometheus (scrape) → Grafana (query + visualize)

## Migration Plan

1. Install SealedSecrets CRD via kubectl, commit to `flux/cluster/`
2. Install Flux via `flux bootstrap github` pointing to homelab repo
3. Verify Flux is syncing (`flux get sources git`, `flux get kustomizations`)
4. Convert hermes (jon-agent) — create HelmRelease, commit, verify, then `helm uninstall`
5. Convert hermes-ana (ana-agent) — same process
6. Convert open-webui — same process
7. Convert metallb — same process
8. Convert longhorn — same process (verify PVCs survive)
9. Convert tailscale — same process
10. Install monitoring stack (Prometheus + Grafana) via HelmRelease
11. Verify everything — all pods running, all HelmReleases synced
12. Remove k0s metallb extension from k0sctl config (now managed by Flux)

### Safety Notes

- Each app verified running under Flux before moving to the next
- PVCs preserved (Longhorn volumes survive Helm uninstall)
- k0sctl untouched for cluster provisioning
- SealedSecrets key preserved during transition
