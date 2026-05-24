# Longhorn Tailscale Exposure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the Longhorn UI through Tailscale using the same dedicated `Service/longhorn-tailscale` pattern from the pre-Flux backup.

**Architecture:** Add one GitOps-managed Kubernetes `Service` manifest in the infra layer and include it in `flux/infra/kustomization.yaml`. The new service selects Longhorn UI pods directly and uses `loadBalancerClass: tailscale`, leaving the Helm-managed `longhorn-frontend` service unchanged.

**Tech Stack:** Flux, Kustomize, Kubernetes Service `LoadBalancer`, Tailscale Kubernetes operator, Longhorn Helm chart.

---

## File Structure

- Create `flux/infra/longhorn-tailscale.yaml`: declares the dedicated Tailscale LoadBalancer service for Longhorn UI.
- Modify `flux/infra/kustomization.yaml`: adds `longhorn-tailscale.yaml` to the infra resource list.
- Keep `flux/infra/longhorn.yaml` unchanged: Longhorn HelmRelease remains chart-managed.
- Keep `longhorn-frontend` unchanged: Helm continues to own the internal ClusterIP service.

## Task 1: Add The Longhorn Tailscale Service Manifest

**Files:**
- Create: `flux/infra/longhorn-tailscale.yaml`
- Modify: `flux/infra/kustomization.yaml`

- [ ] **Step 1: Verify the manifest is currently absent**

Run:

```bash
flux build kustomization flux-system --path ./flux | rg -U "kind: Service\nmetadata:\n(?:  labels:\n(?:    .*\n)+)?  name: longhorn-tailscale"
```

Expected: command exits non-zero with no matches.

- [ ] **Step 2: Create `flux/infra/longhorn-tailscale.yaml`**

Write exactly:

```yaml
---
apiVersion: v1
kind: Service
metadata:
  name: longhorn-tailscale
  namespace: longhorn-system
spec:
  type: LoadBalancer
  loadBalancerClass: tailscale
  selector:
    app: longhorn-ui
  ports:
    - port: 80
      targetPort: 8000
```

- [ ] **Step 3: Add the manifest to `flux/infra/kustomization.yaml`**

Change the file to exactly:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - longhorn.yaml
  - metallb.yaml
  - tailscale.yaml
  - tailscale-connector.yaml
  - longhorn-tailscale.yaml
```

- [ ] **Step 4: Verify Flux renders the service**

Run:

```bash
flux build kustomization flux-system --path ./flux | rg -U "kind: Service\nmetadata:\n(?:  labels:\n(?:    .*\n)+)?  name: longhorn-tailscale"
```

Expected: output includes `kind: Service` and `name: longhorn-tailscale`.

- [ ] **Step 5: Verify the rendered service has the required Tailscale fields**

Run:

```bash
flux build kustomization flux-system --path ./flux | rg -n "name: longhorn-tailscale|namespace: longhorn-system|type: LoadBalancer|loadBalancerClass: tailscale|app: longhorn-ui|targetPort: 8000"
```

Expected: output includes all six values.

## Task 2: Apply And Verify The Longhorn Tailscale Exposure

**Files:**
- Uses: `flux/infra/longhorn-tailscale.yaml`
- Uses: `flux/infra/kustomization.yaml`

- [ ] **Step 1: Apply the local Flux-rendered manifests**

Run:

```bash
flux build kustomization flux-system --path ./flux | kubectl apply -f -
```

Expected: output includes `service/longhorn-tailscale created` or `service/longhorn-tailscale configured`.

- [ ] **Step 2: Verify the service exists and uses Tailscale LoadBalancer class**

Run:

```bash
kubectl get svc longhorn-tailscale -n longhorn-system -o jsonpath='{.spec.type} {.spec.loadBalancerClass} {.spec.selector.app} {.spec.ports[0].port} {.spec.ports[0].targetPort}{"\n"}'
```

Expected:

```text
LoadBalancer tailscale longhorn-ui 80 8000
```

- [ ] **Step 3: Wait for Tailscale to provision the LoadBalancer**

Run:

```bash
kubectl wait --for=jsonpath='{.status.loadBalancer.ingress[0].hostname}'=longhorn-system-longhorn-tailscale.hartley-gray.ts.net svc/longhorn-tailscale -n longhorn-system --timeout=180s
```

Expected: command exits zero and prints that the condition was met.

- [ ] **Step 4: Verify the service has Longhorn UI endpoints**

Run:

```bash
kubectl get endpoints longhorn-tailscale -n longhorn-system -o jsonpath='{.subsets[0].addresses[*].ip} {.subsets[0].ports[0].port}{"\n"}'
```

Expected: output contains at least one pod IP and port `8000`.

- [ ] **Step 5: Verify the Tailscale provisioning condition**

Run:

```bash
kubectl get svc longhorn-tailscale -n longhorn-system -o jsonpath='{.status.conditions[?(@.type=="TailscaleProxyReady")].status} {.status.conditions[?(@.type=="TailscaleProxyReady")].reason}{"\n"}'
```

Expected:

```text
True ProxyCreated
```

- [ ] **Step 6: Verify Flux still builds cleanly after applying**

Run:

```bash
flux build kustomization flux-system --path ./flux >/tmp/longhorn-tailscale-flux-build.yaml
```

Expected: command exits zero.

## Task 3: Final Review And Commit

**Files:**
- Review: `flux/infra/longhorn-tailscale.yaml`
- Review: `flux/infra/kustomization.yaml`
- Review: `docs/superpowers/specs/2026-05-24-longhorn-tailscale-exposure-design.md`
- Review: `docs/superpowers/plans/2026-05-24-longhorn-tailscale-exposure.md`

- [ ] **Step 1: Review the working tree**

Run:

```bash
git status --short
git diff -- flux/infra/kustomization.yaml flux/infra/longhorn-tailscale.yaml docs/superpowers/specs/2026-05-24-longhorn-tailscale-exposure-design.md docs/superpowers/plans/2026-05-24-longhorn-tailscale-exposure.md
```

Expected: diff includes only the Longhorn Tailscale service, the infra kustomization entry, and the approved docs. If unrelated files are present, do not revert them; leave them out of the commit unless explicitly requested.

- [ ] **Step 2: Commit the Longhorn Tailscale exposure**

Run:

```bash
git add flux/infra/longhorn-tailscale.yaml flux/infra/kustomization.yaml docs/superpowers/specs/2026-05-24-longhorn-tailscale-exposure-design.md docs/superpowers/plans/2026-05-24-longhorn-tailscale-exposure.md
git commit -m "feat: expose Longhorn via Tailscale"
```

Expected: commit succeeds.

- [ ] **Step 3: Verify final repository state**

Run:

```bash
git status --short
git log -1 --oneline
```

Expected: `git log -1 --oneline` shows `feat: expose Longhorn via Tailscale`. `git status --short` may still show unrelated uncommitted Tailscale GitOps changes from the previous task; report them explicitly rather than reverting them.

## Self-Review

- Spec coverage: The plan creates the dedicated `Service/longhorn-tailscale`, adds it to the infra layer, leaves `longhorn-frontend` unchanged, and verifies service status, endpoints, Tailscale provisioning, and Flux rendering.
- Placeholder scan: No placeholders remain.
- Type consistency: Resource names, namespace, selector, service type, load balancer class, and port mapping match the approved spec.
