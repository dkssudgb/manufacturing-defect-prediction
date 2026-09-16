import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import joblib

from .settings import (
    FEATURE_COLUMNS_PATH,
    MODEL_DIR,
    MODEL_INFO_PATH,
    MODEL_PATH,
    THRESHOLD_METRICS_PATH,
    WALKFORWARD_PATH,
)


# 서빙 중인 모델 파일. 재학습이 성공하면 activate_model이 이 값을 옮기고
# 캐시를 비운다. 경로를 캐시 키로 쓰기 때문에 같은 프로세스에서 교체가 된다.
_active_model_path: Path = MODEL_PATH


def resolve_model_path(model_file: str | None) -> Path:
    """레지스트리에 기록된 파일 이름을 실제 경로로 바꾼다."""
    if not model_file:
        return MODEL_PATH
    candidate = Path(model_file)
    return candidate if candidate.is_absolute() else MODEL_DIR / model_file


def activate_model(model_file: str | None) -> Path:
    """서빙 모델을 교체한다. 다음 예측부터 새 모델이 쓰인다."""
    global _active_model_path
    path = resolve_model_path(model_file)
    if not path.exists():
        raise FileNotFoundError(f"모델 파일을 찾을 수 없습니다: {path}")
    _active_model_path = path
    _load_model_file.cache_clear()
    return path


def active_model_path() -> Path:
    return _active_model_path


@lru_cache(maxsize=4)
def _load_model_file(path: str):
    return joblib.load(path)


def load_model():
    if not _active_model_path.exists():
        raise FileNotFoundError(f"모델 파일을 찾을 수 없습니다: {_active_model_path}")
    return _load_model_file(str(_active_model_path))


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


@lru_cache(maxsize=1)
def load_walkforward_reference() -> dict[str, Any]:
    """07_2에서 측정한 재학습 주기별 성능. 재학습이 왜 필요한지의 근거다."""
    if not WALKFORWARD_PATH.exists():
        return {"rows": [], "note": "walkforward_cadence.json이 없습니다."}
    return _load_json(WALKFORWARD_PATH)
