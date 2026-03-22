# MLOps Platform - Kind + Istio + MetalLB + Code-Server + Katib

Thesis project: Simulating a cloud environment locally for MLOps development and testing with Kubeflow Katib.

## Architecture

| Layer | Tool | Purpose |
|-------|------|---------|
| Infrastructure | **Kind** | Local Kubernetes cluster |
| Network | **MetalLB** | Assign External IPs to services |
| Service Mesh | **Istio** | Traffic management, Gateway, VirtualService |
| Development | **Code-Server** | Web-based VS Code (StatefulSet + PVC) |
| Optimization | **Katib** | Hyperparameter Tuning |

## Prerequisites

- Docker
- `kind`
- `kubectl`
- `istioctl` (for Istio installation)

## Quick Install

```bash
# Run full setup from scratch
chmod +x setup.sh
./setup.sh full
```

This will: create Kind cluster, install MetalLB, Istio, Code-Server (with Python image), and Katib. RBAC is applied so Code-Server can create Katib experiments.

## Step-by-Step Install

```bash
./setup.sh cluster    # Create Kind cluster
./setup.sh metallb    # Install and configure MetalLB
./setup.sh istio      # Install Istio
./setup.sh vscode     # Install Code-Server and Istio Gateway (builds Python image)
./setup.sh katib      # Install Katib standalone and RBAC
```

## Access

After installation, get the External IP:

```bash
kubectl get svc -n istio-system istio-ingressgateway
```

- **VS Code**: `http://<EXTERNAL_IP>/vscode/` or `http://<EXTERNAL_IP>/`
- **Password**: `1234`

## Running Katib Experiment

### First-Time Setup: Copy Script into Code-Server

The Code-Server workspace (PVC) starts empty. Copy the experiment script once:

```bash
POD=$(kubectl get pod -n default -l app=code-server -o jsonpath='{.items[0].metadata.name}')
kubectl cp katib_experiment.py default/$POD:/home/coder/project/katib_experiment.py
```

### Run from VS Code

1. Open VS Code at `http://<EXTERNAL_IP>/vscode/`
2. Open `/home/coder/project/katib_experiment.py`
3. Run: `python3 katib_experiment.py`

The Code-Server image includes `kubeflow-katib` and `kubernetes`; no extra pip install is needed.

### Check Status

```bash
kubectl get experiment -n kubeflow
kubectl get trials -n kubeflow
```

### Inspect Best Trial

```bash
kubectl get experiment negin-mnist-hp-tuning -n kubeflow -o jsonpath='{.status.currentOptimalTrial}' | jq .
```

---

## Server Deployment

To deploy on a remote server:

1. Copy the project to the server (e.g. via `scp` or `git clone`).
2. Ensure prerequisites are installed on the server: Docker, kind, kubectl, istioctl.
3. Run the full setup:
   ```bash
   cd /path/to/Tesi
   chmod +x setup.sh
   ./setup.sh full
   ```
4. Copy the experiment script into Code-Server (see above).
5. Access VS Code at `http://<SERVER_IP>/vscode/` and run the Katib experiment.

The server must allow inbound traffic on ports 80 and 443 (or the ports configured in `kind-config.yaml`).

---

## Troubleshooting

### DNS Resolution Inside Cluster

If pods cannot resolve external hostnames (e.g. `quay.io`, `docker.io`), patch CoreDNS to use upstream DNS:

```bash
kubectl get configmap coredns -n kube-system -o yaml | sed 's/forward \. \/etc\/resolv.conf/forward . 8.8.8.8 8.8.4.4/' | kubectl apply -f -
```

### ImagePullBackOff

If the cluster cannot pull images (e.g. due to DNS or network restrictions), preload images on the host and load into Kind:

```bash
# Preload Katib / MNIST images (examples)
docker pull docker.io/kubeflowkatib/pytorch-mnist-cpu:v0.16.0
kind load docker-image docker.io/kubeflowkatib/pytorch-mnist-cpu:v0.16.0 --name kind
```

### Code-Server Has Old Script

If you edit `katib_experiment.py` on the host and want the changes in Code-Server, copy again:

```bash
POD=$(kubectl get pod -n default -l app=code-server -o jsonpath='{.items[0].metadata.name}')
kubectl cp katib_experiment.py default/$POD:/home/coder/project/katib_experiment.py
```

### Katib RBAC / 403

If creating experiments from VS Code fails with "Forbidden", ensure RBAC is applied:

```bash
kubectl apply -f code-server-rbac.yaml
```

---

## File Structure

```
Tesi/
├── setup.sh              # Main setup script (Kind, MetalLB, Istio, Code-Server, Katib)
├── kind-config.yaml      # Kind configuration (port mappings 80, 443)
├── metallb-config.yaml   # MetalLB IP pool (optional; setup.sh creates it)
├── vscode.yaml           # Code-Server StatefulSet + Service + PVC
├── istio-networking.yaml # Istio Gateway and VirtualService
├── code-server-rbac.yaml # RBAC: Code-Server can create Katib experiments in kubeflow
├── Dockerfile.code-server# Custom Code-Server image with Python + kubeflow-katib
├── katib_experiment.py   # Python script to create Katib MNIST tuning experiment
├── requirements.txt      # Python dependencies (for reference)
└── README.md
```

---

## Notes

- Code-Server runs as a StatefulSet with 5Gi PVC; code and settings persist after pod restart.
- Katib uses the official standalone install (`kubeflow/katib` manifests v0.17.0).
- VirtualService routes `/vscode` to code-server (with rewrite to `/`).
- The experiment tunes learning rate for Fashion-MNIST; best trial and metrics are available in the experiment status.
