#!/usr/bin/env python3
"""
Read Katib experiment results via the Python SDK (same data as kubectl / UI).

Uses kubeflow-katib KatibClient: get_experiment, get_optimal_hyperparameters, list_trials.
Run from Code-Server or any environment with kubeconfig and kubeflow-katib installed.

Examples:
  python3 katib_read_results.py
  KATIB_NAMESPACE=kubeflow-user-negin EXPERIMENT_NAME=negin-mnist-hp-tuning-final python3 katib_read_results.py
  python3 katib_read_results.py --full
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from kubeflow.katib import KatibClient


def _json_dump(obj: object) -> str:
    return json.dumps(obj, indent=2, default=str)


def main() -> None:
    parser = argparse.ArgumentParser(description="Print Katib experiment results from the SDK")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Print full Experiment object (large); default is status + trials summary only",
    )
    args = parser.parse_args()

    namespace = os.getenv("KATIB_NAMESPACE", "kubeflow-user-negin")
    name = os.getenv("EXPERIMENT_NAME", "negin-mnist-hp-tuning-final")

    client = KatibClient()

    try:
        exp = client.get_experiment(name, namespace)
    except Exception as e:
        print(f"Error fetching experiment '{name}' in '{namespace}': {e}", file=sys.stderr)
        sys.exit(1)

    optimal = None
    try:
        optimal = client.get_optimal_hyperparameters(name, namespace)
    except Exception:
        pass

    trials = client.list_trials(name, namespace)

    print(f"Experiment: {name}")
    print(f"Namespace:  {namespace}")
    print()

    if args.full:
        print(_json_dump(exp.to_dict()))
        return

    status_dict = exp.status.to_dict() if exp.status else {}
    print("=== status (SDK / same as kubectl -o yaml) ===")
    print(_json_dump(status_dict))
    print()

    print("=== get_optimal_hyperparameters() ===")
    print(_json_dump(optimal) if optimal is not None else "null (experiment may still be running or no optimal yet)")
    print()

    trial_summaries = []
    for t in trials:
        d = t.to_dict()
        meta = d.get("metadata", {})
        st = d.get("status", {}) or {}
        trial_summaries.append(
            {
                "name": meta.get("name"),
                "conditions": st.get("conditions"),
            }
        )
    print(f"=== list_trials() ({len(trials)} trials) ===")
    print(_json_dump(trial_summaries))


if __name__ == "__main__":
    main()
