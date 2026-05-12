from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from student_lab.project import latest_model_metadata, load_model_from_uri, load_project_config


app = FastAPI(title="student-model-api", version="1.0.0")
_MODEL: Any | None = None
_METADATA: dict[str, Any] | None = None
_CONFIG: dict[str, Any] | None = None


class PredictionRequest(BaseModel):
    records: list[dict[str, float]]


def ensure_model() -> tuple[Any, dict[str, Any], dict[str, Any]]:
    global _MODEL, _METADATA, _CONFIG
    if _MODEL is None:
        _CONFIG = load_project_config()
        _METADATA = latest_model_metadata(_CONFIG)
        _MODEL = load_model_from_uri(_METADATA["model_uri"])
    return _MODEL, _METADATA or {}, _CONFIG or {}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metadata")
def metadata() -> dict[str, Any]:
    _, model_metadata, config_data = ensure_model()
    return {
        "project": config_data["project"]["name"],
        "student": config_data["student"]["name"],
        "model": model_metadata,
    }


@app.post("/predict")
def predict(payload: PredictionRequest) -> dict[str, Any]:
    model, _, config_data = ensure_model()
    feature_columns = config_data["dataset"]["feature_columns"]
    matrix = [[record[column] for column in feature_columns] for record in payload.records]
    prediction = model.predict(matrix)
    return {"predictions": prediction.tolist()}
