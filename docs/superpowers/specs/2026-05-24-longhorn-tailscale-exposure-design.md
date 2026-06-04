# Longhorn Tailscale Exposure Design

**Date:** 2026-05-24
**Status:** Approved for implementation
**Cluster:** k0s homelab

## Current State

Longhorn is installed through Flux using `flux/infra/longhorn.yaml`. The chart-managed `longhorn-frontend` service is a `ClusterIP` service in `longhorn-system` that selects `app: longhorn-ui` and targets the UI HTTP port.

Tailscale is installed through Flux using `flux/infra/tailscale.yaml`. The existing `Connector/homelab` and `Namespace/tailscale` are being moved into GitOps management in the current working tree. The Tailscale operator is healthy and supports `LoadBalancer` services with `loadBalancerClass: tailscale`.

The pre-Flux backup in `~/homelab-backup/longhorn-system-resources.yaml` exposed Longhorn with a separate service named `longhorn-tailscale`, not by modifying the Helm-managed `longhorn-frontend` service.

## Goal

Expose the Longhorn UI on the tailnet the same way it was exposed before Flux:

- Kubernetes resource: `Service/longhorn-tailscale`
- Namespace: `longhorn-system`
- Service type: `LoadBalancer`
- Load balancer class: `tailscale`
- Selector: `app: longhorn-ui`
- Port mapping: `80 -> 8000`
- Expected tailnet hostname: `longhorn-system-longhorn-tailscale.hartley-gray.ts.net`

## Design

Add a dedicated manifest `flux/infra/longhorn-tailscale.yaml`:

```yaml
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

Add the file to `flux/infra/kustomization.yaml` so Flux renders and applies it with the rest of the infrastructure layer.

The existing `longhorn-frontend` service remains Helm-managed and unchanged. This avoids taking ownership of chart-managed resources and keeps the Tailscale-specific exposure separate from the Longhorn chart.

## Data Flow

A tailnet client requests `longhorn-system-longhorn-tailscale.hartley-gray.ts.net` on port `80`. Tailscale's Kubernetes operator routes that request to the `longhorn-tailscale` LoadBalancer service. Kubernetes service routing selects `longhorn-ui` pods with `app: longhorn-ui` and forwards traffic to container port `8000`.

## Error Handling

If the Tailscale operator cannot provision the proxy, the service status should not receive a Tailscale hostname/IP and events on `Service/longhorn-tailscale` should describe the operator failure.

If the selector stops matching Longhorn UI pods after a chart change, the service will exist but have no endpoints. Verification must check both service status and endpoints.

## Testing And Verification

Implementation is complete only if these checks pass:

- `flux build kustomization flux-system --path ./flux` renders `Service/longhorn-tailscale`.
- Applying or reconciling the manifests creates/configures `Service/longhorn-tailscale` in `longhorn-system`.
- `kubectl get svc longhorn-tailscale -n longhorn-system` shows `TYPE=LoadBalancer` and a Tailscale hostname/IP in `EXTERNAL-IP` or service status.
- `kubectl get endpoints longhorn-tailscale -n longhorn-system` shows backend endpoints for Longhorn UI pods.
- `kubectl describe svc longhorn-tailscale -n longhorn-system` shows a `TailscaleProxyReady=True` condition or equivalent successful Tailscale provisioning signal.

## Out Of Scope

- Adding authentication in front of the Longhorn UI.
- Changing the Longhorn Helm chart values.
- Replacing the existing exit-node connector.
- Exposing Longhorn through Kubernetes Ingress.
