"""Retrain the serving model from inspection results.

The dashboard is the only source of labels for the replayed period: the demo
sample carries no `PassOrFail`, so a row becomes training data only after a
worker inspects it and records the real outcome.

Two facts shape this module.

1. The database keeps only eight process values per prediction
   (`prediction.DISPLAY_PROCESS_COLUMNS`), not the 26 the model needs. The
   missing 18 are recovered by joining `predictions.record_id` back to the
   replay CSV, whose `_id` is the same identifier.
2. `data/labeled_modeling.csv` is already corrected (02_EDA writes it), while
   the replay CSV holds raw recorded values. New rows therefore pass through
   `apply_record_corrections` before they are appended, or the two halves of the
   training set would sit on different scales.

Retraining does not touch `labeled_modeling.csv`. Labels collected from
inspections accumulate in `RETRAIN_LABELS_PATH` and are concatenated at fit
time, so the analysis artefact stays authoritative and a reset can undo
everything by deleting one file.
"""

import shutil
from datetime import datetime, timezone
from typing import Any

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .corrections import apply_record_corrections
from .demo_data import get_demo_data
from .model_loader import activate_model, load_feature_columns, load_threshold_metrics
from .settings import (
    AUTO_RETRAIN_MIN_LABELS,
    BASE_TRAINING_DATA_PATH,
    INITIAL_MODEL_VERSION,
    MODEL_DIR,
    RETRAIN_ESTIMATOR_PARAMS,
    RETRAIN_LABELS_PATH,
    RETRAINED_MODEL_DIR,
    SUPPORTED_PARTS,
    TRAINING_DROP_COLUMNS,
)


LABEL_COLUMN = "PassOrFail"
DEFECT_LABEL = "불량"


class RetrainError(RuntimeError):
    """재학습을 진행할 수 없을 때 발생한다."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def part_of(part_name: Any) -> str | None:
    """PART_NAME에서 학습에 쓰는 Part 범주를 만든다 (앞 3글자 + 뒤 2글자)."""
    if part_name is None:
        return None
    text = str(part_name)
    return text[:3] + text[-2:] if len(text) >= 5 else None


def _replay_rows_by_id() -> dict[str, dict[str, Any]]:
    """재생 표본을 _id로 찾을 수 있게 색인한다."""
    index: dict[str, dict[str, Any]] = {}
    for row in get_demo_data().records:
        identifier = row.get("_id") or row.get("record_id")
        if identifier is not None:
            index[str(identifier)] = row
    return index


def collect_labels(inspections: list[dict[str, Any]]) -> tuple[pd.DataFrame, list[str]]:
    """검사 완료 건을 학습 가능한 행으로 바꾼다.

    반환: (행 프레임, 건너뛴 이유 목록)
    """
    feature_columns = load_feature_columns()
    numeric_columns = [c for c in feature_columns if not c.startswith("Part_")]
    replay = _replay_rows_by_id()

    rows: list[dict[str, Any]] = []
    skipped: list[str] = []

    for inspection in inspections:
        record_id = str(inspection["record_id"])
        if not inspection.get("supported"):
            skipped.append(f"{record_id}: 모델 지원 대상이 아님")
            continue
        source = replay.get(record_id)
        if source is None:
            skipped.append(f"{record_id}: 재생 표본에서 원본 행을 찾지 못함")
            continue

        part = inspection.get("part") or part_of(source.get("PART_NAME"))
        if part not in SUPPORTED_PARTS:
            skipped.append(f"{record_id}: 학습되지 않은 Part 범주({part})")
            continue

        raw: dict[str, float] = {}
        invalid = False
        for column in numeric_columns:
            value = source.get(column)
            if value is None:
                invalid = True
                break
            try:
                raw[column] = float(value)
            except (TypeError, ValueError):
                invalid = True
                break
        if invalid:
            skipped.append(f"{record_id}: 공정 변수 결측 또는 형식 오류")
            continue

        # 학습 데이터와 같은 스케일로 맞춘다. 서빙 예측이 쓰는 함수와 동일하다.
        corrected, _ = apply_record_corrections(raw)
        corrected["Part"] = part
        corrected[LABEL_COLUMN] = 1 if inspection.get("actual_label") == DEFECT_LABEL else 0
        corrected["record_id"] = record_id
        corrected["completed_at"] = inspection.get("completed_at")
        rows.append(corrected)

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


def _build_matrix(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    feature_columns = load_feature_columns()
    features = frame.drop(columns=[c for c in TRAINING_DROP_COLUMNS if c in frame.columns])
    features = features.drop(columns=[c for c in ("record_id", "completed_at") if c in features.columns])
    target = features[LABEL_COLUMN]
    features = features.drop(columns=LABEL_COLUMN)
    features = pd.get_dummies(features, columns=["Part"], drop_first=True, dtype=int)
    # 검사 표본에 없는 Part 더미가 생기지 않도록 학습 시 컬럼 순서에 맞춘다.
    for column in feature_columns:
        if column not in features.columns:
            features[column] = 0
    return features[feature_columns], target


def build_training_frame(labels: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, dict[str, int]]:
    if not BASE_TRAINING_DATA_PATH.exists():
        raise RetrainError(f"기준 학습 데이터가 없습니다: {BASE_TRAINING_DATA_PATH}")
    base = pd.read_csv(BASE_TRAINING_DATA_PATH, index_col=0)

    if labels.empty:
        combined = base
    else:
        # 기준 데이터에 있는 컬럼만 남겨 붙인다.
        usable = [c for c in labels.columns if c in base.columns]
        combined = pd.concat([base, labels[usable]], ignore_index=True)

    features, target = _build_matrix(combined)
    counts = {
        "base_records": int(len(base)),
        "base_defects": int((base[LABEL_COLUMN] == 1).sum()),
        "added_records": int(len(labels)),
        "added_defects": int((labels[LABEL_COLUMN] == 1).sum()) if not labels.empty else 0,
        "train_records": int(len(features)),
        "train_defects": int((target == 1).sum()),
    }
    return features, target, counts


def next_version(current: str | None) -> str:
    """v1.1.0 -> v1.2.0 처럼 마이너 자리를 올린다."""
    text = (current or INITIAL_MODEL_VERSION).lstrip("v")
    parts = text.split(".")
    while len(parts) < 3:
        parts.append("0")
    try:
        parts[1] = str(int(parts[1]) + 1)
    except ValueError:
        return f"{current}-retrained"
    parts[2] = "0"
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
