"""Re-measure the serving model's validation numbers.

The AP and the inspection-volume table shown on the 모델 정보 screen come from
cross-validating the *training procedure on the training data*, not from scoring
the saved pickle. Cross-validation has to refit, so this module rebuilds the
same pipeline `retraining` uses and runs 5-fold x 3-repeat CV over the current
training set (base + labels collected from inspections).

Why this is a separate, explicit action rather than part of every retrain:

- It costs about 14x a retrain (7.6s vs 0.53s). Auto-retrain runs inside
  `complete_inspection`, so folding it in would stall the save by that much.
- It cannot detect what a retrain actually changes. Repeating the CV on
  identical data with a different fold seed moves AP across 0.355 ~ 0.391, and
  five new labels are 0.1% of 5,230 rows. The table would change by measurement
  noise while looking like the model improved.

Numbers produced here will not match `models/threshold_metrics.json` exactly
even on the untouched base data: that file came from a different fold
assignment. The threshold cuts agree to 3-4 decimals; recall at a given volume
moves by a few points. That spread is the measurement's own variance, which is
the reason this is a deliberate action.
"""

from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import average_precision_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .retraining import build_training_frame, load_accumulated_labels
from .settings import (
    DAILY_PRODUCTION_BASELINE,
    RETRAIN_ESTIMATOR_PARAMS,
    VALIDATION_FOLDS,
    VALIDATION_INSPECT_RATIOS,
    VALIDATION_REPEATS,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pipeline() -> Pipeline:
    return Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            ("rf", RandomForestClassifier(**RETRAIN_ESTIMATOR_PARAMS)),
        ]
    )


def _volume_metrics(probabilities: np.ndarray, target: np.ndarray) -> dict[float, dict[str, float]]:
    """검사 물량 k별 성능. 확률 상위 k%를 검사했다면을 계산한다."""
    order = np.argsort(-probabilities)
    defects = float(target.sum())
    result: dict[float, dict[str, float]] = {}
    for ratio in VALIDATION_INSPECT_RATIOS:
        count = max(1, int(round(len(probabilities) * ratio)))
        selected = order[:count]
        caught = float(target[selected].sum())
        recall = caught / defects if defects else 0.0
        result[ratio] = {
            # 상위 k번째 제품의 확률이 그 물량에 대응하는 컷이다
            "threshold": float(probabilities[order[count - 1]]),
            "recall_at_k": recall,
            "precision_at_k": caught / count,
            "lift": recall / ratio if ratio else 0.0,
        }
    return result


def run_validation() -> dict[str, Any]:
    """현재 학습 데이터로 교차검증을 다시 수행한다."""
    features, target, counts = build_training_frame(load_accumulated_labels())
    values = target.to_numpy()

    average_precisions: list[float] = []
    per_repeat: list[dict[float, dict[str, float]]] = []
    for repeat in range(VALIDATION_REPEATS):
        splitter = StratifiedKFold(
            n_splits=VALIDATION_FOLDS, shuffle=True, random_state=repeat
        )
        probabilities = cross_val_predict(
            _pipeline(), features, values, cv=splitter, method="predict_proba"
        )[:, 1]
        average_precisions.append(float(average_precision_score(values, probabilities)))
        per_repeat.append(_volume_metrics(probabilities, values))

    rows = []
    for ratio in VALIDATION_INSPECT_RATIOS:
        recalls = [repeat[ratio]["recall_at_k"] for repeat in per_repeat]
        rows.append(
            {
                "threshold": round(float(np.mean([r[ratio]["threshold"] for r in per_repeat])), 4),
                "inspect_ratio": ratio,
                "inspection_count_per_day": round(ratio * DAILY_PRODUCTION_BASELINE, 1),
                "recall_at_k": round(float(np.mean(recalls)), 4),
                "recall_at_k_std": round(float(np.std(recalls)), 4),
                "precision_at_k": round(
                    float(np.mean([r[ratio]["precision_at_k"] for r in per_repeat])), 4
                ),
                "lift": round(float(np.mean([r[ratio]["lift"] for r in per_repeat])), 2),
                "daily_production_baseline": DAILY_PRODUCTION_BASELINE,
            }
        )

    validation = {
        # 레이블과 다른 필드가 말하는 것을 반복하지 않는다. 건수와 불량 수는
        # records/defects로 따로 내려가고 화면이 한 줄로 조립한다.
        "method": f"{VALIDATION_FOLDS}-fold × {VALIDATION_REPEATS}반복 교차검증",
        "records": counts["train_records"],
        "defects": counts["train_defects"],
        "average_precision_mean": round(float(np.mean(average_precisions)), 4),
        "average_precision_std": round(float(np.std(average_precisions)), 4),
        "average_precision_per_repeat": [round(value, 4) for value in average_precisions],
        "daily_production_records": DAILY_PRODUCTION_BASELINE,
        # 화면에 그대로 나가는 문구라 다른 화면 문구와 같은 존댓말로 쓴다.
        # 시연에서 분석 문서를 함께 제출하지 않으므로 문서 참조는 넣지 않는다.
        # 화면은 07_2 수치와 나란히 보여주는 문장을 직접 조립한다.
        # 이 값은 그 자료를 불러오지 못했을 때 쓰는 대체 문구다.
        "warning": "같은 기간 교차검증이라 최상의 조건. 시간순으로 재학습하며 재면 훨씬 낮아짐",
        "daily_basis_note": (
            f"라벨 데이터 하루 평균 생산량 {DAILY_PRODUCTION_BASELINE}건 기준. "
            "시연 재생 건수와는 다른 기준"
        ),
        "measured_at": _now(),
    }
    return {"validation": validation, "threshold_metrics": rows, "counts": counts}
