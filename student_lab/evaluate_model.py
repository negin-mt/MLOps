from __future__ import annotations

import argparse
import json

from student_lab.project import (
    evaluate_predictions,
    latest_model_metadata,
    load_model_from_uri,
    load_project_config,
    resolve_dataset_uri,
    save_evaluation,
    holdout_split,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="project.yaml")
    args = parser.parse_args()

    config_data = load_project_config(args.config)
    metadata = latest_model_metadata(config_data)
    model = load_model_from_uri(metadata["model_uri"])
    _, _, x_test, _, y_test = holdout_split(config_data, resolve_dataset_uri(config_data))
    prediction = model.predict(x_test)
    metrics = evaluate_predictions(config_data["project"]["task"], y_test, prediction)
    report_uri = save_evaluation(config_data, metrics, metadata)
    print(json.dumps({"report_uri": report_uri, "metrics": metrics}, indent=2))


if __name__ == "__main__":
    main()

