"""Retrain the serving model from inspection results.

The dashboard is the only source of labels for the replayed period: the demo
sample carries no `PassOrFail`, so a row becomes training data only after a
worker inspects it and records the real outcome.

Training rows come from the database alone. Every prediction stores the 26
features that actually entered the model in `predictions.model_features`, after
the recording corrections have been applied, so a completed inspection carries
its own training row. Earlier this module recovered the features by joining
`record_id` back to the replay CSV; that worked for the demo but would not work
against a real line, where no such file exists.

Because the stored features are already corrected, they sit on the same scale as
`data/labeled_modeling.csv`, which 02_EDA writes with the same rules.

Retraining does not touch `labeled_modeling.csv`. Labels collected from
inspections accumulate in `RETRAIN_LABELS_PATH` and are concatenated at fit
time, so the analysis artefact stays authoritative and a reset can undo
everything by deleting one file.
"""

import json
import shutil
from datetime import datetime, timezone
from typing import Any

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .model_loader import activate_model, load_feature_columns, load_threshold_metrics
from .settings import (
    AUTO_RETRAIN_MIN_LABELS,
    BASE_TRAINING_DATA_PATH,
    INITIAL_MODEL_VERSION,
    MODEL_DIR,
    RETRAIN_ESTIMATOR_PARAMS,
    RETRAIN_LABELS_PATH,
    RETRAINED_MODEL_DIR,
    TRAINING_DROP_COLUMNS,
)


LABEL_COLUMN = "PassOrFail"
DEFECT_LABEL = "불량"


