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
- `curl` (used by the monitoring installer to fetch Helm if needed)

## Quick Install

```bash
# Run full setup from scratch
chmod +x setup.sh
./setup.sh full
```

This will: create Kind cluster, install MetalLB, Istio, Code-Server (with Python image), Katib, and **Prometheus + Grafana** (see [Monitoring](#monitoring)). RBAC is applied so Code-Server can create Katib experiments.

## Step-by-Step Install

```bash
./setup.sh cluster    # Create Kind cluster
./setup.sh metallb    # Install and configure MetalLB
./setup.sh istio      # Install Istio
./setup.sh vscode     # Install Code-Server and Istio Gateway (builds Python image)
./setup.sh katib      # Install Katib standalone and RBAC
./setup.sh monitoring # Prometheus + Grafana only (Helm chart)
```

## Monitoring

The stack uses **kube-prometheus-stack** (Prometheus Operator, Prometheus, Grafana, node-exporter, kube-state-metrics). Grafana and Prometheus are exposed via **MetalLB LoadBalancer** services (`monitoring/values-kind.yaml`).

**Install without re-running the full platform:**

```bash
chmod +x monitoring/install-monitoring.sh
./monitoring/install-monitoring.sh
```

Default Grafana login: user `admin`, password `mlops-grafana` (change `grafana.adminPassword` in `monitoring/values-kind.yaml` for shared or production clusters).

```bash
kubectl get svc -n monitoring
```

More detail: **[docs/MONITORING.md](docs/MONITORING.md)**.

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

## Katib UI Quick Test (minimal working setup)

Use this when you only want to validate experiment creation/execution from the UI.

### If the UI has no “Metrics format” field (and you do not use YAML)

The `pytorch-mnist` image prints metrics like `{metricName: accuracy, metricValue: ...}`. Katib needs a **regex** (`metricsFormat`) on the Experiment to read that from StdOut. Many Katib UIs only let you pick **StdOut** and **never show a field for the regex**, and **“Edit and submit YAML”** may be disabled or unavailable. In that situation **the form alone cannot fix MetricsUnavailable**; it is a UI/product gap, not something you misconfigured.

**Practical approach (no YAML files, no kubectl apply):**

1. **Create the experiment from VS Code** with the Python SDK: run `python3 katib_experiment.py` (see [Run from VS Code](#run-from-vscode) below). That script sets `metricsCollectorSpec` and the correct objective; it talks to the API directly.
2. **Use the Katib UI only to watch** experiments, trials, and graphs after they exist.

You still get a normal Katib workflow; only the **creation** step moves from the broken form to one command in the editor.

### UI fields to fill

- **Experiment Name**: `ui-test-experiment` (must be lowercase)
- **Namespace**: `kubeflow-user-negin`
- **Objective**: `maximize`, metric name `accuracy`, goal `0.99` (do not add extra metrics such as `Train-accuracy` unless the image logs them)
- **Algorithm**: `random`
- **Max Trials**: `4`
- **Parallel Trials**: `1` (quota-safe for this local setup)
- **Max Failed Trials**: `3`
- **Parameter** (one only):
  - name: `lr`
  - type: `double`
  - min: `0.01`
  - max: `0.1`
- **Metrics Collector**: `StdOut`
- **Metrics format** (only if your UI shows this field; otherwise use `katib_experiment.py` as above):
  - `\{metricName: ([\w|-]+), metricValue: ((-?\d+)(\.\d+)?)\}`
- **Primary Container Name**: `training-container`
- **Success Condition**: `status.conditions.#(type=="Complete")`
- **Failure Condition**: `status.conditions.#(type=="Failed")`
- **Trial Parameter mapping**:
  - name: `learningRate`
  - reference: `lr`

### TrialSpec YAML (paste in UI editor)

```yaml
apiVersion: batch/v1
kind: Job
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: training-container
          image: docker.io/kubeflowkatib/pytorch-mnist-cpu:v0.16.0
          imagePullPolicy: IfNotPresent
          command:
            - python3
            - /opt/pytorch-mnist/mnist.py
            - --lr=${trialParameters.learningRate}
          resources:
            requests:
              cpu: "1"
              memory: 2Gi
            limits:
              cpu: "1"
              memory: 2Gi
```

### Common UI errors and fixes

- **`metadata.name ... lowercase RFC 1123`**
  - Use lowercase names only (example: `ui-test-experiment`).
- **`spec.trialTemplate.trialParameters must be specified`**
  - Add trial parameter mapping (`learningRate -> lr`) and use `${trialParameters.learningRate}` in command.
- **`Number of TrialAssignment ... != ... TrialSpec`**
  - Parameter count mismatch: keep one parameter (`lr`) for this YAML, or wire all parameters into command and trial mappings.
- **`exceeded quota: user-quota`**
  - Reduce parallelism to `1` (recommended for local test), or reduce requested resources.

### Bug encountered: “Experiment has failed because max failed count has reached”

This showed up while creating experiments from the **Katib UI** with the **`pytorch-mnist`** example image (`docker.io/kubeflowkatib/pytorch-mnist-cpu`).

**What it looked like**

- The Katib UI reported the experiment as failed with a message like **“Experiment has failed because max failed count has reached.”**
- Individual trials often ended as **`MetricsUnavailable`** even when the Kubernetes **Job completed** and the training pod had run.
- `kubectl describe trial …` / trial status showed **MetricsUnavailable** and metrics (**`accuracy`**, or extra names like **`Train-accuracy`**) as **unavailable**.

**What was actually wrong**

1. **StdOut without `metricsFormat`** — The UI only offered **StdOut** for the metrics collector and did **not** expose a field to set the **regex** (`metricsFormat`). The live Experiment CR then had `metricsCollectorSpec.collector.kind: StdOut` but **no** `source.filter.metricsFormat`. Katib could not parse lines such as `{metricName: accuracy, metricValue: …}` from the container logs, so it treated trials as failed for metrics.
2. **Wrong objective metric names** — Using **`Validation-accuracy`** or **`Train-accuracy`** as the primary metric when the image reports **`accuracy`** under that log format also prevents a successful observation.
3. **Extra “additional” metrics** — Adding **`Train-accuracy`** (or similar) in the objective when the training job does not emit that **exact** metric name worsens or triggers unavailable metrics.
4. **Trial template vs hyperparameters** — A template that references **`${trialParameters.momentum}`** (e.g. default ConfigMap example) while only **`lr`** is defined in the wizard causes parameter/substitution mismatches.
5. **`maxFailedTrialCount` too low** — e.g. **`1`** stops the whole experiment on the first metrics failure, which is easy to hit when (1) applies.

**Why the UI alone could not fix it**

Many Katib builds **do not** show a **metrics format** input next to StdOut, and **YAML submit** may be unavailable. Without setting `metricsFormat` on the Experiment (API/YAML/SDK), the form path **cannot** fix the parsing issue.

**What worked**

- **Create the experiment with** `python3 katib_experiment.py` **from VS Code** (SDK sets `metricsCollectorSpec` including the regex), **or** apply a full Experiment manifest that includes `metricsCollectorSpec.source.filter.metricsFormat`.
- In the UI (for future runs or other clusters): objective metric **`accuracy`**, **no** spurious additional metrics, **StdOut** + metrics format if the UI provides it, trial command aligned with hyperparameters only, **parallel trials: 1** if quota errors appear, **`maxFailedTrialCount` ≥ 3** while debugging.

---

## Running Katib Experiment

### First-Time Setup: Copy Script into Code-Server

The Code-Server workspace (PVC) starts empty. Copy the experiment script once:

```bash
POD=$(kubectl get pod -n default -l app=code-server -o jsonpath='{.items[0].metadata.name}')
kubectl cp katib_experiment.py default/$POD:/home/coder/project/katib_experiment.py
kubectl cp katib_read_results.py default/$POD:/home/coder/project/katib_read_results.py
```

### Run from VS Code

1. Open VS Code at `http://<EXTERNAL_IP>/vscode/`
2. Open `/home/coder/project/katib_experiment.py`
3. Run: `python3 katib_experiment.py`

The Code-Server image includes `kubeflow-katib` and `kubernetes`; no extra pip install is needed.

### Read results with the Python SDK (same data as kubectl / Katib UI)

Katib stores results in the **Experiment** and **Trial** objects in the API. The SDK reads them with `KatibClient.get_experiment`, `get_optimal_hyperparameters`, and `list_trials`—so you can script reporting without relying only on `kubectl` or the web UI.

```bash
# Default: EXPERIMENT_NAME=negin-mnist-hp-tuning-final, KATIB_NAMESPACE=kubeflow-user-negin
# Human-friendly table (good for demos, screenshots, thesis discussion)
python3 katib_read_results.py --summary

# Technical JSON-style dump (status + trials)
python3 katib_read_results.py

# Full Experiment object
python3 katib_read_results.py --full
```

#### User-friendly ways to get results (for supervision / reports)

“User friendly” is not a single screen: different audiences need different surfaces.

| Approach | Who it suits | Role |
|----------|----------------|------|
| **Katib UI** (`/katib/`) | Non-developers, exploration | Charts, trial list, experiment status — **most visual**, when experiments complete successfully. |
| **`python3 katib_read_results.py --summary`** | You + your professor + reproducible reports | One command from VS Code: objective, condition, optimal hyperparameters, trial table with metric column — **no raw YAML**. |
| **`kubectl get experiment/trials -o yaml`** | Operators, debugging | Exact cluster state; less readable for stakeholders. |

**Honest limitation you can state in the thesis:** the stock Katib **create** wizard often omits StdOut **metrics format**, which can block successful metrics in the UI until experiments are created via the **SDK** (or YAML). That does **not** block **getting results back** in a friendly way: once tuning runs correctly, the **same** results appear in the **UI** and in **`--summary`**. The recommended story for “best way to get results back” is therefore: **create with `katib_experiment.py`**, **monitor in Katib UI**, **export / present with `katib_read_results.py --summary`** (and UI screenshots where useful).

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

### Future: production cluster with NVIDIA GPUs (device plugin)

Local Kind setups are often **CPU-only**: nodes do not advertise `nvidia.com/gpu`, so GPU trial templates stay `Pending` until the **cluster** exposes GPUs. For a **real** NVIDIA GPU cluster (e.g. university server, cloud GPU nodes), cluster administrators typically install:

1. **NVIDIA driver** on GPU worker nodes  
2. **NVIDIA Container Toolkit** so the container runtime can use GPUs  
3. **[NVIDIA Kubernetes Device Plugin](https://github.com/NVIDIA/k8s-device-plugin#quick-start)** so Kubernetes reports GPU capacity (`nvidia.com/gpu`) on nodes

This repository does **not** replace step 3: `katib_experiment.py` requests `nvidia.com/gpu` when `HARDWARE_BACKEND=nvidia`; the device plugin (or your cloud’s equivalent) is what makes that resource exist for the scheduler.

**Verify after cluster setup:**

```bash
kubectl describe node <gpu-node-name> | grep -E "Allocatable|nvidia.com/gpu"
```

**AMD / ROCm:** use your distribution’s device plugin or operator so nodes advertise `amd.com/gpu` (same idea as NVIDIA; see also `HARDWARE_BACKEND=amd` in `katib_experiment.py`).

**Sharing GPUs fairly** across users remains a **policy** concern: keep using **namespaces**, **ResourceQuota**, and **LimitRange** (see `multi-user-namespaces.yaml` and `katib-guardrails.yaml`). The device plugin enables scheduling; quotas enforce fair use.

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
├── setup.sh              # Main setup script (Kind, MetalLB, Istio, Code-Server, Katib, monitoring)
├── monitoring/
│   ├── install-monitoring.sh  # Helm: kube-prometheus-stack (Prometheus + Grafana)
│   └── values-kind.yaml       # Kind-friendly chart values (LoadBalancer, smaller retention)
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
├── katib_read_results.py # SDK: print experiment status / trials (same info as kubectl/UI)
├── requirements.txt      # Python dependencies (for reference)
├── docs/
│   ├── KATIB.md                         # Katib documentation (CRDs, workflow, diagrams)
│   ├── MONITORING.md                    # Prometheus + Grafana install notes
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
