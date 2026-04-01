#!/usr/bin/env python3
"""
Katib Experiment - Hyperparameter tuning with Kubeflow Katib SDK
This script creates an Experiment in Katib.
Run from inside VS Code (code-server) with kubeflow-katib and kubernetes installed.
"""
import os

from kubernetes.client import V1ObjectMeta
from kubeflow.katib import (
    KatibClient,
    V1beta1Experiment,
    V1beta1ExperimentSpec,
    V1beta1AlgorithmSpec,
    V1beta1ObjectiveSpec,
    V1beta1ParameterSpec,
    V1beta1FeasibleSpace,
)

# 1. Initialize Katib Client (uses default kubeconfig)
client = KatibClient()

# 2. Experiment settings
EXPERIMENT_NAME = "negin-mnist-hp-tuning-final"
NAMESPACE = "kubeflow"
TRIAL_CPU = os.getenv("TRIAL_CPU", "10")
TRIAL_MEMORY = os.getenv("TRIAL_MEMORY", "16Gi")
TRIAL_GPU = os.getenv("TRIAL_GPU", "0")

trial_resources = {
    "requests": {
        "cpu": TRIAL_CPU,
        "memory": TRIAL_MEMORY,
    },
    "limits": {
        "cpu": TRIAL_CPU,
        "memory": TRIAL_MEMORY,
    },
}
if TRIAL_GPU != "0":
    trial_resources["requests"]["nvidia.com/gpu"] = TRIAL_GPU
    trial_resources["limits"]["nvidia.com/gpu"] = TRIAL_GPU

# 3. Define Experiment
experiment = V1beta1Experiment(
    api_version="kubeflow.org/v1beta1",
    kind="Experiment",
    metadata=V1ObjectMeta(
        name=EXPERIMENT_NAME,
        namespace=NAMESPACE,
    ),
    spec=V1beta1ExperimentSpec(
        max_trial_count=4,
        parallel_trial_count=2,
        max_failed_trial_count=3,
        metrics_collector_spec={
            "collector": {"kind": "StdOut"},
            "source": {
                "filter": {
                    "metricsFormat": [
                        r'\{metricName: ([\w|-]+), metricValue: ((-?\d+)(\.\d+)?)\}',
                    ],
                },
            },
        },
        objective=V1beta1ObjectiveSpec(
            type="maximize",
            goal=0.99,
            objective_metric_name="accuracy",
        ),
        algorithm=V1beta1AlgorithmSpec(
            algorithm_name="random",
        ),
        parameters=[
            V1beta1ParameterSpec(
                name="lr",
                parameter_type="double",
                feasible_space=V1beta1FeasibleSpace(min="0.01", max="0.1"),
            ),
        ],
        trial_template={
            "primaryContainerName": "training-container",
            "successCondition": "status.conditions.#(type==\"Complete\")",
            "failureCondition": "status.conditions.#(type==\"Failed\")",
            "trialParameters": [
                {"name": "learningRate", "reference": "lr"},
            ],
            "trialSpec": {
                "apiVersion": "batch/v1",
                "kind": "Job",
                "spec": {
                    "template": {
                        "spec": {
                            "restartPolicy": "Never",
                            "containers": [
                                {
                                    "name": "training-container",
                                    "image": "docker.io/kubeflowkatib/pytorch-mnist-cpu:v0.16.0",
                                    "imagePullPolicy": "IfNotPresent",
                                    "resources": trial_resources,
                                    "command": [
                                        "python3",
                                        "/opt/pytorch-mnist/mnist.py",
                                        "--lr=${trialParameters.learningRate}",
                                    ],
                                }
                            ],
                        }
                    }
                },
            },
        },
    ),
)

# 4. Create experiment in cluster
if __name__ == "__main__":
    try:
        client.create_experiment(experiment, namespace=NAMESPACE)
        print(f"Experiment '{EXPERIMENT_NAME}' created successfully.")
        print(f"  Trial resources: cpu={TRIAL_CPU}, memory={TRIAL_MEMORY}, gpu={TRIAL_GPU}")
        print(f"  Check status: kubectl get experiment -n {NAMESPACE} {EXPERIMENT_NAME}")
        print(f"  Check trials: kubectl get trials -n {NAMESPACE} -l experiment={EXPERIMENT_NAME}")
    except Exception as e:
        print(f"Error creating experiment: {e}")
        raise
