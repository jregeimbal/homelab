# Design: Add hermes-webui as Sidecar to jon-agent

## Goal

Add the hermes-webui as a sidecar container to the existing `hermes-jon` pod in the `jon-agent` namespace, exposing it on port 8787 and mounting the existing `data` volume at `/workspace`.

## Context

The `hermes-jon` deployment lives in namespace `jon-agent` and runs three containers:
- **hermes-agent** (main container) — API at port 8642
- **browserless-chromium** (extraContainer) — browser automation at port 3000
- A `data` PVC (5Gi, Longhorn) mounted at `/opt/data` on the main container

The `hermes-jon-tailscale.yaml` Service exposes port 8642 via Tailscale.

## Design

### Sidecar Container

Add `hermes-webui` as a new entry in the existing `extraContainers` list in `flux/apps/hermes-jon.yaml`:

```yaml
extraContainers:
  # ... existing browserless-chromium ...
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

The webui container connects to the hermes API at `localhost:8642` (same pod, no external access needed).

### Volume Mounts

Mount the existing `data` PVC at two paths inside the webui container:
- `/home/hermeswebui/.hermes` — agent config and state (required by webui)
- `/workspace` — workspace files (required by webui)

The PVC is already defined via the HelmRelease's `persistence` values block. We need to add a matching entry in `extraVolumes` for the sidecar to reference it.

### Service Exposure

Add port 8787 to the existing Service definition so the Tailscale Service automatically exposes it:

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

The Tailscale Service (`hermes-jon-tailscale.yaml`) uses a selector that matches the pod, so it will automatically pick up the new port without modification.

### Security

- No authentication configured by default (follows existing hermes-jon pattern — access via Tailscale only)
- Webui binds to `0.0.0.0` to be reachable within the pod
- No privilege escalation needed — uses default non-root user

## Files Changed

- `flux/apps/hermes-jon.yaml` — add sidecar container, volume mounts, and service port
