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
- **Katib UI**: See [Accessing Katib UI](#accessing-katib-ui) below

## Accessing Katib UI

The Katib UI lets you view experiments, trials, and real-time metric graphs. **Use the `/katib/` path** (not the root).

**Option 1 – Via Istio (same IP as VS Code):**  
Open `http://<EXTERNAL_IP>/katib/` (same IP from `kubectl get svc -n istio-system istio-ingressgateway`).

**Option 2 – LoadBalancer (separate IP):**
```bash
kubectl apply -f katib-ui-expose.yaml
kubectl get svc katib-ui-lb -n kubeflow
```
Then open `http://<KATIB_UI_IP>/katib/`.

**Option 3 – Port-forward:**
```bash
kubectl port-forward -n kubeflow svc/katib-ui 8080:80
```
Then open `http://localhost:8080/katib/`.

---

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

### Multi-user namespaces and fair-share quotas

To support multiple users on the same cluster, this project creates dedicated namespaces:

- `kubeflow-user-negin`
- `kubeflow-user-yousef`

Each namespace has its own:

- `LimitRange` (per-container min/max/default resources)
- `ResourceQuota` (total namespace CPU, memory, GPU budget)
- namespace-scoped RBAC for creating Katib experiments
- required Katib label: `katib.kubeflow.org/metrics-collector-injection=enabled`

This ensures one user cannot consume all cluster resources and impact others.

Apply manually (also applied by `./setup.sh katib`):

```bash
kubectl apply -f multi-user-namespaces.yaml
```

Run the experiment in a specific namespace:

```bash
KATIB_NAMESPACE=kubeflow-user-negin python3 katib_experiment.py
KATIB_NAMESPACE=kubeflow-user-yousef python3 katib_experiment.py
```

### Check Status

```bash
kubectl get experiment -n kubeflow
kubectl get trials -n kubeflow
```

### Inspect Best Trial

```bash
kubectl get experiment negin-mnist-hp-tuning -n kubeflow -o jsonpath='{.status.currentOptimalTrial}' | jq .
```

### Allocate resources per Trial (CPU/GPU)

`katib_experiment.py` uses fixed trial sizing per worker container:

- CPU: `1`
- Memory: `2Gi`
- GPU: selected automatically from hardware backend (`0` for CPU, `1` for GPU backends)

### Hardware-agnostic trial template (CPU / NVIDIA / AMD)

The trial template is parametric and supports multiple hardware targets by switching:

- training image
- GPU resource key (`nvidia.com/gpu` vs `amd.com/gpu`)

Current switch:

```bash
HARDWARE_BACKEND=cpu|nvidia|amd
```

Examples:

```bash
# CPU-only (default)
KATIB_NAMESPACE=kubeflow-user-negin HARDWARE_BACKEND=cpu python3 katib_experiment.py

# NVIDIA/CUDA cluster
KATIB_NAMESPACE=kubeflow-user-negin HARDWARE_BACKEND=nvidia python3 katib_experiment.py

# AMD/ROCm cluster
KATIB_NAMESPACE=kubeflow-user-negin HARDWARE_BACKEND=amd python3 katib_experiment.py
```

Mapping used by the script:

- `cpu` -> image `CPU_TRAINING_IMAGE`, no GPU key
- `nvidia` -> image `NVIDIA_TRAINING_IMAGE`, resource key `nvidia.com/gpu: 1`
- `amd` -> image `AMD_TRAINING_IMAGE`, resource key `amd.com/gpu: 1`

You can override image references without changing code:

```bash
NVIDIA_TRAINING_IMAGE=<your-cuda-image> HARDWARE_BACKEND=nvidia python3 katib_experiment.py
AMD_TRAINING_IMAGE=<your-rocm-image> HARDWARE_BACKEND=amd python3 katib_experiment.py
```

Verify available GPU resource keys on your node:

```bash
kubectl describe node | grep -A3 -E "Allocatable|Capacity|nvidia.com/gpu|amd.com/gpu"
```

### Enforced guardrails (cluster-side, cannot be bypassed by editing Python)

To prevent excessive requests (even if someone edits the experiment script), this project applies namespace guardrails in `kubeflow`:

- **LimitRange** (`katib-trial-limits`): per-container hard max and defaults
- **ResourceQuota** (`katib-quota`): namespace-wide total budget

Defaults in `katib-guardrails.yaml` (good for a local Kind setup):

- Per trial container max: **2 CPU**, **4Gi memory**
- Namespace total budget: **4 CPU**, **8Gi memory**, **1 GPU**

Applied automatically by `./setup.sh katib` (or `./setup.sh full`), or manually:

```bash
kubectl apply -f katib-guardrails.yaml
```

Verify:

```bash
kubectl get limitrange -n kubeflow
kubectl get resourcequota -n kubeflow
kubectl describe limitrange katib-trial-limits -n kubeflow
kubectl describe resourcequota katib-quota -n kubeflow
```

If a user submits a trial above policy, Kubernetes rejects pod creation with a clear message, for example:

`is forbidden: maximum cpu usage per Container is 2, but limit is 3`

Check recent events with:

```bash
kubectl get events -n kubeflow --sort-by=.lastTimestamp | tail -30
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

### Restricted networks (university Wi‑Fi, corporate)

Some networks block DNS to public resolvers (e.g. `8.8.8.8` times out from your laptop). Then CoreDNS inside Kind cannot resolve names either, and trial pods fail when downloading datasets (e.g. Fashion-MNIST) with errors like `Temporary failure in name resolution`.

**What to do:**

- Use a network that allows DNS (e.g. **mobile hotspot**), or configure CoreDNS `forward` to use **nameservers your network allows** (see `nameserver` lines in `/etc/resolv.conf` on the host).
- After changing CoreDNS, restart it: `kubectl rollout restart deployment/coredns -n kube-system`.


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

## Katib Documentation

For detailed Katib documentation (CRDs, user workflow, results), see **[docs/KATIB.md](docs/KATIB.md)**. It includes:
- Katib CRDs (Experiment, Suggestion, Trial)
- User workflow to create experiments
- How Katib returns results
- Draw.io diagram descriptions for block diagrams

---

## File Structure

```
Tesi/
├── setup.sh              # Main setup script (Kind, MetalLB, Istio, Code-Server, Katib)
├── kind-config.yaml      # Kind configuration (port mappings 80, 443)
├── metallb-config.yaml   # MetalLB IP pool (optional; setup.sh creates it)
├── vscode.yaml           # Code-Server StatefulSet + Service + PVC
├── istio-networking.yaml  # Istio Gateway and VirtualService (vscode)
├── katib-ui-expose.yaml   # LoadBalancer to expose Katib UI (optional)
├── multi-user-namespaces.yaml # Per-user namespaces + quotas + LimitRanges + RBAC
├── katib-guardrails.yaml  # LimitRange + ResourceQuota for trial resource enforcement
├── code-server-rbac.yaml # RBAC: Code-Server can create Katib experiments in kubeflow
├── Dockerfile.code-server# Custom Code-Server image with Python + kubeflow-katib
├── katib_experiment.py   # Python script to create Katib MNIST tuning experiment
├── requirements.txt      # Python dependencies (for reference)
├── docs/
│   ├── KATIB.md                         # Katib documentation (CRDs, workflow, diagrams)
│   ├── katib-architecture.drawio.svg    # Diagram 1 (architecture)
│   ├── katib-user-workflow.png          # Diagram 2 (user workflow)
│   └── katib-trial-pod-structure.png    # Diagram 3 (trial pod)
└── README.md
```

---

## Notes

- Code-Server runs as a StatefulSet with 5Gi PVC; code and settings persist after pod restart.
- Katib uses the official standalone install (`kubeflow/katib` manifests v0.17.0).
- VirtualService routes `/vscode` to code-server. Katib UI is exposed via `katib-ui-expose.yaml` (LoadBalancer) or port-forward.
- The experiment tunes learning rate for Fashion-MNIST; best trial and metrics are available in the experiment status.