class RetrainError(RuntimeError):
    """재학습을 진행할 수 없을 때 발생한다."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def collect_labels(inspections: list[dict[str, Any]]) -> tuple[pd.DataFrame, list[str]]:
    """검사 완료 건을 학습 가능한 행으로 바꾼다.

    피처는 예측 시점에 저장한 `predictions.model_features`에서 읽는다.
    반환: (행 프레임, 건너뛴 이유 목록)
    """
    feature_columns = load_feature_columns()
    rows: list[dict[str, Any]] = []
    skipped: list[str] = []

    for inspection in inspections:
        record_id = str(inspection["record_id"])
        if not inspection.get("supported"):
            skipped.append(f"{record_id}: 모델 지원 대상이 아님")
            continue

        try:
            features = json.loads(inspection.get("model_features") or "{}")
        except (TypeError, ValueError):
            features = {}
        if not features:
            # 이 컬럼이 생기기 전에 예측된 행이다. 초기화하면 다시 채워진다.
            skipped.append(f"{record_id}: 저장된 학습 피처가 없음 (초기화 후 재생 필요)")
            continue

        missing = [column for column in feature_columns if column not in features]
        if missing:
            skipped.append(f"{record_id}: 학습 피처 누락 {len(missing)}개")
            continue

        row = {column: float(features[column]) for column in feature_columns}
        row[LABEL_COLUMN] = 1 if inspection.get("actual_label") == DEFECT_LABEL else 0
        row["record_id"] = record_id
        row["completed_at"] = inspection.get("completed_at")
        rows.append(row)

    return pd.DataFrame(rows), skipped


def load_accumulated_labels() -> pd.DataFrame:
    if not RETRAIN_LABELS_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(RETRAIN_LABELS_PATH)


def save_accumulated_labels(frame: pd.DataFrame) -> None:
    RETRAIN_LABELS_PATH.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(RETRAIN_LABELS_PATH, index=False, encoding="utf-8")


def merge_labels(existing: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    """같은 record_id는 최신 검사 결과로 덮어쓴다."""
    if existing.empty:
        return fresh
    if fresh.empty:
        return existing
    merged = pd.concat([existing, fresh], ignore_index=True)
    return merged.drop_duplicates(subset="record_id", keep="last").reset_index(drop=True)


def _matrix_from_base(base: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """기준 학습 데이터를 모델 입력 행렬로 만든다 (06_Final_Model.ipynb 셀 10과 동일)."""
    feature_columns = load_feature_columns()
    features = base.drop(columns=[c for c in TRAINING_DROP_COLUMNS if c in base.columns])
    target = features[LABEL_COLUMN]
    features = features.drop(columns=LABEL_COLUMN)
    features = pd.get_dummies(features, columns=["Part"], drop_first=True, dtype=int)
    for column in feature_columns:
        if column not in features.columns:
            features[column] = 0
    return features[feature_columns], target


def _matrix_from_labels(labels: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """검사로 확보한 라벨을 행렬로 만든다.

    이 행들은 예측 시점에 저장된 값이라 이미 26개 피처 형태다. 기준 데이터처럼
    `Part` 문자열을 더미로 펼치는 단계가 없다.
    """
    feature_columns = load_feature_columns()
    target = labels[LABEL_COLUMN]
    features = labels.reindex(columns=feature_columns).fillna(0)
    return features, target


def build_training_frame(labels: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, dict[str, int]]:
    if not BASE_TRAINING_DATA_PATH.exists():
        raise RetrainError(f"기준 학습 데이터가 없습니다: {BASE_TRAINING_DATA_PATH}")
    base = pd.read_csv(BASE_TRAINING_DATA_PATH, index_col=0)
    base_features, base_target = _matrix_from_base(base)

    if labels.empty:
        features, target = base_features, base_target
    else:
        label_features, label_target = _matrix_from_labels(labels)
        features = pd.concat([base_features, label_features], ignore_index=True)
        target = pd.concat([base_target, label_target], ignore_index=True)

    counts = {
        "base_records": int(len(base_features)),
        "base_defects": int((base_target == 1).sum()),
        "added_records": int(len(labels)),
        "added_defects": int((labels[LABEL_COLUMN] == 1).sum()) if not labels.empty else 0,
        "train_records": int(len(features)),
        "train_defects": int((target == 1).sum()),
    }
    return features, target, counts


def next_version(current: str | None) -> str:
    """v1.1.0 -> v1.1.1 처럼 패치 자리를 올린다.

    재학습은 검사 5건마다 돌 수 있어 시연 한 번에도 여러 번 일어난다. 라벨
    5건 추가가 마이너 버전 하나만큼의 변화는 아니므로 패치 자리를 쓴다.
    마이너 자리는 검증을 다시 수행해 성능표를 확정했을 때 올린다.
    """
    text = (current or INITIAL_MODEL_VERSION).lstrip("v")
    parts = text.split(".")
    while len(parts) < 3:
        parts.append("0")
    try:
        parts[2] = str(int(parts[2]) + 1)
    except ValueError:
        return f"{current}-retrained"
    return "v" + ".".join(parts)


def retrain(
    repository,
    actor: str,
    reason: str,
    trigger: str = "수동",
) -> dict[str, Any]:
    """검사 결과를 반영해 모델을 다시 학습하고 서빙 모델을 교체한다."""
    active = repository.active_model()
    last_trained_at = active["created_at"] if active and active["source"] != "초기 배포" else None

    inspections = repository.completed_inspections_since(last_trained_at)
    fresh, skipped = collect_labels(inspections)
    accumulated = merge_labels(load_accumulated_labels(), fresh)

    if accumulated.empty:
        raise RetrainError(
            "재학습에 쓸 검사 결과가 없습니다. 검사 대기열에서 검사를 완료한 뒤 다시 실행하세요."
        )

    features, target, counts = build_training_frame(accumulated)

    model = Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            ("rf", RandomForestClassifier(**RETRAIN_ESTIMATOR_PARAMS)),
        ]
    )
    model.fit(features, target)

    version = next_version(active["version"] if active else INITIAL_MODEL_VERSION)
    RETRAINED_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    path = RETRAINED_MODEL_DIR / f"final_rf_part_balanced_{version}.pkl"
    joblib.dump(model, path)
    # 레지스트리에는 MODEL_DIR 기준 상대 경로를 저장한다. 테스트는 다른 폴더를
    # 쓰므로 폴더 이름을 하드코딩하면 안 된다.
    model_file = path.relative_to(MODEL_DIR).as_posix()

    save_accumulated_labels(accumulated)
    entry = repository.register_model(
        {
            "version": version,
            "model_file": model_file,
            "parent_version": active["version"] if active else None,
            "source": "재학습",
            "trigger": trigger,
            "reason": reason,
            "created_by": actor,
            "created_at": _now(),
            "train_records": counts["train_records"],
            "train_defects": counts["train_defects"],
            "added_records": counts["added_records"],
            "added_defects": counts["added_defects"],
        }
    )
    activate_model(model_file)

    return {
        **entry,
        "counts": counts,
        "skipped": skipped,
        "new_labels": int(len(fresh)),
    }


def clear_retrained_artifacts() -> None:
    """초기화 시 재학습 산출물을 지운다."""
    if RETRAIN_LABELS_PATH.exists():
        RETRAIN_LABELS_PATH.unlink()
    if RETRAINED_MODEL_DIR.exists():
        shutil.rmtree(RETRAINED_MODEL_DIR, ignore_errors=True)


def operating_precision(summary_operating: dict[str, int]) -> float | None:
    denominator = summary_operating.get("tp", 0) + summary_operating.get("fp", 0)
    if denominator == 0:
        return None
    return summary_operating["tp"] / denominator


def retrain_status(repository, threshold: float, summary_operating: dict[str, int]) -> dict[str, Any]:
    """재학습 권고 여부와 자동 실행까지 남은 검사 수를 계산한다."""
    active = repository.active_model()
    last_trained_at = active["created_at"] if active and active["source"] != "초기 배포" else None
    pending = repository.completed_inspections_since(last_trained_at)
    pending_count = len(pending)

    # 검증 기준 Precision@k: 현재 threshold에 가장 가까운 운영점의 값
    metrics = load_threshold_metrics()
    reference = min(metrics, key=lambda row: abs(row["threshold"] - threshold)) if metrics else None
    expected_precision = reference["precision_at_k"] if reference else None
    observed_precision = operating_precision(summary_operating)

    reasons: list[str] = []
    if pending_count >= AUTO_RETRAIN_MIN_LABELS:
        reasons.append(
            f"마지막 재학습 이후 검사 결과가 {pending_count}건 쌓였습니다 "
            f"(자동 기준 {AUTO_RETRAIN_MIN_LABELS}건)."
        )
    # 표본이 너무 적으면 성능 판단을 하지 않는다. 불량률이 1% 수준이라
    # 몇 건으로는 Precision이 0이 나오는 것이 정상이다.
    if (
        observed_precision is not None
        and expected_precision
        and pending_count >= AUTO_RETRAIN_MIN_LABELS
        and observed_precision < expected_precision / 2
    ):
        reasons.append(
            f"운영 Precision {observed_precision * 100:.1f}%가 검증 기준 "
            f"{expected_precision * 100:.1f}%의 절반 아래입니다."
        )

    return {
        "active_version": active["version"] if active else None,
        "active_source": active["source"] if active else None,
        "last_trained_at": active["created_at"] if active else None,
        "pending_inspections": pending_count,
        "auto_threshold": AUTO_RETRAIN_MIN_LABELS,
        "remaining_for_auto": max(0, AUTO_RETRAIN_MIN_LABELS - pending_count),
        "expected_precision": expected_precision,
        "observed_precision": observed_precision,
        "recommended": bool(reasons),
        "reasons": reasons,
    }
