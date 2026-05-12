from __future__ import annotations

import argparse
import json

from kubernetes import client, config
from kubernetes.config.config_exception import ConfigException

from student_lab.project import latest_model_metadata, load_project_config, resolve_params, save_model_bundle, train_bundle


def best_params_from_katib(config_data: dict) -> dict:
    namespace = config_data["student"]["namespace"]
    experiment_name = f"{config_data['student']['name']}-search"
    try:
        config.load_incluster_config()
    except ConfigException:
        config.load_kube_config()
    api = client.CustomObjectsApi()
    experiment = api.get_namespaced_custom_object(
        group="kubeflow.org",
        version="v1beta1",
        namespace=namespace,
        plural="experiments",
        name=experiment_name,
    )
    assignments = experiment.get("status", {}).get("currentOptimalTrial", {}).get("parameterAssignments", [])
    if not assignments:
        raise RuntimeError("Katib has not produced best parameters yet")
    return {
        item["name"]: int(item["value"]) if str(item["value"]).isdigit() else item["value"]
        for item in assignments
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="project.yaml")
    parser.add_argument("--source", choices=["katib", "defaults"], default="katib")
    args = parser.parse_args()

    config_data = load_project_config(args.config)
    overrides = best_params_from_katib(config_data) if args.source == "katib" else None
    params = resolve_params(config_data, overrides)
    bundle = train_bundle(config_data, params)
    artifacts = save_model_bundle(config_data, bundle, params, args.source)
    print(json.dumps({"params": params, "metrics": bundle["metrics"], "artifacts": artifacts}, indent=2))


if __name__ == "__main__":
    main()

