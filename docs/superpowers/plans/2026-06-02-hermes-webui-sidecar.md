# hermes-webui Sidecar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the hermes-webui container as a sidecar to the hermes-jon pod, exposing it on port 8787, sharing the existing `data` PVC.

**Architecture:** The hermes-agent Helm chart supports `extraContainers` (full Container spec passthrough) and `service.ports` (custom ports). The `data` PVC is always defined at the pod level when `persistence.enabled: true`, so sidecars can mount it directly. One file changes.

**Tech Stack:** Kubernetes, Helm, Flux CD, YAML

---

## Files Modified

- `flux/apps/hermes-jon.yaml` — add hermes-webui sidecar container, service port

---

### Task 1: Add hermes-webui sidecar container and service port

**Files:**
- Modify: `flux/apps/hermes-jon.yaml`

- [ ] **Step 1: Add hermes-webui sidecar to `extraContainers`**

After the existing `browserless-chromium` container entry (around line 93), add a new sidecar container. The `data` volume is already defined by the chart at the pod level when `persistence.enabled: true`, so the sidecar can reference it directly via `volumeMounts`.

Find the end of the `browserless-chromium` container block (the line with `seccompProfile:` followed by `type: RuntimeDefault` and the closing `}`), and add:

```yaml
      - image: ghcr.io/nesquena/hermes-webui:latest
        imagePullPolicy: Always
        name: hermes-webui
        ports:
          - containerPort: 8787
            name: webui
            protocol: TCP
        env:
          - name: WANTED_UID
            value: "1000"
          - name: WANTED_GID
            value: "1000"
          - name: HERMES_WEBUI_HOST
            value: "0.0.0.0"
        volumeMounts:
          - name: data
            mountPath: /home/hermeswebui/.hermes
          - name: data
            mountPath: /workspace
```

The sidecar mounts the existing `data` PVC at two paths:
- `/home/hermeswebui/.hermes` — agent config and state (required by webui)
- `/workspace` — workspace files (required by webui)

The webui connects to the hermes API at `localhost:8642` via pod-internal networking.

- [ ] **Step 2: Add port 8787 to the service**

In the `service` block at the bottom of the values (lines 190-197), add a second port entry. Replace the existing `service` block:

```yaml
    service:
      enabled: true
      ports:
        - containerPort: 8642
          name: api-server
          port: 8642
          protocol: TCP
          targetPort: 8642
        - containerPort: 8787
          name: webui
          port: 8787
          protocol: TCP
          targetPort: 8787
```

The Tailscale Service (`hermes-jon-tailscale.yaml`) uses a label selector that matches the pod, so it will automatically pick up the new port without modification.

- [ ] **Step 3: Verify YAML syntax**

Run a YAML syntax check:

```bash
python3 -c "import yaml; yaml.safe_load(open('flux/apps/hermes-jon.yaml'))"
```

Expected: no output (success).

- [ ] **Step 4: Commit**

```bash
git add flux/apps/hermes-jon.yaml
git commit -m "hermes: add webui sidecar on port 8787 with data volume"
```
