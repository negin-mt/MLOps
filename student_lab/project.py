from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
import os
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import accuracy_score, f1_score, mean_absolute_error, r2_score, root_mean_squared_error
from sklearn.model_selection import train_test_split
import yaml

from student_lab.storage import get_bytes, is_s3_uri, list_objects, parse_s3_uri, put_bytes, put_json, read_csv


ROOT_DIR = Path(os.getenv("PROJECT_ROOT", str(Path.cwd())))
AUTO_CONFIG = Path(os.getenv("AUTO_CONFIG_PATH", str(ROOT_DIR / ".platform" / "platform.auto.yaml")))


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_project_config(path: str | Path = ROOT_DIR / "project.yaml") -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if AUTO_CONFIG.exists():
        auto_payload = yaml.safe_load(AUTO_CONFIG.read_text(encoding="utf-8")) or {}
        payload = deep_merge(payload, auto_payload)
    return payload


def resolve_dataset_uri(config_data: dict[str, Any], dataset_uri: str | None = None) -> str:
    if dataset_uri:
        return dataset_uri
    dataset_cfg = config_data["dataset"]
    uri = dataset_cfg["uri"]
    if not dataset_cfg.get("auto_select_latest", False) or not is_s3_uri(uri):
        return uri
    bucket, key = parse_s3_uri(uri)
    prefix = str(dataset_cfg.get("prefix") or Path(key).parent.as_posix()).strip("/")
    if prefix:
        prefix = f"{prefix}/"
    objects = list_objects(bucket, prefix)
    return f"s3://{bucket}/{objects[0]['Key']}" if objects else uri


def dataset_frame(config_data: dict[str, Any], dataset_uri: str | None = None) -> pd.DataFrame:
    uri = resolve_dataset_uri(config_data, dataset_uri)
    frame = read_csv(uri)
    required = config_data["dataset"]["feature_columns"] + [config_data["dataset"]["target_column"]]
    return frame[required].dropna().copy()


def holdout_split(config_data: dict[str, Any], dataset_uri: str | None = None):
    frame = dataset_frame(config_data, dataset_uri)
    feature_columns = config_data["dataset"]["feature_columns"]
    target_column = config_data["dataset"]["target_column"]
    x_train, x_test, y_train, y_test = train_test_split(
        frame[feature_columns],
        frame[target_column],
        test_size=float(config_data["dataset"].get("test_size", 0.2)),
        random_state=int(config_data["dataset"].get("random_state", 42)),
    )
    return frame, x_train, x_test, y_train, y_test


def build_model(config_data: dict[str, Any], params: dict[str, Any]) -> Any:
    kwargs = {
        "n_estimators": int(params["n_estimators"]),
        "max_depth": int(params["max_depth"]) if params.get("max_depth") is not None else None,
        "min_samples_split": int(params["min_samples_split"]),
        "min_samples_leaf": int(params["min_samples_leaf"]),
        "random_state": int(config_data["dataset"].get("random_state", 42)),
        "n_jobs": -1,
    }
    if config_data["project"]["task"] == "classification":
        return RandomForestClassifier(**kwargs)
    return RandomForestRegressor(**kwargs)


def evaluate_predictions(task: str, truth: Any, prediction: Any) -> dict[str, float]:
    if task == "classification":
        return {
            "accuracy": float(accuracy_score(truth, prediction)),
            "f1": float(f1_score(truth, prediction, average="weighted")),
        }
    return {
        "rmse": float(root_mean_squared_error(truth, prediction)),
        "mae": float(mean_absolute_error(truth, prediction)),
        "r2": float(r2_score(truth, prediction)),
    }


