# Infrastructure Reference

## k0s Cluster

**Cluster name:** homelab  
**Orchestration:** k0s (single-binary Kubernetes)  
**Provisioning:** k0sctl (`k0sctl.yaml`)

### Nodes

| Node                  | Role     | OS      |
|-----------------------|----------|---------|
| homelab-soquartz-1    | controller | DietPi |
| homelab-soquartz-2    | worker   | DietPi  |
| homelab-soquartz-3    | worker   | DietPi  |
| homelab-soquartz-4    | worker   | DietPi  |
| homelab-soquartz-5    | worker   | DietPi  |
| homelab-soquartz-6    | worker   | DietPi  |

### Network Configuration

- **CNI:** Kuberouter
- **Pod CIDR:** 10.244.0.0/16
- **Service CIDR:** 10.96.0.0/12
- **kubeProxy:** enabled (iptables mode)
- **autoMTU:** enabled
- **API server port:** 6443
- **k0s API port:** 9443

### Storage Backend

- **Type:** etcd (embedded, no external etcd cluster)

---

## Longhorn

**Namespace:** longhorn-system  
**HelmRelease:** `longhorn`  
**Chart source:** `longhorn` HelmRepository (charts.longhorn.io)  
**Version:** 11.11.2

### Purpose

Longhorn provides distributed block storage for the cluster. All persistent volumes use the `longhorn` StorageClass.

### Used By

- Prometheus (5Gi)
- Grafana (5Gi)
- Open WebUI (10Gi)
- Hermes agents (5Gi each)
- All other stateful workloads

### Configuration

Default HelmRelease values — no custom overrides beyond storage class designation in app HelmReleases.

---

## MetalLB

**Namespace:** metallb-system  
**HelmRelease:** `metallb`  
**Chart source:** `metallb` HelmRepository (metallb.github.io/metallb)  
**Version:** 0.16.0

### Purpose

MetalLB provides Layer 2 load balancing for Kubernetes LoadBalancer services.

### Current Status

Installed but not actively used for production services. Tailscale Operator has replaced MetalLB as the primary external access mechanism. Kept in the repo as a fallback option.

---

## Tailscale

**Namespace:** tailscale  
**HelmRelease:** `tailscale-operator`  
**Chart source:** `tailscale` HelmRepository (pkgs.tailscale.com/helmcharts)  
**Version:** 1.98.3

### Components

1. **Tailscale Operator** — Manages Tailscale nodes as Kubernetes resources
2. **Tailscale Connector** (`tailscale-connector.yaml`) — Connects the cluster to the Tailnet
3. **Longhorn UI** — not exposed directly. The `longhorn` Tailscale Ingress (in `flux/apps/authentik.yaml`) serves `https://longhorn.<tailnet>.ts.net` through authentik's embedded outpost, which requires an `authentik Admins` login before it forwards to `longhorn-frontend`.

### External Access Pattern

Services with `service.type: LoadBalancer` and `service.loadBalancerClass: tailscale` are automatically exposed on the Tailnet via the Tailscale Operator. This replaces the need for:
- Ingress controllers
- MetalLB IP pools
- Port forwarding

### Used By

- Grafana (monitoring namespace)
- Open WebUI (open-webui namespace)
- Authentik (authentik namespace)
- Trading Assistant (trading-assistant namespace)
- Sofarmap (sofarmap namespace)
- Longhorn UI (longhorn-system namespace)

---

## NodeLocal DNSCache

**Namespace:** kube-system  
**Kind:** DaemonSet (`node-local-dns`), deployed as plain manifests from `flux/infra/node-local-dns.yaml`

### Purpose

