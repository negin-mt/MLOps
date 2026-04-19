from __future__ import annotations

import argparse
import os
from pathlib import Path

from student_lab.project import AUTO_CONFIG, compute_profile, load_project_config


ROOT_DIR = Path(os.getenv("PROJECT_ROOT", str(Path.cwd())))
TEMPLATE_DIR = ROOT_DIR / "manifests"
RENDERED_DIR = ROOT_DIR / "manifests" / "rendered"


def manifest_context(config_data: dict) -> dict[str, str]:
    profile = compute_profile(config_data)
    serving_cfg = config_data.get("serving", {})
    serving_requests = serving_cfg.get("requests", {"cpu": "100m", "memory": "256Mi"})
    serving_limits = serving_cfg.get("limits", {"cpu": "500m", "memory": "512Mi"})
    student = config_data["student"]["name"]
    namespace = config_data["student"]["namespace"]
    bucket = config_data["student"]["bucket"]
    gpu_limit = ""
    if profile["gpu"]:
        gpu_limit = f"            {profile['gpu']}: \"1\"\n"

    return {
        "__STUDENT__": student,
        "__NAMESPACE__": namespace,
        "__BUCKET__": bucket,
        "__WORKSPACE_PVC__": config_data["kubernetes"]["workspace_pvc"],
        "__SERVICE_ACCOUNT__": config_data["kubernetes"]["service_account"],
        "__RUNTIME_IMAGE__": config_data["images"]["runtime"],
        "__EXPERIMENT_NAME__": f"{student}-search",
        "__N_ESTIMATORS_MIN__": str(config_data["katib"]["parameters"]["n_estimators"]["min"]),
        "__N_ESTIMATORS_MAX__": str(config_data["katib"]["parameters"]["n_estimators"]["max"]),
        "__MAX_DEPTH_MIN__": str(config_data["katib"]["parameters"]["max_depth"]["min"]),
        "__MAX_DEPTH_MAX__": str(config_data["katib"]["parameters"]["max_depth"]["max"]),
        "__MIN_SPLIT_MIN__": str(config_data["katib"]["parameters"]["min_samples_split"]["min"]),
        "__MIN_SPLIT_MAX__": str(config_data["katib"]["parameters"]["min_samples_split"]["max"]),
        "__MIN_LEAF_MIN__": str(config_data["katib"]["parameters"]["min_samples_leaf"]["min"]),
        "__MIN_LEAF_MAX__": str(config_data["katib"]["parameters"]["min_samples_leaf"]["max"]),
        "__MAX_TRIALS__": str(config_data["katib"]["max_trial_count"]),
        "__MAX_FAILED_TRIALS__": str(config_data["katib"]["max_failed_trial_count"]),
        "__PARALLEL_TRIALS__": str(config_data["katib"]["parallel_trial_count"]),
        "__CPU_REQUEST__": str(profile["requests"]["cpu"]),
        "__MEMORY_REQUEST__": str(profile["requests"]["memory"]),
        "__CPU_LIMIT__": str(profile["limits"]["cpu"]),
        "__MEMORY_LIMIT__": str(profile["limits"]["memory"]),
        "__SERVE_CPU_REQUEST__": str(serving_requests["cpu"]),
        "__SERVE_MEMORY_REQUEST__": str(serving_requests["memory"]),
        "__SERVE_CPU_LIMIT__": str(serving_limits["cpu"]),
        "__SERVE_MEMORY_LIMIT__": str(serving_limits["memory"]),
        "__NODE_SELECTOR_KEY__": next(iter(profile["node_selector"].keys())),
        "__NODE_SELECTOR_VALUE__": next(iter(profile["node_selector"].values())),
        "__GPU_LIMIT_LINE__": gpu_limit,
        "__SERVING_PORT__": str(config_data["serving"]["port"]),
        "__SERVING_REPLICAS__": str(config_data["serving"]["replicas"]),
        "__INFERENCE_HOST__": config_data["network"]["inference_host"],
    }


def render_file(template_path: Path, output_path: Path, replacements: dict[str, str]) -> None:
    content = template_path.read_text(encoding="utf-8")
    for key, value in replacements.items():
        content = content.replace(key, value)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT_DIR / "project.yaml"))
    args = parser.parse_args()

    config_data = load_project_config(args.config)
    if AUTO_CONFIG.exists():
        config_data = load_project_config(args.config)
    replacements = manifest_context(config_data)

    for template in TEMPLATE_DIR.glob("*.template"):
        output = RENDERED_DIR / template.name.replace(".template", "")
        render_file(template, output, replacements)


if __name__ == "__main__":
    main()
