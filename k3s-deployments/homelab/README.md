# Deploy homelab apps

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: 'apps'
spec:
  project: default
  source:
    repoURL: 'git@github.com:jregeimbal/homelab.git'
    path: k3s-deployments/homelab
    targetRevision: HEAD
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: homelab
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```