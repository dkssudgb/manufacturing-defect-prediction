import json
from functools import lru_cache
from typing import Any

import joblib

from .settings import FEATURE_COLUMNS_PATH, MODEL_INFO_PATH, MODEL_PATH, THRESHOLD_METRICS_PATH


@lru_cache(maxsize=1)
def load_model():
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"모델 파일을 찾을 수 없습니다: {MODEL_PATH}")
    return joblib.load(MODEL_PATH)


@lru_cache(maxsize=1)
def load_feature_columns() -> list[str]:
    columns = joblib.load(FEATURE_COLUMNS_PATH)
    if not isinstance(columns, list) or not columns:
        raise ValueError("feature_columns.pkl 형식이 올바르지 않습니다.")
    return columns


def _load_json(path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


@lru_cache(maxsize=1)
def load_model_info() -> dict[str, Any]:
    return _load_json(MODEL_INFO_PATH)


@lru_cache(maxsize=1)
def load_threshold_metrics() -> list[dict[str, Any]]:
    return _load_json(THRESHOLD_METRICS_PATH)

