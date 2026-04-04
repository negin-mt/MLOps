# Cluster monitoring (Prometheus + Grafana)

This project installs **[kube-prometheus-stack](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack)** via `monitoring/install-monitoring.sh`.

## What you get

- **Prometheus** — scrapes cluster and workload metrics (via Prometheus Operator).
- **Grafana** — dashboards (many pre-provisioned), data source wired to Prometheus.
- **node-exporter** — node-level metrics.
- **kube-state-metrics** — Kubernetes object metrics.

Services are exposed as **LoadBalancer** (MetalLB) using `monitoring/values-kind.yaml`.

## Install

From the repo root:

```bash
chmod +x monitoring/install-monitoring.sh
./monitoring/install-monitoring.sh
```

Or as part of a full platform install:

```bash
./setup.sh full
```

Helm is downloaded to `.tools/helm` if it is not on your `PATH` (see `.gitignore`).

## Access

After install:

```bash
kubectl get svc -n monitoring
```

- **Grafana:** `http://<EXTERNAL_IP>/` — user `admin`, password from `monitoring/values-kind.yaml` (`grafana.adminPassword`) unless you override it.
- **Prometheus UI:** `http://<EXTERNAL_IP>:9090/` — use the LoadBalancer service whose port list starts with `9090`.

## Uninstall

```bash
helm uninstall kube-prometheus -n monitoring
kubectl delete namespace monitoring
```

## Notes

- On **small Kind** clusters, this stack is resource-heavy; reduce replicas or chart version only if you hit OOM.
- For **production**, use a strong Grafana password, TLS, and ingress; do not rely on default credentials.
