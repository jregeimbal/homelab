# Setup Guide

## Prerequisites

- SO Quartz devices (or compatible Rockchip ARM64 boards)
- MicroSD cards (32GB+) per node
- Network access for each node
- k0sctl binary installed locally
- Flux CLI (optional, for verification)

## Step 1: Prepare Node Images

Each node runs DietPi (Debian-based lightweight OS) burned to MicroSD.

### Using the burn script

The repo includes `setup/burn-url-to-device.sh` for burning DietPi images to disk:

```bash
sudo ./setup/burn-url-to-device.sh \
  https://dietpi.com/downloads/images/DietPi_SOQuartz-ARMv8-Trixie.img.xz \
  /dev/diskX \
  HOSTNAME \
  PASSWORD \
  n
```

Parameters:
- **IMAGE URL** (optional): DietPi image URL. Defaults to SO Quartz ARMv8 Trixie.
- **DEVICE PATH** (optional): Target disk (e.g., `/dev/disk7`). Find with `diskutil list` (macOS) or `lsblk` (Linux).
- **HOSTNAME** (optional): Node hostname. Defaults to `homelab-soquartz-N`.
- **PASSWORD** (optional): DietPi user password. Defaults to `dietpi`.
- **EJECT** (optional): `y` or `n`. Defaults to `n`.

### Manual image burning

If not using the script, download the DietPi SO Quartz image and flash using `dd`, `balenaEtcher`, or `bmaptool`.

```bash
# Example with dd
xzcat DietPi_SOQuartz-ARMv8-Trixie.img.xz | sudo dd of=/dev/diskX bs=4m status=progress
```

## Step 2: Boot and Configure Nodes

1. Insert MicroSD into each node and power on
2. Log in via serial console or SSH (default user: `dietpi`)
3. Run `dietpi-software` to install any additional software
4. Assign static IPs or configure DHCP reservations
5. Ensure all nodes can reach each other via SSH

Node naming convention:
- `homelab-soquartz-1` — controller
- `homelab-soquartz-2` through `homelab-soquartz-6` — workers

## Step 3: Deploy k0s Cluster

The cluster is deployed using k0sctl, which reads configuration from `k0sctl.yaml`.

```bash
# Deploy the cluster
k0sctl apply

# Get kubeconfig after deployment
k0sctl kubeconfig > kubeconfig

# Verify nodes
kubectl --kubeconfig kubeconfig get nodes
```

### Cluster Configuration (from k0sctl.yaml)

- **Cluster name:** homelab
- **k0s version:** managed by k0sctl
- **CNI:** Kuberouter (autoMTU enabled)
- **API server port:** 6443
- **Storage backend:** etcd (embedded)
- **Node roles:** 1 controller, 5 workers

## Step 4: Bootstrap Flux CD

Flux CD is bootstrapped from this repository and manages all cluster state.

```bash
# Install Flux CLI
brew install flux

# Bootstrap Flux (run from repo root)
flux bootstrap github \
  --owner=<github-username> \
  --repository=homelab \
  --branch=main \
  --path=./flux/cluster \
  --personal
```

Flux watches the `flux/cluster/` path and applies resources in this order:
1. SealedSecrets CRD
2. HelmRepositories (Longhorn, MetalLB, Bitnami, Prometheus, Grafana, OpenWebUI, Tailscale, Hermes-agent)
3. Namespaces (monitoring, flux-system, jon-agent, ana-agent, longhorn-system, tailscale, open-webui)
4. Apps Kustomization (triggers deployment of all apps)
5. Infra Kustomization (Longhorn, MetalLB, Tailscale, SealedSecrets)

Note: The `flux/cluster/kustomization.yaml` lists `apps-kustomization.yaml` before `../../flux/infra/`, so apps are deployed after infra components. The `apps-kustomization.yaml` has a `dependsOn` constraint requiring `flux-system` to be ready first.

## Step 5: Verify Deployment

```bash
# Check Flux sync status
flux get sources git
flux get kustomizations

# Check Helm releases
flux get helmreleases --all-namespaces

# Verify nodes are ready
kubectl --kubeconfig kubeconfig get nodes

# Check namespace status
kubectl --kubeconfig kubeconfig get namespaces
```

## Troubleshooting

- **Nodes not reachable:** Verify SSH connectivity and that `k0sctl.yaml` addresses match actual node hostnames/IPs
- **Flux not syncing:** Check that the GitHub token has repo read access and the `--path` matches your kustomization location
- **Longhorn not mounting:** Ensure worker nodes have available block devices or loopback storage configured