def resolve_params(config_data: dict[str, Any], overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    params = dict(config_data["model"]["defaults"])
    if overrides:
        params.update({key: value for key, value in overrides.items() if value is not None})
    return params


def train_bundle(config_data: dict[str, Any], params: dict[str, Any], dataset_uri: str | None = None) -> dict[str, Any]:
    resolved_dataset_uri = resolve_dataset_uri(config_data, dataset_uri)
    frame, x_train, x_test, y_train, y_test = holdout_split(config_data, resolved_dataset_uri)
    model = build_model(config_data, params)
    model.fit(x_train, y_train)
    prediction = model.predict(x_test)
    metrics = evaluate_predictions(config_data["project"]["task"], y_test, prediction)
    return {
        "model": model,
        "metrics": metrics,
        "dataset_uri": resolved_dataset_uri,
        "rows": len(frame),
        "x_test": x_test,
        "y_test": y_test,
    }


def objective_metric(config_data: dict[str, Any], metrics: dict[str, float]) -> float:
    return float(metrics[config_data["project"]["objective_metric_name"]])


def model_bucket(config_data: dict[str, Any]) -> str:
    return config_data["artifacts"]["bucket"]


def artifact_uri(config_data: dict[str, Any], prefix: str, filename: str) -> str:
    return f"s3://{model_bucket(config_data)}/{prefix}/{filename}"


def save_model_bundle(config_data: dict[str, Any], bundle: dict[str, Any], params: dict[str, Any], source: str) -> dict[str, str]:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    prefix = f"{config_data['artifacts'].get('model_prefix', 'models')}/{run_id}"
    model_uri = artifact_uri(config_data, prefix, "model.joblib")
    metrics_uri = artifact_uri(config_data, prefix, "metrics.json")
    metadata_uri = artifact_uri(config_data, prefix, "metadata.json")

    payload = BytesIO()
    joblib.dump(bundle["model"], payload)
    put_bytes(model_uri, payload.getvalue())
    put_json(metrics_uri, {"metrics": bundle["metrics"], "dataset_uri": bundle["dataset_uri"], "rows": bundle["rows"]})
    put_json(
        metadata_uri,
        {
            "source": source,
            "params": params,
            "dataset_uri": bundle["dataset_uri"],
            "metrics": bundle["metrics"],
            "model_uri": model_uri,
            "metrics_uri": metrics_uri,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return {"model_uri": model_uri, "metrics_uri": metrics_uri, "metadata_uri": metadata_uri}


def latest_model_metadata(config_data: dict[str, Any]) -> dict[str, Any]:
    bucket = model_bucket(config_data)
    prefix = config_data["artifacts"].get("model_prefix", "models")
    objects = [item for item in list_objects(bucket, prefix) if item["Key"].endswith("metadata.json")]
    if not objects:
        raise RuntimeError("No trained model metadata found")
    return json.loads(get_bytes(f"s3://{bucket}/{objects[0]['Key']}"))


def save_evaluation(config_data: dict[str, Any], metrics: dict[str, float], metadata: dict[str, Any]) -> str:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    uri = artifact_uri(config_data, f"{config_data['artifacts'].get('evaluation_prefix', 'evaluations')}/{run_id}", "report.json")
    put_json(uri, {"metrics": metrics, "model": metadata, "created_at": datetime.now(timezone.utc).isoformat()})
    return uri


def load_model_from_uri(uri: str) -> Any:
    payload = BytesIO(get_bytes(uri))
    return joblib.load(payload)


def compute_profile(config_data: dict[str, Any]) -> dict[str, Any]:
    target = str(config_data.get("compute", {}).get("target", "cpu")).lower().replace("-", "_")
    mode = str(config_data.get("cluster", {}).get("compute_mode", "simulated")).lower()
    if target == "cpu":
        return {
            "node_selector": {"mlops.openai/compute": "cpu"},
            "requests": config_data["compute"]["cpu"]["requests"],
            "limits": config_data["compute"]["cpu"]["limits"],
            "gpu": None,
        }
    if target in {"nvidia_sim", "nvidia"}:
        return {
            "node_selector": {"mlops.openai/accelerator": "nvidia"},
            "requests": config_data["compute"]["nvidia_sim"]["requests"],
            "limits": config_data["compute"]["nvidia_sim"]["limits"],
            "gpu": "nvidia.com/gpu" if mode == "real" else None,
        }
    if target in {"amd_sim", "amd"}:
        return {
            "node_selector": {"mlops.openai/accelerator": "amd"},
            "requests": config_data["compute"]["amd_sim"]["requests"],
            "limits": config_data["compute"]["amd_sim"]["limits"],
            "gpu": "amd.com/gpu" if mode == "real" else None,
        }
    raise ValueError(f"Unsupported compute target: {target}")
