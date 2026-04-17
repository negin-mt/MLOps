from __future__ import annotations

import argparse
import json
import time

from student_lab.project import load_project_config, objective_metric, resolve_params, train_bundle


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="project.yaml")
    parser.add_argument("--n-estimators", type=int)
    parser.add_argument("--max-depth", type=int)
    parser.add_argument("--min-samples-split", type=int)
    parser.add_argument("--min-samples-leaf", type=int)
    args = parser.parse_args()

    config_data = load_project_config(args.config)
    params = resolve_params(
        config_data,
        {
            "n_estimators": args.n_estimators,
            "max_depth": args.max_depth,
            "min_samples_split": args.min_samples_split,
            "min_samples_leaf": args.min_samples_leaf,
        },
    )
    bundle = train_bundle(config_data, params)
    metric_name = config_data["project"]["objective_metric_name"]
    metric_value = objective_metric(config_data, bundle["metrics"])

    print(json.dumps({"params": params, "metrics": bundle["metrics"]}, indent=2), flush=True)
    print(f"{metric_name}={metric_value}", flush=True)
    # Give Katib's metrics collector time to read the final line before the pod exits.
    time.sleep(5)


if __name__ == "__main__":
    main()