A per-node DNS cache that eliminates the conntrack UDP race condition causing intermittent pod DNS timeouts. It uses plain CoreDNS v1.14.2 on the host network instead of the upstream `k8s-dns-node-cache` wrapper (these kernels lack `CONFIG_DUMMY`, which the wrapper's dummy-interface setup needs).

### How It Works

- **Address:** bound to `169.254.20.10` (link-local) on a dedicated empty bridge, `nodelocaldns`. Not on `lo` — k0s picks the first non-127.x IPv4 address in interface order as its API address, and a controller restarted with the address on `lo` advertised 169.254.20.10 and broke worker kube-proxy connections (2026-10-15). The bridge is created after boot, so it sorts after eth0 on every node.
- **Redirect:** two init containers prepare the host; one DNATs pod DNS traffic (UDP/TCP 10.96.0.10:53 → 169.254.20.10:53) in iptables PREROUTING only (not OUTPUT, which would loop the cache's own upstream forwarding). Pods keep `10.96.0.10` in resolv.conf — no kubelet change needed, since k0s forbids setting `clusterDNS` in workerProfiles.
- **Resolvers:** `cluster.local`/reverse-lookup zones forward to CoreDNS (10.96.0.10:53) over TCP (`force_tcp` removes the race on the cache→CoreDNS leg). Everything else forwards to the node's systemd-resolved stub (127.0.0.53, reachable on the host network), which sends tailnet names to Tailscale and everything else to the router — see `scripts/set-node-dns.sh`. Nodes without resolved fall back to 100.100.100.100 (Tailscale MagicDNS).
- **Corefile changes:** the Corefile is mounted with `subPath`, which never sees ConfigMap updates — bump the `homelab/corefile-revision` pod annotation when it changes.

---

## SealedSecrets

**Namespace:** flux-system  
**CRD:** `secrets/encrypted/sealed-secrets-crd.yaml`

### Purpose

SealedSecrets allows encrypted secrets to be safely committed to Git. The SealedSecrets controller in the cluster decrypts them into standard Kubernetes Secrets.

### Workflow

1. Create a plaintext Kubernetes Secret
2. Seal it using `kubeseal` (with the cluster's public key)
3. The output is a SealedSecret resource (encrypted)
4. Commit the SealedSecret to the repository
5. Flux applies it, and the controller decrypts it

### Encrypted Secrets in Repo

| SealedSecret                              | Namespace   | Contents                          |
|-------------------------------------------|-------------|-----------------------------------|
| hermes-jon-secrets.sealedsecret.yaml      | jon-agent   | API key, HF token, OpenRouter, Telegram |
| hermes-ana-secrets.sealedsecret.yaml      | ana-agent   | API server key                    |
| hermes-wander-secrets.sealedsecret.yaml   | wander-agent| API server key, dashboard session token, Firecrawl key |
| open-webui-secret.sealedsecret.yaml       | open-webui  | Open WebUI secrets, Hermes API key |
| open-webui-oidc.sealedsecret.yaml         | open-webui  | Authentik OIDC client secret      |
| grafana-oidc.sealedsecret.yaml            | monitoring  | Authentik OIDC client secret      |
| authentik-secrets.sealedsecret.yaml       | authentik   | Secret key, Postgres password, bootstrap password |
| authentik-oidc-clients.sealedsecret.yaml  | authentik   | OIDC client secrets for all SSO apps |
| trading-assistant-secrets.sealedsecret.yaml | trading-assistant | Postgres/DUI passwords, paper Webull keys, master key |
| trading-assistant-ghcr-pull.sealedsecret.yaml | trading-assistant | GHCR read:packages pull token |
| sofarmap-secrets.sealedsecret.yaml        | sofarmap    | Postgres/OIDC/session keys, Google Maps + OSRM keys |
| sofarmap-ghcr-pull.sealedsecret.yaml      | sofarmap    | GHCR read:packages pull token |

### Tools Required

- `kubeseal` (Bitnami SealedSecrets CLI) — for sealing secrets
- Access to the target cluster's SealedSecrets controller public key

---

## HelmRepositories

All HelmRepositories are defined in `flux/cluster/helmrepositories.yaml`:

| Name               | URL                                           | Type   |
|-------------------|-----------------------------------------------|--------|
| longhorn          | https://charts.longhorn.io                    | Helm   |
| metallb           | https://metallb.github.io/metallb             | Helm   |
| bitnami           | https://charts.bitnami.com/bitnami            | Helm   |
| prometheus-community | https://prometheus-community.github.io/helm-charts | Helm |
| grafana           | https://grafana.github.io/helm-charts         | Helm   |
| openwebui         | https://open-webui.github.io/helm-charts      | Helm   |
| tailscale         | https://pkgs.tailscale.com/helmcharts         | Helm   |
| hermes-agent      | https://github.com/ultraworkers/hermes-agent-helm-chart | Git |
