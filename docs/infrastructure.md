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
3. **Longhorn Tailscale** (`longhorn-tailscale.yaml`) — Exposes Longhorn UI via Tailscale

### External Access Pattern

Services with `service.type: LoadBalancer` and `service.loadBalancerClass: tailscale` are automatically exposed on the Tailnet via the Tailscale Operator. This replaces the need for:
- Ingress controllers
- MetalLB IP pools
- Port forwarding

### Used By

- Grafana (monitoring namespace)
- Open WebUI (open-webui namespace)
- Longhorn UI (longhorn-system namespace)

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
| open-webui-secret.sealedsecret.yaml       | open-webui  | Open WebUI secrets                |
| open-webui-hermes-openai.sealedsecret.yaml| open-webui  | API key for Hermes backend        |

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
