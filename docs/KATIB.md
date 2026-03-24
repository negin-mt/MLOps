# Katib Documentation

This document describes how Katib works, the CRDs involved, the user workflow, and how results are returned. Use [draw.io](https://app.diagrams.net/) to recreate the block diagrams described in the *Draw.io Diagrams* section.

---

## 1. What is Katib?

**Katib** is Kubeflow's component for automated hyperparameter tuning and Neural Architecture Search (NAS). It runs multiple training jobs (Trials) with different hyperparameter values and selects the best one based on a user-defined objective metric (e.g. accuracy, loss).

---

## 2. Katib CRDs (Custom Resource Definitions)

Katib uses three main Kubernetes CRDs:

| CRD | Purpose |
|-----|---------|
| **Experiment** (`experiments.kubeflow.org`) | Defines a single tuning run: objective metric, search space, algorithm, max trials, trial template. |
| **Suggestion** (`suggestions.kubeflow.org`) | Holds hyperparameter proposals from the search algorithm (e.g. random, Bayesian). One Suggestion is created per Experiment. |
| **Trial** (`trials.kubeflow.org`) | One evaluation run with a specific hyperparameter set. Each Trial corresponds to one worker (e.g. a Kubernetes Job) that trains the model. |

### Experiment CRD

- **Objective**: Metric to optimize (e.g. `accuracy`), type (`maximize`/`minimize`), optional goal.
- **Parameters**: Search space (e.g. learning rate `lr` in [0.01, 0.1]).
- **Algorithm**: Search strategy (e.g. `random`, `grid`, Bayesian optimization).
- **Trial Template**: Template for the worker (e.g. a Job with a training container and `--lr=${trialParameters.learningRate}`).
- **Metrics Collector**: How to collect metrics from training output (e.g. StdOut with regex).

### Suggestion CRD

- Created automatically by the Katib controller when an Experiment is created.
- The algorithm service (e.g. random suggestion) fills `status.suggestions` with hyperparameter sets.
- The controller reads these and creates Trial resources.

### Trial CRD

- One Trial per suggested hyperparameter set.
- References the Experiment and Suggestion.
- Creates the worker resource (e.g. Job) from the trial template.
- Each Trial pod includes a metrics collector sidecar that parses training logs and sends metrics to the Katib DB.

**Check CRDs in the cluster:**
```bash
kubectl get crd | grep kubeflow
```

---

## 3. Katib Control Plane Components

| Component | Role |
|-----------|------|
| **katib-controller** | Watches Experiment, Suggestion, Trial; creates Suggestion and Trial resources; coordinates the workflow. |
| **katib-db-manager** | gRPC API for reading/writing experiment and trial data. |
| **katib-mysql** | MySQL backend storing experiments, trials, and metrics. |
| **katib-ui** | Web UI to view experiments and real-time graphs. |

---

## 4. User Workflow to Create a Katib Instance

### Step 1: Prepare Training Code

- Package training code in a Docker image.
- Ensure the training script outputs metrics in a format Katib can parse (e.g. `{metricName: accuracy, metricValue: 0.95}`).

### Step 2: Define the Experiment

**Option A – Python SDK (used in this project):**

```python
from kubeflow.katib import KatibClient, V1beta1Experiment, V1beta1ExperimentSpec, ...

client = KatibClient()
experiment = V1beta1Experiment(
    metadata=...,
    spec=V1beta1ExperimentSpec(
        objective=V1beta1ObjectiveSpec(type="maximize", objective_metric_name="accuracy", ...),
        algorithm=V1beta1AlgorithmSpec(algorithm_name="random"),
        parameters=[V1beta1ParameterSpec(name="lr", feasible_space=V1beta1FeasibleSpace(min="0.01", max="0.1"))],
        trial_template={...},  # Job template with training container
        max_trial_count=4,
        parallel_trial_count=2,
        metrics_collector_spec={...},
    ),
)
client.create_experiment(experiment, namespace="kubeflow")
```

**Option B – YAML:**

```bash
kubectl apply -f experiment.yaml -n kubeflow
```

### Step 3: Katib Controller Actions

1. Creates a **Suggestion** for the Experiment.
2. Algorithm service proposes hyperparameter sets.
3. Controller creates **Trial** resources for each set.
4. Each Trial creates a worker (e.g. Job) from the trial template.
5. Worker runs training; metrics collector parses logs and sends metrics to katib-db-manager.
6. Controller updates Experiment status (e.g. `currentOptimalTrial`) as Trials complete.

### Step 4: Monitor Progress

```bash
kubectl get experiment -n kubeflow
kubectl get trials -n kubeflow
kubectl get pods -n kubeflow -l katib.kubeflow.org/trial
```

---

## 5. How Katib Returns Results to the User

### Via Experiment Status

Results are stored in the Experiment's `status` field:

```yaml
status:
  currentOptimalTrial:
    bestTrialName: negin-mnist-hp-tuning-xyz123
    observation:
      metrics:
        - name: accuracy
          latest: "0.9014"
          max: "0.9014"
          min: "0.8236"
    parameterAssignments:
      - name: lr
        value: "0.0406"
  succeededTrialList: [...]
  runningTrialList: []
  trials: 4
  trialsSucceeded: 4
```

### Via kubectl

```bash
kubectl get experiment <name> -n kubeflow -o jsonpath='{.status.currentOptimalTrial}' | jq .
```

### Via Katib UI

The Katib UI (exposed at `http://<IP>/katib/`) shows experiments, trials, and real-time metric graphs.

### Via Python SDK

The Katib Python SDK can be used to list experiments and fetch results programmatically.

---

## 6. Draw.io Diagrams

Use [draw.io](https://app.diagrams.net/) to create the following diagrams. Export as PNG/SVG and add them to this document.

### Diagram 1: Katib Architecture (CRDs and Components)

**Blocks to draw:**
- **User** (top) → creates **Experiment** (CRD)
- **Katib Controller** (center) → watches Experiment, creates **Suggestion** (CRD), creates **Trial** (CRD)
- **Suggestion** → connects to **Algorithm Service** (e.g. random)
- **Trial** → creates **Worker** (e.g. Job with training container + metrics collector)
- **Worker** → sends metrics to **katib-db-manager** → **katib-mysql**
- **Katib Controller** → reads from DB, updates **Experiment.status**
- **User** → reads results via kubectl, Katib UI, or SDK

### Diagram 2: User Workflow

**Flow:**
1. User defines Experiment (SDK or YAML)
2. Katib Controller creates Suggestion
3. Algorithm proposes hyperparameters
4. Controller creates Trials
5. Trials spawn worker Jobs
6. Workers train, metrics collector parses output
7. Metrics stored in DB
8. Controller updates Experiment.status
9. User inspects best trial

### Diagram 3: Trial Pod Structure

**Blocks:**
- **Trial Pod** (one box)
  - **training-container**: runs model training (e.g. PyTorch MNIST)
  - **metrics-logger-and-collector**: sidecar that reads stdout, parses metrics with regex, sends to katib-db-manager

---

## 7. References

- [Katib Architecture (Kubeflow)](https://www.kubeflow.org/docs/components/katib/reference/architecture/)
- [Configure Experiment](https://www.kubeflow.org/docs/components/katib/user-guides/hp-tuning/configure-experiment/)
- [Trial Template Guide](https://www.kubeflow.org/docs/components/katib/user-guides/trial-template/)
- [Metrics Collector](https://www.kubeflow.org/docs/components/katib/user-guides/metrics-collector/)
