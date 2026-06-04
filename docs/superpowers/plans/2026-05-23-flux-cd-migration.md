# Flux CD GitOps Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the k0s homelab cluster from manual kubectl/Helm management to Flux CD GitOps with SealedSecrets.

**Architecture:** Install Flux via `flux bootstrap github` pointing to the homelab repo. Each app becomes a HelmRelease CRD managed by Flux. Secrets encrypted with SealedSecrets. Monitoring via Prometheus + Grafana. Migration is parallel — each app is verified under Flux before removing its manual install.

**Tech Stack:** k0s, Flux CD (SourceGit, HelmController, KustomizeController), SealedSecrets, Helm (OCI + repo), Longhorn, MetalLB, Tailscale

---

## Prerequisites

Before starting, ensure:
- `kubectl` is connected to the cluster
- `flux` CLI is installed (`brew install flux` or download from https://fluxcd.io)
- `kubeseal` CLI is installed (`brew install kubeseal` or download from https://github.com/bitnami-labs/sealed-secrets)
- `helm` CLI is installed
- SSH key for GitHub is configured (`git@github.com:jregeimbal/homelab.git`)
- The homelab repo is accessible from the cluster nodes (GitHub reachability)

---

### Task 1: Create repo directory structure

**Files:**
- Create: `flux/cluster/` (directory)
- Create: `flux/infra/` (directory)
- Create: `flux/apps/` (directory)
- Create: `values/base/` (directory)
- Create: `values/overlays/homelab/` (directory)
- Create: `secrets/encrypted/` (directory)

- [ ] **Step 1: Create directory structure**

```bash
cd /Users/jonregeimbal/Dev/jregeimbal/homelab
mkdir -p flux/cluster flux/infra flux/apps
mkdir -p values/base values/overlays/homelab
mkdir -p secrets/encrypted
```

- [ ] **Step 2: Add .gitignore for secrets**

```bash
echo "secrets/plaintext/" >> .gitignore
```

- [ ] **Step 3: Commit**

```bash
git add flux/ values/ secrets/ .gitignore
git commit -m "chore: create flux cd repo structure"
```

---

### Task 2: Install SealedSecrets CRD

**Files:**
- Create: `secrets/encrypted/sealed-secrets-crd.yaml`
- Modify: `flux/cluster/kustomization.yaml`

- [ ] **Step 1: Get the latest SealedSecrets CRD YAML**

```bash
curl -sSL https://github.com/bitnami-labs/sealed-secrets/releases/download/v0.31.0/controller.yaml | grep -A 999 "kind: CustomResourceDefinition" > secrets/encrypted/sealed-secrets-crd.yaml
```

Verify the file contains a `CustomResourceDefinition` for `sealedsecrets.bitnami.com`:

```bash
grep "kind: CustomResourceDefinition" secrets/encrypted/sealed-secrets-crd.yaml
```

Expected output: `kind: CustomResourceDefinition`

- [ ] **Step 2: Create the cluster kustomization**

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - sealed-secrets-crd.yaml
  - helmrepositories.yaml
  - namespaces.yaml
```

Write to `flux/cluster/kustomization.yaml`.

- [ ] **Step 3: Commit**

```bash
git add flux/cluster/kustomization.yaml secrets/encrypted/sealed-secrets-crd.yaml
git commit -m "infra: add SealedSecrets CRD and cluster kustomization"
```

---

### Task 3: Define HelmRepositories and Namespaces

**Files:**
- Create: `flux/cluster/helmrepositories.yaml`
- Create: `flux/cluster/namespaces.yaml`

- [ ] **Step 1: Create HelmRepositories**

Write to `flux/cluster/helmrepositories.yaml`:

```yaml
---
apiVersion: source.toolkit.fluxcd.io/v1beta2
kind: HelmRepository
metadata:
  name: longhorn
  namespace: flux-system
spec:
  type: oci
  url: oci://ghcr.io/longhorn/charts/longhorn
  interval: 5m
---
apiVersion: source.toolkit.fluxcd.io/v1beta2
kind: HelmRepository
metadata:
  name: metallb
  namespace: flux-system
spec:
  type: oci
  url: oci://ghcr.io/metallb/charts/metallb
  interval: 5m
---
apiVersion: source.toolkit.fluxcd.io/v1beta2
kind: HelmRepository
metadata:
  name: bitnami
  namespace: flux-system
spec:
  url: https://charts.bitnami.com/bitnami
  interval: 5m
---
apiVersion: source.toolkit.fluxcd.io/v1beta2
kind: HelmRepository
metadata:
  name: prometheus-community
  namespace: flux-system
spec:
  type: oci
  url: oci://ghcr.io/prometheus-community/charts/prometheus
  interval: 5m
---
apiVersion: source.toolkit.fluxcd.io/v1beta2
kind: HelmRepository
metadata:
  name: grafana
  namespace: flux-system
spec:
  type: oci
  url: oci://ghcr.io/grafana/helm/charts/grafana
  interval: 5m
---
apiVersion: source.toolkit.fluxcd.io/v1beta2
kind: HelmRepository
metadata:
  name: openwebui
  namespace: flux-system
spec:
  url: https://open-webui.github.io/helm-charts
  interval: 5m
---
apiVersion: source.toolkit.fluxcd.io/v1beta2
kind: HelmRepository
metadata:
  name: hermes-agent
  namespace: flux-system
spec:
  type: git
  url: https://github.com/ultraworkers/hermes-agent-helm-chart
  interval: 5m
```

Note: Tailscale Helm repo is currently unreachable. The Tailscale operator will be installed via a HelmRepository pointing to the Tailscale GitHub k8s repo during implementation.

- [ ] **Step 2: Create Namespaces**

Write to `flux/cluster/namespaces.yaml`:

```yaml
---
apiVersion: v1
kind: Namespace
metadata:
  name: monitoring
---
apiVersion: v1
kind: Namespace
metadata:
  name: flux-system
```

- [ ] **Step 3: Commit**

```bash
git add flux/cluster/helmrepositories.yaml flux/cluster/namespaces.yaml
git commit -m "infra: define HelmRepositories and namespaces"
```

---

### Task 4: Bootstrap Flux

**Files:**
- No new files — Flux creates its own resources in the `flux-system` namespace

- [ ] **Step 1: Bootstrap Flux pointing to the homelab repo**

```bash
flux bootstrap github \
  --owner=jregeimbal \
  --repository=homelab \
  --branch=k0s-k0sctl \
  --path=flux \
  --personal
```

This will:
- Create a deploy key for the repo
- Install Flux controllers in the `flux-system` namespace
- Create a `Kustomization` that watches the `flux/` path

- [ ] **Step 2: Verify Flux is running**

```bash
kubectl get pods -n flux-system
```

Expected: All pods in `flux-system` namespace should be `Running` and `READY`.

- [ ] **Step 3: Verify Flux is syncing the cluster kustomization**

```bash
flux get kustomizations -A
```

Expected: The `flux-system` kustomization should show `Ready=True`.

- [ ] **Step 4: Verify HelmRepositories are synced**

```bash
flux get sources helm -A
```

Expected: All HelmRepositories defined in `helmrepositories.yaml` should show `Ready=True`.

- [ ] **Step 5: Commit the Flux-generated files**

After bootstrap, Flux creates files in the repo. Commit them:

```bash
git add .
git commit -m "infra: flux bootstrap generated files"
```

---

### Task 5: Extract current Helm values for base configs

**Files:**
- Create: `values/base/hermes-jon-values.yaml`
- Create: `values/base/hermes-ana-values.yaml`
- Create: `values/base/metallb-values.yaml`
- Create: `values/base/longhorn-values.yaml`
- Create: `values/base/open-webui-values.yaml`
- Create: `values/base/monitoring-values.yaml`

- [ ] **Step 1: Extract hermes (jon-agent) values**

```bash
helm get values hermes -n jon-agent -o yaml > values/base/hermes-jon-values.yaml
```

The file will contain the current values. The `secrets` section contains API keys that will be moved to SealedSecrets.

- [ ] **Step 2: Extract hermes-ana values**

```bash
helm get values hermes-ana -n ana-agent -o yaml > values/base/hermes-ana-values.yaml
```

- [ ] **Step 3: Extract metallb values**

The current metallb has no custom values (uses defaults). Create a minimal values file:

```yaml
---
# values/base/metallb-values.yaml
# MetalLB uses defaults; override as needed
```

- [ ] **Step 4: Extract longhorn values**

The current longhorn uses defaults. Create a minimal values file:

```yaml
---
# values/base/longhorn-values.yaml
# Longhorn uses defaults; override as needed
```

- [ ] **Step 5: Create open-webui values**

Open-webui is not Helm-managed. Create values based on the current deployment:

```yaml
---
# values/base/open-webui-values.yaml
replicaCount: 1
image:
  repository: ghcr.io/open-webui/open-webui
  tag: main
service:
  type: LoadBalancer
  ports:
    - port: 80
      targetPort: 8080
persistence:
  enabled: true
  size: 10Gi
  storageClass: longhorn
env:
  OLLAMA_BASE_URL: "http://hermes-agent.jon-agent.svc.cluster.local:5000"
  WEBUI_SECRET_KEY: "changeme-in-production"
```

- [ ] **Step 6: Create monitoring values**

```yaml
---
# values/base/monitoring-values.yaml
# Prometheus values
prometheus:
  prometheus:
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: longhorn
          resources:
            requests:
              storage: 20Gi
    service:
      type: ClusterIP

# Grafana values
grafana:
  persistence:
    enabled: true
    storageClassName: longhorn
    size: 5Gi
  service:
    type: LoadBalancer
  adminPassword: "changeme"
  sidecar:
    datasources:
      enabled: true
      datasources:
        prometheus:
          url: "http://prometheus-server.monitoring.svc.cluster.local"
```

- [ ] **Step 7: Commit**

```bash
git add values/base/
git commit -m "infra: extract base Helm values for all apps"
```

---

### Task 6: Create HelmRelease for hermes (jon-agent)

**Files:**
- Create: `flux/apps/hermes-jon.yaml`

- [ ] **Step 1: Create the HelmRelease**

Write to `flux/apps/hermes-jon.yaml`:

```yaml
---
apiVersion: source.toolkit.fluxcd.io/v1beta2
kind: HelmChart
metadata:
  name: hermes-agent
  namespace: flux-system
spec:
  chart: hermes-agent
  version: "0.1.0"
  sourceRef:
    kind: HelmRepository
    name: hermes-agent
    namespace: flux-system
  interval: 5m
  path: ./charts
---
apiVersion: helm.toolkit.fluxcd.io/v2beta2
kind: HelmRelease
metadata:
  name: hermes
  namespace: jon-agent
spec:
  interval: 5m
  chartRef:
    kind: HelmChart
    name: hermes-agent
    namespace: flux-system
  releaseName: hermes
  targetNamespace: jon-agent
  valuesFile: ../../values/base/hermes-jon-values.yaml
  install:
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    remediation:
      retries: 3
```

- [ ] **Step 2: Commit**

```bash
git add flux/apps/hermes-jon.yaml
git commit -m "apps: add Flux HelmRelease for hermes (jon-agent)"
```

---

### Task 7: Convert hermes (jon-agent) to Flux

**Files:**
- No new files — verify existing HelmRelease is working

- [ ] **Step 1: Verify Flux is syncing the HelmRelease**

```bash
flux get helmreleases -n jon-agent
```

Expected: `hermes` should show `Ready=True`.

- [ ] **Step 2: Verify pods are running**

```bash
kubectl get pods -n jon-agent
```

Expected: `hermes-hermes-agent-*` pods should be `Running`.

- [ ] **Step 3: Verify the deployment is managed by Flux**

```bash
kubectl get deployment hermes-hermes-agent -n jon-agent -o yaml | grep "meta.helm.sh/release-name"
```

Expected: Should show `hermes` as the release name.

- [ ] **Step 4: Uninstall the manual Helm release**

```bash
helm uninstall hermes -n jon-agent
```

- [ ] **Step 5: Verify Flux recreates the release**

```bash
flux get helmreleases -n jon-agent
kubectl get pods -n jon-agent
```

Expected: Flux should detect the missing release and recreate it. Pods should be `Running`.

- [ ] **Step 6: Commit**

```bash
git commit -m "apps: migrated hermes (jon-agent) to Flux" --allow-empty
```

---

### Task 8: Create HelmRelease for hermes-ana (ana-agent)

**Files:**
- Create: `flux/apps/hermes-ana.yaml`

- [ ] **Step 1: Create the HelmRelease**

Write to `flux/apps/hermes-ana.yaml`:

```yaml
---
apiVersion: helm.toolkit.fluxcd.io/v2beta2
kind: HelmRelease
metadata:
  name: hermes-ana
  namespace: ana-agent
spec:
  interval: 5m
  chartRef:
    kind: HelmChart
    name: hermes-agent
    namespace: flux-system
  releaseName: hermes-ana
  targetNamespace: ana-agent
  valuesFile: ../../values/base/hermes-ana-values.yaml
  install:
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    remediation:
      retries: 3
```

- [ ] **Step 2: Commit**

```bash
git add flux/apps/hermes-ana.yaml
git commit -m "apps: add Flux HelmRelease for hermes-ana (ana-agent)"
```

---

### Task 9: Convert hermes-ana (ana-agent) to Flux

**Files:**
- No new files

- [ ] **Step 1: Verify Flux is syncing**

```bash
flux get helmreleases -n ana-agent
kubectl get pods -n ana-agent
```

Expected: `hermes-ana-*` pods should be `Running`.

- [ ] **Step 2: Uninstall manual Helm release**

```bash
helm uninstall hermes-ana -n ana-agent
```

- [ ] **Step 3: Verify Flux recreates**

```bash
flux get helmreleases -n ana-agent
kubectl get pods -n ana-agent
```

Expected: Flux recreates the release, pods are `Running`.

- [ ] **Step 4: Commit**

```bash
git commit -m "apps: migrated hermes-ana (ana-agent) to Flux" --allow-empty
```

---

### Task 10: Create HelmRelease for open-webui

**Files:**
- Create: `flux/apps/open-webui.yaml`

- [ ] **Step 1: Create the HelmRelease**

Write to `flux/apps/open-webui.yaml`:

```yaml
---
apiVersion: helm.toolkit.fluxcd.io/v2beta2
kind: HelmRelease
metadata:
  name: open-webui
  namespace: open-webui
spec:
  interval: 5m
  chart:
    spec:
      chart: open-webui
      version: "14.6.0"
      sourceRef:
        kind: HelmRepository
        name: openwebui
        namespace: flux-system
      interval: 5m
  releaseName: open-webui
  targetNamespace: open-webui
  valuesFile: ../../values/base/open-webui-values.yaml
  install:
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    remediation:
      retries: 3
```

- [ ] **Step 2: Commit**

```bash
git add flux/apps/open-webui.yaml
git commit -m "apps: add Flux HelmRelease for open-webui"
```

---

### Task 11: Convert open-webui to Flux

**Files:**
- No new files

- [ ] **Step 1: Verify Flux is syncing**

```bash
flux get helmreleases -n open-webui
kubectl get pods -n open-webui
```

Expected: `open-webui-*` pod should be `Running`.

- [ ] **Step 2: Delete the manual deployment**

```bash
kubectl delete deployment open-webui -n open-webui
```

- [ ] **Step 3: Verify Flux recreates**

```bash
flux get helmreleases -n open-webui
kubectl get pods -n open-webui
```

Expected: Flux recreates the deployment, pod is `Running`.

- [ ] **Step 4: Commit**

```bash
git commit -m "apps: migrated open-webui to Flux" --allow-empty
```

---

### Task 12: Create HelmRelease for metallb

**Files:**
- Create: `flux/infra/metallb.yaml`

- [ ] **Step 1: Create the HelmRelease**

Write to `flux/infra/metallb.yaml`:

```yaml
---
apiVersion: helm.toolkit.fluxcd.io/v2beta2
kind: HelmRelease
metadata:
  name: metallb
  namespace: metallb-system
spec:
  interval: 5m
  chart:
    spec:
      chart: metallb
      version: "0.16.0"
      sourceRef:
        kind: HelmRepository
        name: metallb
        namespace: flux-system
      interval: 5m
  releaseName: metallb
  targetNamespace: metallb-system
  valuesFile: ../../values/base/metallb-values.yaml
  install:
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    remediation:
      retries: 3
```

- [ ] **Step 2: Commit**

```bash
git add flux/infra/metallb.yaml
git commit -m "infra: add Flux HelmRelease for metallb"
```

---

### Task 13: Convert metallb to Flux

**Files:**
- No new files

- [ ] **Step 1: Verify Flux is syncing**

```bash
flux get helmreleases -n metallb-system
kubectl get pods -n metallb-system
```

Expected: `metallb-controller-*` and `metallb-speaker-*` pods should be `Running`.

- [ ] **Step 2: Uninstall manual Helm release**

```bash
helm uninstall metallb -n metallb-system
```

- [ ] **Step 3: Verify Flux recreates**

```bash
flux get helmreleases -n metallb-system
kubectl get pods -n metallb-system
```

Expected: Flux recreates the release, pods are `Running`.

- [ ] **Step 4: Commit**

```bash
git commit -m "infra: migrated metallb to Flux" --allow-empty
```

---

### Task 14: Create HelmRelease for longhorn

**Files:**
- Create: `flux/infra/longhorn.yaml`

- [ ] **Step 1: Create the HelmRelease**

Write to `flux/infra/longhorn.yaml`:

```yaml
---
apiVersion: helm.toolkit.fluxcd.io/v2beta2
kind: HelmRelease
metadata:
  name: longhorn
  namespace: longhorn-system
spec:
  interval: 5m
  chart:
    spec:
      chart: longhorn
      version: "1.11.2"
      sourceRef:
        kind: HelmRepository
        name: longhorn
        namespace: flux-system
      interval: 5m
  releaseName: longhorn
  targetNamespace: longhorn-system
  valuesFile: ../../values/base/longhorn-values.yaml
  install:
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    remediation:
      retries: 3
```

- [ ] **Step 2: Commit**

```bash
git add flux/infra/longhorn.yaml
git commit -m "infra: add Flux HelmRelease for longhorn"
```

---

### Task 15: Convert longhorn to Flux

**Files:**
- No new files

- [ ] **Step 1: Verify Flux is syncing**

```bash
flux get helmreleases -n longhorn-system
kubectl get pods -n longhorn-system | grep -v "csi-\|csi-attacher\|csi-provisioner\|csi-resizer\|csi-snapshotter\|engine-image\|instance-manager\|longhorn-manager\|longhorn-csi"
```

Expected: `longhorn-ui-*` and `longhorn-driver-deployer-*` pods should be `Running`.

- [ ] **Step 2: Uninstall manual Helm release**

```bash
helm uninstall longhorn -n longhorn-system
```

- [ ] **Step 3: Verify Flux recreates**

```bash
flux get helmreleases -n longhorn-system
kubectl get pods -n longhorn-system | grep -v "csi-\|csi-attacher\|csi-provisioner\|csi-resizer\|csi-snapshotter\|engine-image\|instance-manager\|longhorn-manager\|longhorn-csi"
```

Expected: Flux recreates the release, pods are `Running`.

- [ ] **Step 4: Verify PVCs are preserved**

```bash
kubectl get pvc -A
```

Expected: All PVCs should still be `Bound`.

- [ ] **Step 5: Commit**

```bash
git commit -m "infra: migrated longhorn to Flux" --allow-empty
```

---

### Task 16: Install Tailscale operator via Flux

**Files:**
- Create: `flux/infra/tailscale.yaml`

Note: The Tailscale Helm chart repo is currently unreachable from this machine. The Tailscale operator will be installed via a HelmChart that references the Tailscale GitHub repo directly, or via a Kustomization that applies the operator manifests.

- [ ] **Step 1: Create the Tailscale HelmRelease**

Write to `flux/infra/tailscale.yaml`. Since the Helm repo is unreachable, we'll use a HelmChart that references the Tailscale k8s operator manifests directly:

```yaml
---
apiVersion: source.toolkit.fluxcd.io/v1beta2
kind: HelmChart
metadata:
  name: tailscale-operator
  namespace: flux-system
spec:
  chart: tailscale-operator
  version: "*"
  sourceRef:
    kind: GitRepository
    name: tailscale-k8s
    namespace: flux-system
  interval: 5m
  path: ./kubernetes
---
apiVersion: source.toolkit.fluxcd.io/v1beta2
kind: GitRepository
metadata:
  name: tailscale-k8s
  namespace: flux-system
spec:
  url: https://github.com/tailscale/tailscale
  ref:
    branch: main
  interval: 10m
---
apiVersion: helm.toolkit.fluxcd.io/v2beta2
kind: HelmRelease
metadata:
  name: tailscale-operator
  namespace: tailscale
spec:
  interval: 5m
  chartRef:
    kind: HelmChart
    name: tailscale-operator
    namespace: flux-system
  releaseName: tailscale-operator
  targetNamespace: tailscale
  install:
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    remediation:
      retries: 3
```

- [ ] **Step 2: Commit**

```bash
git add flux/infra/tailscale.yaml
git commit -m "infra: add Flux HelmRelease for tailscale operator"
```

---

### Task 17: Convert tailscale to Flux

**Files:**
- No new files

- [ ] **Step 1: Verify Flux is syncing**

```bash
flux get helmreleases -n tailscale
kubectl get pods -n tailscale | grep operator
```

Expected: `operator-*` pod should be `Running`.

- [ ] **Step 2: Delete the manual deployment**

```bash
kubectl delete deployment operator -n tailscale
```

- [ ] **Step 3: Verify Flux recreates**

```bash
flux get helmreleases -n tailscale
kubectl get pods -n tailscale | grep operator
```

Expected: Flux recreates the operator, pod is `Running`.

- [ ] **Step 4: Commit**

```bash
git commit -m "infra: migrated tailscale operator to Flux" --allow-empty
```

---

### Task 18: Create monitoring stack HelmRelease

**Files:**
- Create: `flux/apps/monitoring.yaml`

- [ ] **Step 1: Create the monitoring HelmRelease**

Write to `flux/apps/monitoring.yaml`:

```yaml
---
apiVersion: helm.toolkit.fluxcd.io/v2beta2
kind: HelmRelease
metadata:
  name: prometheus
  namespace: monitoring
spec:
  interval: 5m
  chart:
    spec:
      chart: prometheus
      version: "29.8.0"
      sourceRef:
        kind: HelmRepository
        name: prometheus-community
        namespace: flux-system
      interval: 5m
  releaseName: prometheus
  targetNamespace: monitoring
  valuesFile: ../../values/base/monitoring-values.yaml
  install:
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    remediation:
      retries: 3
---
apiVersion: helm.toolkit.fluxcd.io/v2beta2
kind: HelmRelease
metadata:
  name: grafana
  namespace: monitoring
spec:
  interval: 5m
  chart:
    spec:
      chart: grafana
      version: "10.5.15"
      sourceRef:
        kind: HelmRepository
        name: grafana
        namespace: flux-system
      interval: 5m
  releaseName: grafana
  targetNamespace: monitoring
  valuesFile: ../../values/base/monitoring-values.yaml
  dependsOn:
    - name: prometheus
  install:
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    remediation:
      retries: 3
```

- [ ] **Step 2: Commit**

```bash
git add flux/apps/monitoring.yaml
git commit -m "apps: add Flux HelmRelease for monitoring stack (prometheus + grafana)"
```

---

### Task 19: Verify monitoring stack

**Files:**
- No new files

- [ ] **Step 1: Verify pods are running**

```bash
kubectl get pods -n monitoring
```

Expected: `prometheus-server-*` and `grafana-*` pods should be `Running`.

- [ ] **Step 2: Verify services**

```bash
kubectl get svc -n monitoring
```

Expected: `prometheus-server` (ClusterIP) and `grafana` (LoadBalancer) services.

- [ ] **Step 3: Commit**

```bash
git commit -m "apps: monitoring stack verified" --allow-empty
```

---

### Task 20: Create Flux apps kustomization

**Files:**
- Create: `flux/apps/kustomization.yaml`

- [ ] **Step 1: Create the apps kustomization**

Write to `flux/apps/kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../cluster/
  - hermes-jon.yaml
  - hermes-ana.yaml
  - open-webui.yaml
  - monitoring.yaml
  - ../infra/
```

- [ ] **Step 2: Commit**

```bash
git add flux/apps/kustomization.yaml
git commit -m "infra: add Flux apps kustomization"
```

---

### Task 21: Final verification

**Files:**
- No new files

- [ ] **Step 1: Verify all HelmReleases are synced**

```bash
flux get helmreleases --all-namespaces
```

Expected: All HelmReleases should show `Ready=True`.

- [ ] **Step 2: Verify all pods are running**

```bash
kubectl get pods --all-namespaces
```

Expected: All application pods should be `Running`.

- [ ] **Step 3: Verify Flux is healthy**

```bash
flux check
```

Expected: All checks pass.

- [ ] **Step 4: Commit**

```bash
git commit -m "verify: final verification complete" --allow-empty
```

---

### Task 22: Clean up k0s extensions

**Files:**
- Modify: `k0sctl.yaml`

- [ ] **Step 1: Remove the metallb Helm extension from k0sctl config**

The metallb Helm chart is now managed by Flux. Remove it from the k0sctl config to avoid conflicts:

```yaml
# In k0sctl.yaml, remove these lines from spec.k0s.config.spec.extensions:
#   helm:
#     repositories:
#       - name: metallb
#         url: https://metallb.github.io/metallb
#     charts:
#       - name: metallb
#         chartname: metallb/metallb
#         namespace: metallb-system
```

- [ ] **Step 2: Commit**

```bash
git add k0sctl.yaml
git commit -m "infra: remove metallb from k0s extensions (now managed by Flux)"
```

---

## Summary of Files Created/Modified

| File | Action | Purpose |
|------|--------|---------|
| `flux/cluster/kustomization.yaml` | Create | Flux cluster kustomization |
| `flux/cluster/helmrepositories.yaml` | Create | Helm repo definitions |
| `flux/cluster/namespaces.yaml` | Create | Namespace definitions |
| `secrets/encrypted/sealed-secrets-crd.yaml` | Create | SealedSecrets CRD |
| `values/base/hermes-jon-values.yaml` | Create | Hermes (jon-agent) values |
| `values/base/hermes-ana-values.yaml` | Create | Hermes (ana-agent) values |
| `values/base/metallb-values.yaml` | Create | MetalLB values |
| `values/base/longhorn-values.yaml` | Create | Longhorn values |
| `values/base/open-webui-values.yaml` | Create | Open-webUI values |
| `values/base/monitoring-values.yaml` | Create | Prometheus + Grafana values |
| `flux/apps/hermes-jon.yaml` | Create | Hermes (jon-agent) HelmRelease |
| `flux/apps/hermes-ana.yaml` | Create | Hermes (ana-agent) HelmRelease |
| `flux/apps/open-webui.yaml` | Create | Open-webUI HelmRelease |
| `flux/apps/monitoring.yaml` | Create | Prometheus + Grafana HelmRelease |
| `flux/apps/kustomization.yaml` | Create | Flux apps kustomization |
| `flux/infra/metallb.yaml` | Create | MetalLB HelmRelease |
| `flux/infra/longhorn.yaml` | Create | Longhorn HelmRelease |
| `flux/infra/tailscale.yaml` | Create | Tailscale operator HelmRelease |
| `k0sctl.yaml` | Modify | Remove metallb Helm extension |
